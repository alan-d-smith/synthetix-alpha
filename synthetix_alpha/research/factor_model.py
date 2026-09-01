"""Risk-adjust a strategy's daily returns against published factors.

A Sharpe ratio says a strategy made money; it does not say the money was not simply factor exposure. The gap
fade is a reversal strategy on long equity, so the two obvious deflationary explanations are market beta and
short-term reversal. Both are controlled for here, reversal being built on the strategy's own universe and
traded over the same open-to-close window so it is a fair comparison rather than a monthly proxy.

    python -m synthetix_alpha.research.factor_model returns.parquet --column hold
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from synthetix_alpha.data import wrds

FF5 = ["mktrf", "smb", "hml", "rmw", "cma", "umd"]


def factors(limit: int = 2500) -> pd.DataFrame:
    """Fama-French five factors plus momentum, daily, indexed by date."""
    df = wrds.get("ff.fivefactors_daily", ordering="-date", limit=limit)
    return df.set_index("date").sort_index().astype(float)


def reversal(op: pd.DataFrame, cl: pd.DataFrame, lookback: int, decile: float = 0.10) -> pd.Series:
    """Long the biggest losers over `lookback` days, short the winners, held open to close.

    Measured over the same window the strategy trades: a close-to-close factor would leave the overnight
    move uncontrolled, which is exactly the part the gap fade is exposed to.
    """
    day = cl / op - 1
    past = cl.shift(1) / cl.shift(1 + lookback) - 1
    r = past.rank(axis=1, pct=True)
    return (day.where(r <= decile).mean(axis=1)
            - day.where(r >= 1 - decile).mean(axis=1)).rename(f"str{lookback}")


def regress(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Coefficients, t-statistics and R-squared for an OLS fit with an intercept already in X."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X) * (e @ e) / (len(y) - X.shape[1])))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return beta, beta / se, float(r2)


def alpha(returns: pd.Series, controls: Optional[pd.DataFrame] = None,
          terms: Sequence[str] = FF5) -> dict:
    """Annualised alpha of a daily return series against the factor set, plus any extra controls."""
    ff = factors()
    frame = [returns.rename("r"), ff]
    if controls is not None:
        frame.append(controls)
    d = pd.concat(frame, axis=1).dropna()
    cols = list(terms) + ([c for c in controls.columns] if controls is not None else [])
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    beta, t, r2 = regress((d["r"] - d["rf"]).to_numpy(), X)
    return {"sessions": len(d), "start": d.index[0], "end": d.index[-1],
            "alpha_annual": float(beta[0] * 252), "alpha_t": float(t[0]), "r2": r2,
            "loadings": {c: (float(beta[i + 1]), float(t[i + 1])) for i, c in enumerate(cols)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("returns", help="parquet of daily strategy returns indexed by date")
    ap.add_argument("--column", default="hold")
    ap.add_argument("--reversal", action="store_true", help="add same-universe reversal controls")
    a = ap.parse_args()
    s = pd.read_parquet(a.returns)[a.column]
    s.index = pd.to_datetime(s.index).date
    controls = None
    if a.reversal:
        from synthetix_alpha.data.alpaca import AlpacaClient
        from synthetix_alpha.live.intraday import UNIVERSE
        end = dt.date.today()
        b = AlpacaClient().stock_bars(UNIVERSE, "1Day", end - dt.timedelta(days=1900), end).reset_index()
        b["date"] = pd.to_datetime(b["timestamp"]).dt.date
        op = b.pivot_table(index="date", columns="symbol", values="open")
        cl = b.pivot_table(index="date", columns="symbol", values="close")
        controls = pd.concat([reversal(op, cl, 1), reversal(op, cl, 21)], axis=1)
    r = alpha(s, controls)
    print(f"{r['sessions']} sessions, {r['start']} to {r['end']}")
    print(f"alpha {r['alpha_annual']*100:.2f}% annualised, t={r['alpha_t']:.2f}, R2={r['r2']:.3f}")
    for k, (b_, t_) in r["loadings"].items():
        print(f"  {k:<8}{b_:+.3f}  t={t_:+.2f}")


if __name__ == "__main__":
    main()
