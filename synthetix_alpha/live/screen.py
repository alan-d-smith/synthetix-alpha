"""Daily universe scan: which names are in the rich-IV regime the strategy needs.

The deployed gate fires on ~25% of days for any one underlying, so trading a single index can mean no trades
at all in a short window. This scans DoltHub's `volatility_history` (~1,500 names) for the same IV-vs-realised
condition and applies the liquidity floors in config/universe.yaml.

Extreme IV/RV usually prices a scheduled event (earnings, M&A, FDA) — selling that premium is the classic trap —
so `iv_rv_max` caps the ratio rather than sorting by it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from synthetix_alpha import config
from synthetix_alpha.data import dolt

UNIVERSE = config.ROOT / "config" / "universe.yaml"


def rules(path: Optional[Path] = None) -> dict:
    raw = yaml.safe_load(Path(path or UNIVERSE).read_text()) or {}
    return raw.get("universe", raw)


def scan(iv_rv_min: float = 1.25, iv_rv_max: float = 2.0, limit: int = 40, asof: Optional[dt.date] = None,
         universe: Optional[dict] = None) -> pd.DataFrame:
    """Names whose implied vol is rich vs realised, ranked by IV rank. Returns symbol-indexed frame."""
    u = universe or rules()
    allow = {s.upper() for s in (u.get("ticker_allowlist") or [])}
    deny = {s.upper() for s in (u.get("ticker_denylist") or [])}
    date = f"'{asof.isoformat()}'" if asof else "(SELECT MAX(date) FROM volatility_history)"
    df = dolt.query(f"""
        SELECT act_symbol AS symbol, date, iv_current AS iv, hv_current AS hv,
               iv_current/hv_current AS iv_rv,
               (iv_current-iv_year_low)/NULLIF(iv_year_high-iv_year_low,0) AS iv_rank
        FROM volatility_history
        WHERE date = {date} AND hv_current > 0.05
          AND iv_current/hv_current BETWEEN {iv_rv_min} AND {iv_rv_max}
        ORDER BY iv_current/hv_current DESC LIMIT {max(limit * 4, 200)}""")
    if df.empty:
        return df
    df["symbol"] = df["symbol"].str.upper()
    if allow:
        df = df[df["symbol"].isin(allow)]
    df = df[~df["symbol"].isin(deny)]
    return df.set_index("symbol").sort_values("iv_rank", ascending=False).head(limit)


def liquidity(symbols: list[str], u: Optional[dict] = None, days: int = 20, client=None) -> pd.DataFrame:
    """Average dollar volume and last price over `days` sessions, with the universe.yaml floors applied."""
    from synthetix_alpha.data.alpaca import AlpacaClient

    u = u or rules()
    end = dt.date.today()
    bars = (client or AlpacaClient()).stock_bars(symbols, "1Day", end - dt.timedelta(days=days * 2), end)
    if bars.empty:
        return pd.DataFrame(columns=["price", "avg_dollar_volume", "liquid"])
    g = bars.groupby("symbol").tail(days).groupby("symbol")
    out = pd.DataFrame({"price": g["close"].last(), "avg_dollar_volume": (bars["close"] * bars["volume"]).groupby(bars["symbol"]).mean()})
    out["liquid"] = (out["price"] >= u.get("min_price", 5.0)) & (out["avg_dollar_volume"] >= u.get("avg_dollar_volume_floor", 5e7))
    return out


def candidates(iv_rv_min: float = 1.25, limit: int = 15, client=None) -> pd.DataFrame:
    """Tradable shortlist: in-regime names that also clear the liquidity floors."""
    s = scan(iv_rv_min=iv_rv_min, limit=limit * 3)
    if s.empty:
        return s
    liq = liquidity(list(s.index), client=client)
    out = s.join(liq, how="inner")
    return out[out["liquid"]].drop(columns="liquid").head(limit)


def main() -> None:
    df = candidates()
    print(df.round(3).to_string() if len(df) else "no candidates in regime today")


if __name__ == "__main__":
    main()
