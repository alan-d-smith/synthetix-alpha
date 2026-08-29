"""Per-underlying chain slices, spot and trailing features (no lookahead), cached as parquet. Source: kaggle | dolt."""

from __future__ import annotations

import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd
from gs_quant.timeseries.technicals import bollinger_bands, macd, relative_strength_index

from synthetix_alpha import config
from synthetix_alpha.data import kaggle

COLS = ["expiration", "type", "strike", "bid", "ask", "mid", "iv", "delta", "underlying_price"]
CACHE = config.ROOT / "datasets" / "cache" / "engine"
DOLT_START = dt.date(2019, 2, 9)


def build(underlying: str, source: str = "kaggle") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compact chain frame (date index) and daily feature frame."""
    chains, spot = (kaggle.load_chains(underlying), None) if source == "kaggle" else _dolt_chains(underlying)
    df = chains[COLS].reset_index()
    if df.empty:
        raise ValueError(f"no {source} chains for {underlying}")
    df["dte"] = (pd.to_datetime(df["expiration"]) - pd.to_datetime(df["date"])).dt.days.astype("int16")
    df = df[df["dte"] > 0]
    for c in ("strike", "bid", "ask", "mid", "iv", "delta", "underlying_price"):
        df[c] = df[c].astype("float32")
    df["type"] = df["type"].astype("category")
    return df.set_index("date"), features(df, spot)


def _dolt_chains(underlying: str) -> pd.DataFrame:
    from synthetix_alpha.data import dolt
    from synthetix_alpha.data.alpaca import AlpacaClient

    end = dt.date.today()
    chains = dolt.load_chains([underlying], DOLT_START, end)
    spot = AlpacaClient().stock_bars(underlying, "1Day", DOLT_START, end)["close"]
    spot.index = spot.index.tz_convert("America/New_York").date
    return chains.join(spot.rename("underlying_price"), on="date").dropna(subset=["underlying_price"]), spot


def features(df: pd.DataFrame, spot: Optional[pd.Series] = None) -> pd.DataFrame:
    """Spot-based features on the daily spot series; IV-surface features on chain dates, forward-filled onto it."""
    rows = {}
    for date, d in df.groupby("date", sort=True):
        s = float(d["underlying_price"].iloc[0])
        rows[date] = {**_surface(d, s, 30, "atm_iv", "skew25"), **_surface(d, s, 90, "far_iv", None)}
    surface = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    if spot is None:
        spot = df.groupby("date")["underlying_price"].first()
    idx = sorted(set(spot.index) | set(surface.index))
    f = pd.DataFrame({"spot": spot.reindex(idx).ffill()}, index=idx).join(surface.reindex(idx).ffill())
    ret = f["spot"].pct_change()
    f["rv20"] = ret.rolling(20).std() * np.sqrt(252)
    f["mom20"] = f["spot"].pct_change(20)
    f["sma50_ratio"] = f["spot"] / f["spot"].rolling(50).mean() - 1
    f["sma200_ratio"] = f["spot"] / f["spot"].rolling(200).mean() - 1
    f["iv_rank"] = f["atm_iv"].rolling(252, min_periods=60).rank(pct=True)
    f["iv_rv_ratio"] = f["atm_iv"] / f["rv20"]
    f["term_slope"] = f["far_iv"] - f["atm_iv"]
    return f.drop(columns="far_iv").join(technicals(f["spot"]))


def technicals(spot: pd.Series) -> pd.DataFrame:
    """RSI, Bollinger position and MACD from gs-quant, all trailing."""
    bands = bollinger_bands(spot, 20, 2)
    low, high = bands.iloc[:, 0], bands.iloc[:, 1]
    return pd.DataFrame({
        "rsi": relative_strength_index(spot, 14).squeeze(),
        "bollinger_pos": (spot - low) / (high - low).replace(0, np.nan),
        "macd": macd(spot) / spot,
    })


def _surface(d: pd.DataFrame, spot: float, dte: int, iv_name: str, skew_name: Optional[str]) -> dict:
    out = {iv_name: np.nan, **({skew_name: np.nan} if skew_name else {})}
    near = d[d["dte"].between(dte - (15 if dte <= 30 else 30), dte + (20 if dte <= 30 else 30)) & d["iv"].notna()]
    if near.empty:
        return out
    e = near[near["expiration"] == near.iloc[(near["dte"] - dte).abs().argmin()]["expiration"]]
    atm = e.iloc[(e["strike"] - spot).abs().argsort()[:2]]
    out[iv_name] = float(atm["iv"].mean())
    if skew_name:
        puts, calls = e[e["type"] == "put"], e[e["type"] == "call"]
        if len(puts) and len(calls):
            p = puts.iloc[(puts["delta"].abs() - 0.25).abs().argmin()]
            c = calls.iloc[(calls["delta"].abs() - 0.25).abs().argmin()]
            out[skew_name] = float(p["iv"] - c["iv"])
    return out


class EngineData:
    def __init__(self, underlying: str, chains: pd.DataFrame, feats: pd.DataFrame):
        self.underlying, self.features = underlying, feats
        self._by_date = {d: g.set_index("symbol") for d, g in chains.groupby(level=0, sort=True)}
        self.dates = sorted(self._by_date)

    @classmethod
    def load(cls, underlying: str, dte_max: int = 120, start: Optional[dt.date] = None, end: Optional[dt.date] = None,
             source: str = "kaggle") -> "EngineData":
        underlying = underlying.upper()
        CACHE.mkdir(parents=True, exist_ok=True)
        stem = underlying if source == "kaggle" else f"{underlying}_{source}"
        chains_pq, feats_pq = CACHE / f"{stem}.parquet", CACHE / f"{stem}_features.parquet"
        if chains_pq.exists() and feats_pq.exists():
            chains, feats = pd.read_parquet(chains_pq), pd.read_parquet(feats_pq)
        else:
            chains, feats = build(underlying, source)
            chains.to_parquet(chains_pq)
            feats.to_parquet(feats_pq)
        chains = chains[chains["dte"] <= dte_max]
        if start:
            chains = chains[chains.index >= start]
        if end:
            chains = chains[chains.index <= end]
        return cls(underlying, chains, feats)

    def chain(self, date: dt.date) -> Optional[pd.DataFrame]:
        return self._by_date.get(date)
