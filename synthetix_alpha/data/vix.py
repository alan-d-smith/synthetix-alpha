"""CBOE volatility indices from FRED (VIXCLS, VXNCLS): the market's own 30-day IV, with decades of history."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from synthetix_alpha import config

FILES = {"VIX": "VIXCLS.csv", "VXN": "VXNCLS.csv"}
INDEX_FOR = {"SPY": "VIX", "QQQ": "VXN"}  # only these two have an index that measures the same asset
DIR = config.ROOT / "datasets"


def load(index: str = "VIX", directory: Optional[Path] = None) -> pd.Series:
    """Daily close as a decimal (0.18 = 18 vol), indexed by date."""
    path = Path(directory or DIR) / FILES[index.upper()]
    df = pd.read_csv(path, parse_dates=["observation_date"])
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce") / 100.0
    s.index = df["observation_date"].dt.date
    return s.dropna().rename(index.upper())


def for_underlying(underlying: str, directory: Optional[Path] = None) -> tuple[pd.Series, bool]:
    """Returns (series, matched). VIX is the market regime for any name, but only a like-for-like IV for SPY/QQQ."""
    index = INDEX_FOR.get(underlying.upper())
    return load(index or "VIX", directory), index is not None
