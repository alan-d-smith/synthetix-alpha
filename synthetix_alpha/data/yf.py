"""Earnings dates and split history from yfinance, cached as parquet under datasets/cache/yf."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd

from synthetix_alpha import config

CACHE = config.ROOT / "datasets" / "cache" / "yf"
MAX_EARNINGS = 100  # Yahoo rejects anything higher


def _cached(symbol: str, kind: str, fetch) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol.upper()}_{kind}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = fetch()
    df.to_parquet(path, compression="zstd", index=False)
    return df


def earnings_dates(symbol: str, refresh: bool = False) -> pd.Series:
    """Announcement dates, ascending. Empty if yfinance has none for the symbol."""
    path = CACHE / f"{symbol.upper()}_earnings.parquet"
    if refresh and path.exists():
        path.unlink()

    def fetch() -> pd.DataFrame:
        import yfinance as yf
        try:
            e = yf.Ticker(symbol).get_earnings_dates(limit=MAX_EARNINGS)
        except Exception:
            e = None
        dates = [] if e is None or e.empty else sorted({i.date() for i in e.index})
        return pd.DataFrame({"date": dates})

    return pd.to_datetime(_cached(symbol, "earnings", fetch)["date"]).dt.date.sort_values().reset_index(drop=True)


def splits(symbol: str, refresh: bool = False) -> pd.Series:
    """Split ratios indexed by effective date, e.g. 4.0 for a 4:1 split."""
    path = CACHE / f"{symbol.upper()}_splits.parquet"
    if refresh and path.exists():
        path.unlink()

    def fetch() -> pd.DataFrame:
        import yfinance as yf
        try:
            s = yf.Ticker(symbol).splits
        except Exception:
            s = None
        if s is None or len(s) == 0:
            return pd.DataFrame({"date": [], "ratio": []})
        return pd.DataFrame({"date": [i.date() for i in s.index], "ratio": s.to_numpy(dtype=float)})

    df = _cached(symbol, "splits", fetch)
    if df.empty:
        return pd.Series(dtype=float, name="ratio")
    return pd.Series(df["ratio"].to_numpy(), index=pd.to_datetime(df["date"]).dt.date, name="ratio")


def days_to_earnings(symbol: str, dates, horizon: int = 400) -> pd.Series:
    """Calendar days from each date to the next announcement. NaN when no future date is known."""
    known = list(earnings_dates(symbol))
    if not known:
        return pd.Series(float("nan"), index=dates, name="days_to_earnings")
    ann = pd.Series(known)
    out = []
    for d in dates:
        nxt = ann[ann >= d]
        gap = (nxt.iloc[0] - d).days if len(nxt) else None
        out.append(float(gap) if gap is not None and gap <= horizon else float("nan"))
    return pd.Series(out, index=dates, name="days_to_earnings")


def spans_split(symbol: str, start: dt.date, end: dt.date) -> Optional[dt.date]:
    """First split date inside the window, or None. Kaggle single-name chains are not split adjusted."""
    s = splits(symbol)
    inside = [d for d in s.index if start <= d <= end]
    return inside[0] if inside else None
