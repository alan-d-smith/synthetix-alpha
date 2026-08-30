"""Daily scan for underlyings whose implied vol is rich vs realised, filtered by config/universe.yaml."""

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
    """In-regime names ranked by IV rank. iv_rv_max caps event-driven outliers (earnings, M&A)."""
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
        ORDER BY iv_current/hv_current DESC LIMIT {max(limit * 4, 600)}""")
    if df.empty:
        return df
    df["symbol"] = df["symbol"].str.upper()
    if allow:
        df = df[df["symbol"].isin(allow)]
    df = df[~df["symbol"].isin(deny)]
    return df.set_index("symbol").sort_values("iv_rank", ascending=False).head(limit)


def liquidity(symbols: list[str], u: Optional[dict] = None, days: int = 20, client=None) -> pd.DataFrame:
    """Average dollar volume and last price, with universe.yaml floors applied."""
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


def days_to_earnings(symbols: list[str], asof: Optional[dt.date] = None) -> pd.Series:
    """Days to each name's next announcement. NaN when unknown, which the caller treats as disqualifying."""
    from synthetix_alpha.data import yf

    day = [asof or dt.date.today()]
    out = {}
    for sym in symbols:
        try:
            out[sym] = float(yf.days_to_earnings(sym, day).iloc[0])
        except Exception:
            out[sym] = float("nan")
    return pd.Series(out, name="days_to_earnings")


def candidates(iv_rv_min: float = 1.25, limit: int = 15, client=None, min_days_to_earnings: float = 30.0,
               asof: Optional[dt.date] = None) -> pd.DataFrame:
    """In-regime names that clear the liquidity floors and are clear of earnings.

    IV is often rich precisely because an announcement is near, which is the one setup the backtest says to avoid.
    """
    s = scan(iv_rv_min=iv_rv_min, limit=limit * 3, asof=asof)
    if s.empty:
        return s
    liq = liquidity(list(s.index), client=client)
    out = s.join(liq, how="inner")
    out = out[out["liquid"]].drop(columns="liquid")
    if out.empty:
        return out
    out = out.join(days_to_earnings(list(out.index), asof))
    return out[out["days_to_earnings"] >= min_days_to_earnings].head(limit)


def main() -> None:
    df = candidates()
    print(df.round(3).to_string() if len(df) else "no candidates in regime today")


if __name__ == "__main__":
    main()
