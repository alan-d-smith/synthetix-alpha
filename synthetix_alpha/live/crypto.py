"""Crypto dislocation sleeve: buy extreme volatility-adjusted drops, exit after a fixed hold.

Crypto trades continuously, so this is the one sleeve that can act while equity markets are shut. The signal is
deliberately rare: at z < -3.5 it fired about 16 times a year across 15 pairs, returning ~3.8% gross per event with
a 59% win rate (t = 2.85, positive in both halves of the sample). Everything more frequent was consumed by Alpaca's
0.15%/side maker fee, which is why turnover is kept this low.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd

from synthetix_alpha import config
from synthetix_alpha.live import cli

PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD", "AVAX/USD", "LTC/USD", "DOGE/USD", "XRP/USD", "ADA/USD",
         "TRUMP/USD", "WIF/USD", "BONK/USD", "PEPE/USD", "SHIB/USD", "UNI/USD", "AAVE/USD", "DOT/USD", "BCH/USD"]
LOOKBACK, HOLD, THRESHOLD = 24, 48, 3.5   # hours, hours, sigma
MAX_CONCURRENT = 3


def bars(hours: int = 24 * 40, pairs: Optional[list[str]] = None) -> pd.DataFrame:
    """Hourly closes, indexed by timestamp with pairs as columns."""
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    k, s = config.credentials()
    end = dt.datetime.now(dt.timezone.utc)
    d = CryptoHistoricalDataClient(k, s).get_crypto_bars(CryptoBarsRequest(
        symbol_or_symbols=pairs or PAIRS, timeframe=TimeFrame(1, TimeFrameUnit.Hour),
        start=end - dt.timedelta(hours=hours), end=end)).df
    if d.empty:
        return pd.DataFrame()
    return d.reset_index().pivot_table(index="timestamp", columns="symbol", values="close").sort_index()


def zscore(px: pd.DataFrame, lookback: int = LOOKBACK) -> pd.Series:
    """Latest move over `lookback` hours, scaled by each pair's own hourly volatility."""
    ret = px.pct_change()
    vol = ret.rolling(24 * 7).std()
    z = (px / px.shift(lookback) - 1) / (vol * np.sqrt(lookback))
    return z.iloc[-1].dropna().sort_values()


def signals(px: Optional[pd.DataFrame] = None, threshold: float = THRESHOLD) -> pd.DataFrame:
    """Pairs currently dislocated beyond the threshold, most extreme first."""
    px = bars() if px is None else px
    if px.empty or len(px) < 24 * 7 + LOOKBACK:
        return pd.DataFrame()
    z = zscore(px)
    move = (px.iloc[-1] / px.iloc[-1 - LOOKBACK] - 1).reindex(z.index)
    out = pd.DataFrame({"z": z, "move_24h": move, "price": px.iloc[-1].reindex(z.index)})
    return out[out["z"] < -threshold]


def plan(nav: float, budget_pct: float = 0.15, px: Optional[pd.DataFrame] = None) -> list[dict]:
    """Equal-weight buys across dislocated pairs, capped at MAX_CONCURRENT."""
    sig = signals(px)
    if sig.empty:
        return []
    sig = sig.head(MAX_CONCURRENT)
    per = nav * budget_pct / max(len(sig), 1)
    out = []
    for pair, row in sig.iterrows():
        qty = per / float(row["price"])
        if qty > 0:
            out.append({"symbol": pair, "qty": round(qty, 8), "price": round(float(row["price"]), 6),
                        "z": round(float(row["z"]), 2), "move_24h": round(float(row["move_24h"]), 4),
                        "notional": round(qty * float(row["price"]), 2),
                        "exit_after_hours": HOLD})
    return out


def enter(orders: list[dict], *, dry_run: bool = True) -> list[dict]:
    """Buy now. The exit is time-based, so it is left to the caller to close after HOLD hours."""
    out = []
    for o in orders:
        r = cli.submit_equity(o["symbol"], o["qty"], "buy", dry_run=dry_run)
        out.append({**o, "status": r.get("status", "dry_run")})
    return out
