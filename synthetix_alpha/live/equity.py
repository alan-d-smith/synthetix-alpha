"""Equity sleeve, run in parallel with the options sleeves.

Cross-sectional momentum (Jegadeesh & Titman 1993): long the strongest names over 12 months skipping the last,
equal weight, long only. Deterministic and independent of the options gate, so it trades when the vol gate does not.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from synthetix_alpha.live import cli, screen


def momentum(symbols: list[str], client, lookback: int = 252, skip: int = 21) -> pd.Series:
    """12-1 total return per symbol, highest first. Names without enough history are dropped."""
    end = dt.date.today()
    bars = client.stock_bars(symbols, "1Day", end - dt.timedelta(days=int(lookback * 1.6)), end)
    if bars.empty:
        return pd.Series(dtype=float)
    out = {}
    for sym, g in bars.groupby("symbol"):
        close = g["close"].dropna()
        if len(close) < lookback * 0.8:
            continue
        window = close.iloc[-lookback:-skip] if skip else close.iloc[-lookback:]
        if len(window) > 1 and window.iloc[0] > 0:
            out[sym] = float(window.iloc[-1] / window.iloc[0] - 1)
    return pd.Series(out, name="momentum").sort_values(ascending=False)


def plan(nav: float, client, top_n: int = 10, budget_pct: float = 0.20,
         universe: Optional[list[str]] = None) -> list[dict]:
    """Equal-weight buys across the strongest names, capped at budget_pct of NAV in total."""
    names = universe or list(screen.scan(iv_rv_min=0.0, iv_rv_max=99.0, limit=300).index)
    if not names:
        return []
    liq = screen.liquidity(names, client=client)
    names = list(liq[liq["liquid"]].index) if not liq.empty else names
    ranked = momentum(names, client)
    if ranked.empty:
        return []
    picks, per_name = list(ranked.head(top_n).index), nav * budget_pct / max(top_n, 1)
    prices = screen.liquidity(picks, client=client)["price"]
    orders = []
    for sym in picks:
        px = float(prices.get(sym, 0) or 0)
        qty = int(per_name // px) if px > 0 else 0
        if qty >= 1:
            orders.append({"symbol": sym, "qty": qty, "price": round(px, 2),
                           "notional": round(qty * px, 2), "momentum": round(float(ranked[sym]), 4)})
    return orders


def submit_all(orders: list[dict], *, dry_run: bool = True) -> list[dict]:
    out = []
    for o in orders:
        res = cli.submit_equity(o["symbol"], o["qty"], "buy", dry_run=dry_run)
        out.append({**o, "status": res.get("status", "dry_run"), "order_id": res.get("id")})
    return out
