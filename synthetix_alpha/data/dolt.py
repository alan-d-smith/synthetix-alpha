"""DoltHub `post-no-preference/options` (local clone): EOD option surfaces for ~1,500 US names, 2019-02 → present.

Coverage is a coarse surface, not a full chain: snapshots roughly every other day, ~3 expirations x ~20 strikes per
name with bid/ask/IV/greeks (no spot, volume or OI). Good for skew/term-structure/IV-rank signals across many names;
single-contract price paths are patchy. `volatility_history` adds daily HV/IV summaries per name.
"""

from __future__ import annotations

import datetime as dt
import io
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

from synthetix_alpha import config
from synthetix_alpha.data.schema import CHAIN_COLUMNS, GREEKS

DateLike = dt.date


def query(sql: str, db: Optional[Path] = None) -> pd.DataFrame:
    out = subprocess.run([config.DOLT_BIN, "sql", "-r", "csv", "-q", sql], cwd=db or config.DOLT_OPTIONS_DB,
                         capture_output=True, text=True, check=True)
    return pd.read_csv(io.StringIO(out.stdout))


def head(db: Optional[Path] = None) -> str:
    return str(query("SELECT HASHOF('HEAD') AS h", db).iloc[0, 0])


def to_chains(raw: pd.DataFrame) -> pd.DataFrame:
    """option_chain rows -> (date, symbol) x CHAIN_COLUMNS (bid_size/ask_size/last/volume are absent: NaN)."""
    if raw.empty:
        return pd.DataFrame(columns=CHAIN_COLUMNS, index=pd.MultiIndex.from_arrays([[], []], names=["date", "symbol"]))
    quote_time = pd.to_datetime(raw["date"]).dt.tz_localize("America/New_York") + pd.Timedelta(hours=16)
    expiration = pd.to_datetime(raw["expiration"])
    root, strike = raw["act_symbol"].str.replace(".", "", regex=False), raw["strike"].astype(float)
    cp = raw["call_put"].str[0].str.upper()
    df = pd.DataFrame({
        "date": quote_time.dt.date, "underlying": raw["act_symbol"], "expiration": expiration.dt.date,
        "type": cp.map({"C": "call", "P": "put"}), "strike": strike, "bid": raw["bid"], "ask": raw["ask"],
        "quote_time": quote_time.dt.tz_convert("UTC"), "iv": raw["vol"], **{g: raw[g] for g in GREEKS},
        "symbol": root.astype(str) + expiration.dt.strftime("%y%m%d").astype(str) + cp.astype(str) + (strike * 1000).round().astype(int).astype(str).str.zfill(8),
    })
    df["mid"], df["trade_time"] = (df["bid"] + df["ask"]) / 2, df["quote_time"]
    return df.set_index(["date", "symbol"]).reindex(columns=CHAIN_COLUMNS)


def to_volatility(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns={"act_symbol": "symbol"})
    for c in [c for c in df.columns if c == "date" or c.endswith("_date")]:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df.assign(underlying=df["symbol"]).set_index(["date", "symbol"])


def load_chains(symbols: Iterable[str], start: DateLike, end: DateLike, db: Optional[Path] = None) -> pd.DataFrame:
    return _load("option_chain", to_chains, symbols, start, end, db)


def load_volatility(symbols: Iterable[str], start: DateLike, end: DateLike, db: Optional[Path] = None) -> pd.DataFrame:
    return _load("volatility_history", to_volatility, symbols, start, end, db)


def _load(table: str, convert: Callable, symbols: Iterable[str], start: DateLike, end: DateLike, db: Optional[Path]) -> pd.DataFrame:
    """Per (symbol, year) parquet cache under datasets/cache/dolt/<HEAD>/<table>; one query per year for what's missing."""
    symbols = sorted({s.upper() for s in symbols})
    cache = config.DOLT_CACHE / head(db) / table
    cache.mkdir(parents=True, exist_ok=True)
    frames, missing = [], defaultdict(list)
    for s in symbols:
        for y in range(start.year, end.year + 1):
            f = cache / f"{s}_{y}.parquet"
            frames.append(pd.read_parquet(f)) if f.exists() else missing[y].append(s)
    for y, syms in missing.items():
        quoted = ",".join(f"'{s}'" for s in syms)
        df = convert(query(f"SELECT * FROM {table} WHERE date BETWEEN '{y}-01-01' AND '{y}-12-31' AND act_symbol IN ({quoted})", db))
        for s in syms:
            part = df[df["underlying"] == s]
            part.to_parquet(cache / f"{s}_{y}.parquet")
            frames.append(part)
    out = pd.concat(frames).sort_index()
    dates = out.index.get_level_values("date")
    return out[(dates >= start) & (dates <= end)]


DOLTHUB_API = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"


def query_remote(sql: str, timeout: int = 90, url: str = DOLTHUB_API) -> pd.DataFrame:
    """Run the same SQL against DoltHub over HTTP, for hosts without the 8GB clone.

    Values arrive as strings, so numeric columns are coerced. Slower than the local clone, roughly 20 seconds,
    which is fine for a once-a-day screen but not for anything in a loop.
    """
    import httpx

    r = httpx.get(url, params={"q": sql}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if body.get("query_execution_status") != "Success":
        raise RuntimeError(f"dolthub: {body.get('query_execution_message', 'query failed')}")
    df = pd.DataFrame(body.get("rows") or [])
    for c in df.columns:
        if c not in ("symbol", "act_symbol", "date"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
