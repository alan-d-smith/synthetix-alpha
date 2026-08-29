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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("--underlyings", help="comma list; default from spec")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--equity", type=float, default=100_000.0)
    p.add_argument("--out")
    p.add_argument("--trades-dir")
    p.add_argument("--source", default="kaggle", choices=["kaggle", "dolt"], help="dolt = 2019-present coarse surfaces (out-of-sample)")
    a = p.parse_args()
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
