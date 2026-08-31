"""Sleeve allocation: compare weighting schemes and budgets, always out of sample.

Every scheme here beats equal weight in sample and loses to it out of sample, so the module exists to make that
visible rather than to produce weights to trade. Run it before changing an allocation, not after.

    python -m synthetix_alpha.strategy.allocate weights      # scheme comparison, walk-forward
    python -m synthetix_alpha.strategy.allocate budget       # gap fade budget sweep
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

ANN = 252


def sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(ANN)) if r.std() else float("nan")


def drawdown(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def weights(returns: pd.DataFrame, kind: str = "equal") -> np.ndarray:
    """Weighting schemes. `equal` is the default because it is the only one with no parameters to overfit."""
    mu, cov = returns.mean().values * ANN, returns.cov().values * ANN
    n = len(mu)
    if kind == "equal":
        return np.ones(n) / n
    if kind == "invvol":
        w = 1 / np.sqrt(np.diag(cov))
    elif kind == "minvar":
        w = np.linalg.pinv(cov) @ np.ones(n)
    elif kind in ("tangency", "tangency_long"):
        w = np.linalg.pinv(cov) @ mu
        if kind == "tangency_long":
            w = np.clip(w, 0, None)
    else:
        raise ValueError(f"unknown scheme {kind}")
    return w / w.sum() if w.sum() else np.ones(n) / n


def walk_forward(returns: pd.DataFrame, kind: str, start: int = 200, step: int = 60) -> pd.Series:
    """Fit weights on everything up to a point, trade the next `step` days, roll forward."""
    out = []
    for i in range(start, len(returns) - step, step):
        w = weights(returns.iloc[:i], kind)
        out.append(returns.iloc[i:i + step] @ w)
    return pd.concat(out) if out else pd.Series(dtype=float)


def sharpe_se(s: float, years: float) -> float:
    """Standard error of a Sharpe estimate (Lo 2002). Differences smaller than ~2 of these are not real."""
    return float(np.sqrt((1 + s ** 2 / 2) / years)) if years > 0 else float("nan")


def compare(returns: pd.DataFrame, start: int = 200, step: int = 60) -> pd.DataFrame:
    rows = []
    for kind in ("equal", "invvol", "minvar", "tangency_long", "tangency"):
        ins = returns @ weights(returns, kind)
        oos = walk_forward(returns, kind, start, step)
        if oos.empty:
            continue
        rows.append({"scheme": kind, "in_sample": sharpe(ins), "out_of_sample": sharpe(oos),
                     "oos_ann": float(oos.mean() * ANN), "oos_maxdd": drawdown(oos), "oos_days": len(oos)})
    df = pd.DataFrame(rows)
    if not df.empty:
        yrs = df["oos_days"].iloc[0] / ANN
        df.attrs["se"] = sharpe_se(df["out_of_sample"].max(), yrs)
        df.attrs["years"] = yrs
    return df


def budget_sweep(base: pd.Series, sleeve: pd.Series, budgets=(0.0, 0.4, 0.5, 0.6, 0.7, 1.0),
                 nav: float = 100_000.0) -> pd.DataFrame:
    """What a second sleeve does to the book at each deployment size. Sharpe is not scale invariant here
    because the base book is held fixed while only the sleeve is levered."""
    j = pd.concat({"base": base, "sleeve": sleeve}, axis=1).dropna()
    yrs = len(j) / ANN
    rows = []
    for b in budgets:
        p = j["base"] + b * j["sleeve"]
        eq = (1 + p).cumprod()
        rows.append({"budget": b, "pnl": float((eq.iloc[-1] - 1) * nav),
                     "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs else float("nan"),
                     "sharpe": sharpe(p), "maxdd": drawdown(p), "worst_day": float(p.min())})
    return pd.DataFrame(rows)


def _load():
    from synthetix_alpha.data.alpaca import AlpacaClient
    from synthetix_alpha.live import intraday
    from synthetix_alpha.strategy import EngineData
    from synthetix_alpha.strategy.engine import run
    from synthetix_alpha.strategy.spec import Spec

    def spec_returns(path):
        spec = Spec.load(path)
        legs = []
        for u in spec.underlyings:
            d = EngineData.load(u, dte_max=spec.dte_max + max(l.dte_offset for l in spec.legs) + 1)
            legs.append(run(spec, d, 100_000.0).equity.pct_change())
        r = pd.concat(legs, axis=1).mean(axis=1).dropna()
        r.index = pd.to_datetime(pd.Series(list(r.index)))
        return r

    cfg = json.load(open("strategies/portfolio.json"))
    sleeves = {p.split("/")[-1][:-5]: spec_returns(p) for p in cfg["sleeves"]}
    op, cl = intraday.panels(AlpacaClient(), days=1825)
    gf = ((cl / op - 1).where(intraday.zgap(op, cl).rank(axis=1, ascending=True) <= 20).mean(axis=1).dropna()
          - 0.0003)
    gf.index = pd.to_datetime(pd.Series(list(gf.index)))
    return pd.concat(sleeves, axis=1).dropna(), gf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["weights", "budget"])
    a = ap.parse_args()
    options, gapfade = _load()
    if a.mode == "weights":
        df = compare(options)
        print(df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        print(f"\nSharpe standard error over {df.attrs['years']:.2f}y of test data: {df.attrs['se']:.2f}")
        print("Differences smaller than about twice that are not distinguishable.")
    else:
        df = budget_sweep(options.mean(axis=1), gapfade)
        print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
