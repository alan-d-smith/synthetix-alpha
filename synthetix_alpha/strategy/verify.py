"""Adversarial checks for a candidate spec: parameter fragility, out-of-sample regimes, P&L concentration.

python -m synthetix_alpha.strategy.verify spec.json [--oos AAPL,NVDA,TSLA] [--dolt SPY]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from synthetix_alpha.strategy.run import backtest
from synthetix_alpha.strategy.spec import Spec

PERTURBATIONS = {
    "delta_short": [-0.05, 0.05], "delta_long": [-0.05, 0.05], "dte": [-10, 10],
    "profit_target": [-0.25, 0.25], "stop_loss": [-0.25, 0.25], "entry_every_days": [-2, 2],
    "signal": [-0.1, 0.1], "slippage": [0.5], "dte_exit": [-7, 7],
}


def score(s: dict) -> float:
    if not s or s["total_trades"] < 40:
        return -9.0
    return (0.5 * s["mean_sharpe"] + 0.5 * s["min_sharpe"] + 2 * s["worst_year"]
            + 3 * max(s["worst_drawdown"], -1) + (s["positive_years"] - 1))


def perturb(spec: Spec, kind: str, delta: float) -> Spec | None:
    s = copy.deepcopy(spec)
    s.name = f"{spec.name}__{kind}{delta:+g}"
    opts = [l for l in s.legs if l.type != "stock" and l.delta is not None]
    try:
        if kind == "delta_short" and (short := [l for l in opts if l.side == "short"]):
            for l in short:
                l.delta = round(l.delta + delta, 3)
        elif kind == "delta_long" and (long_ := [l for l in opts if l.side == "long"]):
            for l in long_:
                l.delta = round(l.delta + delta, 3)
        elif kind == "dte":
            s.dte_target, s.dte_min, s.dte_max = (int(s.dte_target + delta), int(s.dte_min + delta), int(s.dte_max + delta))
        elif kind == "signal":
            s.signal = {k: [None if lo is None else round(lo + delta * abs(lo or 1), 4),
                            None if hi is None else round(hi + delta * abs(hi or 1), 4)] for k, (lo, hi) in s.signal.items()}
        elif kind == "slippage":
            s.slippage = min(1.0, s.slippage + delta)
        elif getattr(s, kind, None) is not None:
            v = getattr(s, kind)
            setattr(s, kind, max(1, int(round(v + delta))) if isinstance(v, int) else round(v * (1 + delta), 3))
        else:
            return None
        s.validate()
        return s
    except (ValueError, TypeError):
        return None


def concentration(trades_csv: Path) -> dict:
    t = pd.read_csv(trades_csv)
    if t.empty:
        return {}
    pnl = t["pnl"].sort_values(ascending=False)
    total = pnl.sum()
    return {"n": len(pnl), "total_pnl": round(float(total), 1),
            "top5_share": round(float(pnl.head(5).sum() / total), 3) if total else None,
            "best": round(float(pnl.max()), 1), "worst": round(float(pnl.min()), 1),
            "median": round(float(pnl.median()), 1)}


def verify(spec: Spec, oos=(), dolt=(), out_dir: Path = Path("datasets/research/verify")) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = backtest(spec, trades_dir=out_dir)
    report = {"name": spec.name, "base": base["summary"], "base_score": score(base["summary"]),
              "base_per_underlying": {u: {k: m[k] for k in ("sharpe", "n_trades", "max_drawdown")} | {"yearly": m["yearly"]}
                                      for u, m in base["results"].items()},
              "concentration": {u: concentration(out_dir / f"{spec.name}_{u}_kaggle.csv") for u in base["results"]},
              "fragility": {}, "oos": {}}
    for kind, deltas in PERTURBATIONS.items():
        for d in deltas:
            p = perturb(spec, kind, d)
            if p is None:
                continue
            try:
                report["fragility"][p.name.split("__")[1]] = round(score(backtest(p)["summary"]), 3)
            except Exception as e:
                report["fragility"][p.name.split("__")[1]] = f"error: {type(e).__name__}"
    vals = [v for v in report["fragility"].values() if isinstance(v, float)]
    report["fragility_summary"] = {"n": len(vals), "median": round(float(np.median(vals)), 3) if vals else None,
                                   "min": round(min(vals), 3) if vals else None,
                                   "share_above_half_base": round(float(np.mean([v > 0.5 * report["base_score"] for v in vals])), 2) if vals else None}
    for u in oos:
        try:
            r = backtest(spec, underlyings=[u])
            report["oos"][u] = {"score": round(score(r["summary"]), 3), **{k: round(v, 4) for k, v in r["summary"].items()},
                                "yearly": r["results"][u]["yearly"]}
        except Exception as e:
            report["oos"][u] = f"error: {type(e).__name__}: {e}"
    for u in dolt:
        try:
            r = backtest(spec, underlyings=[u], source="dolt")
            report["oos"][f"{u}@dolt"] = {"score": round(score(r["summary"]), 3), **{k: round(v, 4) for k, v in r["summary"].items()},
                                          "yearly": r["results"][u]["yearly"]}
        except Exception as e:
            report["oos"][f"{u}@dolt"] = f"error: {type(e).__name__}: {e}"
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("--oos", default="", help="comma list of underlyings not used in fitting")
    p.add_argument("--dolt", default="", help="comma list to run against the Dolt surface")
    p.add_argument("--out")
    a = p.parse_args()
    r = verify(Spec.load(a.spec), [u for u in a.oos.split(",") if u], [u for u in a.dolt.split(",") if u])
    Path(a.out or f"datasets/research/verify/{r['name']}_verify.json").write_text(json.dumps(r, indent=2, default=str))
    print(json.dumps(r, indent=1, default=str))


if __name__ == "__main__":
    main()
