"""kylegraupe's Kaggle EOD option-chain datasets (one wide row per date/expiry/strike) in the canonical layouts."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from synthetix_alpha.data.schema import BAR_COLUMNS, CHAIN_COLUMNS, GREEKS

DATASETS = {
    "AAPL": "kylegraupe/aapl-options-data-2016-2020",  # 2016-01 → 2023-03
    "NVDA": "kylegraupe/nvda-daily-option-chains-q1-2020-to-q4-2022",  # 2020-01 → 2022-12
    "QQQ": "kylegraupe/qqq-daily-option-chains-q1-2020-to-q4-2022",  # 2021-01 → 2022-12
    "SPY": "kylegraupe/spy-daily-eod-options-quotes-2020-2022",  # 2020-01 → 2022-12
    "TSLA": "kylegraupe/tsla-daily-eod-options-quotes-2019-2022",  # 2019-01 → 2022-12
}
_SIDE = {"bid": "BID", "ask": "ASK", "last": "LAST", "iv": "IV", "volume": "VOLUME", **{g: g.upper() for g in GREEKS}}
CHUNK_ROWS = 1_000_000


def download(underlying: str) -> Path:
    import kagglehub

    return Path(kagglehub.dataset_download(DATASETS[underlying.upper()]))


def load_chains(underlying: str, path: Union[str, Path, None] = None, cache: bool = True) -> pd.DataFrame:
    """Daily chains indexed by (date, symbol) with CHAIN_COLUMNS + underlying_price; `.loc[date]` is one chain snapshot."""
    underlying = underlying.upper()
    path = Path(path) if path else download(underlying)
    csvs, folder = (sorted(path.glob("*.csv")), path) if path.is_dir() else ([path], path.parent)
    parquet = folder / f"{underlying.lower()}_chains.parquet"
    if cache and parquet.exists():
        return pd.read_parquet(parquet)
    chunks = (to_chains(chunk, underlying) for csv in csvs for chunk in pd.read_csv(csv, chunksize=CHUNK_ROWS, low_memory=False))
    chains = pd.concat(chunks)
    chains = chains[~chains.index.duplicated(keep="last")].sort_index()
    if cache:
        chains.to_parquet(parquet)
    return chains


def to_chains(raw: pd.DataFrame, underlying: str) -> pd.DataFrame:
    raw = raw.rename(columns=lambda c: c.strip().strip("[]"))
    quote_time = pd.to_datetime(raw["QUOTE_READTIME"].str.strip()).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    expiration = pd.to_datetime(raw["EXPIRE_DATE"].str.strip())
    strike = raw["STRIKE"].astype(float)
    base = {"date": quote_time.dt.tz_convert("America/New_York").dt.date, "underlying": underlying,
            "expiration": expiration.dt.date, "strike": strike, "quote_time": quote_time, "trade_time": quote_time,
            "underlying_price": raw["UNDERLYING_LAST"].astype(float)}
    sides = []
    for option_type, p in (("call", "C"), ("put", "P")):
        s = pd.DataFrame({**base, "type": option_type})
        for col, src in _SIDE.items():
            s[col] = pd.to_numeric(raw[f"{p}_{src}"], errors="coerce")
        size = raw[f"{p}_SIZE"].astype(str).str.split(" x ", expand=True, n=1)
        s["bid_size"], s["ask_size"] = pd.to_numeric(size[0], errors="coerce"), pd.to_numeric(size[1], errors="coerce")
        s["symbol"] = underlying + expiration.dt.strftime("%y%m%d") + p + (strike * 1000).round().astype(int).astype(str).str.zfill(8)
        sides.append(s)
    df = pd.concat(sides, ignore_index=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df.set_index(["date", "symbol"])[[*CHAIN_COLUMNS, "underlying_price"]]


def underlying_bars(chains: pd.DataFrame) -> pd.DataFrame:
    df = chains.reset_index().groupby("date", sort=True).agg(
        timestamp=("quote_time", "first"), symbol=("underlying", "first"), close=("underlying_price", "first"))
    return df.reindex(columns=["timestamp", *BAR_COLUMNS]).set_index("timestamp")
