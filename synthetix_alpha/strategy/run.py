"""Backtest a spec over its underlyings: python -m synthetix_alpha.strategy.run spec.json [--out results.json]"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

from synthetix_alpha.strategy.data import EngineData
from synthetix_alpha.strategy.engine import run
from synthetix_alpha.strategy.spec import Spec

KEYS = ("total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "n_trades", "win_rate", "profit_factor", "avg_days")


def backtest(spec: Spec, underlyings=None, start=None, end=None, equity0=100_000.0, trades_dir=None, source="kaggle") -> dict:
    results = {}
    for u in underlyings or spec.underlyings:
        data = EngineData.load(u, dte_max=spec.dte_max + max(l.dte_offset for l in spec.legs) + 1, start=start, end=end, source=source)
        r = run(spec, data, equity0)
        results[u] = r.metrics
        if trades_dir:
            Path(trades_dir).mkdir(parents=True, exist_ok=True)
            r.trades.to_csv(Path(trades_dir) / f"{spec.name}_{u}_{source}.csv", index=False)
            r.equity.to_csv(Path(trades_dir) / f"{spec.name}_{u}_{source}_equity.csv")
    sharpes = [m["sharpe"] for m in results.values() if m]
    yearly = [v for m in results.values() if m for v in m["yearly"].values()]
    summary = {"mean_sharpe": float(np.mean(sharpes)) if sharpes else 0.0, "min_sharpe": float(min(sharpes)) if sharpes else 0.0,
               "worst_year": float(min(yearly)) if yearly else 0.0, "positive_years": float(np.mean([y > 0 for y in yearly])) if yearly else 0.0,
               "worst_drawdown": float(min(m["max_drawdown"] for m in results.values() if m)) if sharpes else 0.0,
               "total_trades": int(sum(m["n_trades"] for m in results.values() if m))}
    return {"spec": spec.to_dict(), "results": results, "summary": summary}


def backtest_combo(specs: list, weights=None, equity0: float = 100_000.0, source: str = "kaggle") -> dict:
    """Combine sleeves at the return level. Each sleeve runs on full capital, so integer contract rounding
    behaves as it would standalone; only the weighted returns are blended."""
    import pandas as pd

    from synthetix_alpha.strategy.engine import metrics, run

    weights = weights or [1.0 / len(specs)] * len(specs)
    rets, per, trades = [], {}, 0
    for spec, w in zip(specs, weights):
        legs = []
        for u in spec.underlyings:
            data = EngineData.load(u, dte_max=spec.dte_max + max(l.dte_offset for l in spec.legs) + 1, source=source)
            r = run(spec, data, equity0)
            legs.append(r.equity.pct_change())
            trades += r.metrics["n_trades"]
        sleeve = pd.concat(legs, axis=1).mean(axis=1)  # equal weight across the sleeve's underlyings
        per[spec.name] = {"weight": w, "sharpe": round(_sharpe(sleeve), 3)}
        rets.append(sleeve * w)
    blended = pd.concat(rets, axis=1).fillna(0.0).sum(axis=1)
    curve = equity0 * (1 + blended).cumprod()
    m = metrics(curve, pd.DataFrame(), equity0)
    m["n_trades"] = trades
    return {"per_sleeve": per, "combined": m,
            "summary": {"mean_sharpe": m["sharpe"], "min_sharpe": m["sharpe"], "worst_year": min(m["yearly"].values()),
                        "positive_years": sum(v > 0 for v in m["yearly"].values()) / max(len(m["yearly"]), 1),
                        "worst_drawdown": m["max_drawdown"], "total_trades": trades}}


def _sharpe(returns) -> float:
    r = returns.dropna()
    return float(r.mean() / r.std() * (252 ** 0.5)) if len(r) > 1 and r.std() > 0 else 0.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("spec", help="a Spec json, or a portfolio json with sleeves and weights")
    p.add_argument("--underlyings", help="comma list; default from spec")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--equity", type=float, default=100_000.0)
    p.add_argument("--out")
    p.add_argument("--trades-dir")
    p.add_argument("--source", default="kaggle", choices=["kaggle", "dolt"], help="dolt = 2019-present coarse surfaces (out-of-sample)")
    a = p.parse_args()
    raw = json.loads(Path(a.spec).read_text())
    if "sleeves" in raw:
        c = backtest_combo([Spec.load(x) for x in raw["sleeves"]], raw.get("weights"), a.equity, a.source)
        print("sleeves:", json.dumps(c["per_sleeve"]))
        print("combined:", json.dumps({k: round(v, 4) for k, v in c["summary"].items()}))
        return
    spec = Spec.load(a.spec)
    out = backtest(spec, a.underlyings.split(",") if a.underlyings else None, a.start, a.end, a.equity, a.trades_dir, a.source)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2, default=str))
    for u, m in out["results"].items():
        row = " ".join(f"{k}={m[k]:.3g}" if isinstance(m.get(k), float) else f"{k}={m.get(k)}" for k in KEYS)
        print(f"{u}: {row} yearly={ {y: round(v, 3) for y, v in m['yearly'].items()} } exits={m['exit_reasons']}")
    print("summary:", json.dumps(out["summary"]))


if __name__ == "__main__":
    main()
