"""Alpaca market data via alpaca-py: option contracts, option/stock bars, option chain snapshots (greeks/IV)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, Optional, Union

import pandas as pd
from alpaca.common.exceptions import APIError as AlpacaAPIError  # noqa: F401  (re-exported)
from alpaca.data.enums import OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest, OptionChainRequest, OptionSnapshotRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest

from synthetix_alpha import config
from synthetix_alpha.data.occ import parse_occ_symbol
from synthetix_alpha.data.schema import BAR_COLUMNS, CHAIN_COLUMNS, GREEKS

DateLike = Union[dt.date, dt.datetime, str, None]
BAR_FIELDS = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trade_count", "vw": "vwap"}
CONTRACT_COLUMNS = ["symbol", "name", "status", "tradable", "expiration_date", "underlying_symbol", "type", "style",
                    "strike_price", "size", "root_symbol", "close_price", "close_price_date", "open_interest"]
_UNITS = {"min": TimeFrameUnit.Minute, "t": TimeFrameUnit.Minute, "hour": TimeFrameUnit.Hour, "h": TimeFrameUnit.Hour,
          "day": TimeFrameUnit.Day, "d": TimeFrameUnit.Day, "week": TimeFrameUnit.Week, "w": TimeFrameUnit.Week,
          "month": TimeFrameUnit.Month, "m": TimeFrameUnit.Month}
BATCH = 100


def timeframe(tf: str) -> TimeFrame:
    m = re.fullmatch(r"(\d+)([A-Za-z]+)", tf.strip())
    if not m or m[2].lower() not in _UNITS:
        raise ValueError(f"bad timeframe {tf!r}")
    return TimeFrame(int(m[1]), _UNITS[m[2].lower()])


def _dt(v: DateLike) -> Optional[dt.datetime]:
    if v is None:
        return None
    if isinstance(v, str):
        v = dt.datetime.fromisoformat(v)
    if not isinstance(v, dt.datetime):
        v = dt.datetime.combine(v, dt.time.min)
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


def _end(v: DateLike) -> Optional[dt.datetime]:
    """A date (or date string) as `end` means the whole day: exclusive end = next midnight."""
    e = _dt(v)
    whole_day = isinstance(v, str) and len(v) == 10 or (isinstance(v, dt.date) and not isinstance(v, dt.datetime))
    return e + dt.timedelta(days=1) if e is not None and whole_day else e


def _clamp_end(end: DateLike) -> dt.datetime:  # free plan: the last 15 min of SIP/OPRA data is gated
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=16)
    e = _end(end)
    return cutoff if e is None or e > cutoff else e


def _symbols(s: Union[str, Iterable[str]]) -> list[str]:
    return [x.strip() for x in s.split(",")] if isinstance(s, str) else [str(x) for x in s]


def bars_to_frame(raw: dict) -> pd.DataFrame:
    rows = [{"timestamp": b["t"], "symbol": sym, **{n: b.get(k) for k, n in BAR_FIELDS.items()}}
            for sym, bars in (raw or {}).items() for b in bars or []]
    df = pd.DataFrame(rows, columns=["timestamp", *BAR_COLUMNS])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values(["symbol", "timestamp"]).set_index("timestamp")


def snapshots_to_frame(raw: dict) -> pd.DataFrame:
    rows = []
    for sym, s in (raw or {}).items():
        q, t, g = s.get("latestQuote") or {}, s.get("latestTrade") or {}, s.get("greeks") or {}
        occ = parse_occ_symbol(sym)
        rows.append({"symbol": sym, "underlying": occ.underlying, "expiration": occ.expiration, "type": occ.option_type,
                     "strike": occ.strike, "bid": q.get("bp"), "ask": q.get("ap"), "bid_size": q.get("bs"),
                     "ask_size": q.get("as"), "quote_time": q.get("t"), "last": t.get("p"), "trade_time": t.get("t"),
                     "iv": s.get("impliedVolatility"), **{k: g.get(k) for k in GREEKS},
                     "volume": (s.get("dailyBar") or {}).get("v")})
    df = pd.DataFrame(rows, columns=["symbol", *CHAIN_COLUMNS]).set_index("symbol")
    df["mid"] = (pd.to_numeric(df["bid"]) + pd.to_numeric(df["ask"])) / 2
    for c in ("quote_time", "trade_time"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df.sort_values(["expiration", "strike", "type"])


def contracts_to_frame(contracts: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(contracts, columns=CONTRACT_COLUMNS if not contracts else None)
    for c in ("strike_price", "close_price", "open_interest"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).dt.date
    return df.set_index("symbol").sort_values(["expiration_date", "strike_price", "type"])[CONTRACT_COLUMNS[1:]]


class AlpacaClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, *, paper: bool = config.PAPER,
                 feed: str = config.OPTIONS_FEED, options=None, stocks=None, trading=None):
        if api_key is None and not (options and stocks and trading):
            api_key, api_secret = config.credentials()
        self.feed = OptionsFeed(feed)
        self.options = options or OptionHistoricalDataClient(api_key, api_secret, raw_data=True)
        self.stocks = stocks or StockHistoricalDataClient(api_key, api_secret, raw_data=True)
        self.trading = trading or TradingClient(api_key, api_secret, paper=paper)

    def option_bars(self, symbols, timeframe_: str = "1Day", start: DateLike = None, end: DateLike = None) -> pd.DataFrame:
        syms, tf, s, e = _symbols(symbols), timeframe(timeframe_), _dt(start), _clamp_end(end)
        raw = {}
        for i in range(0, len(syms), BATCH):
            raw.update(self.options.get_option_bars(OptionBarsRequest(symbol_or_symbols=syms[i:i + BATCH], timeframe=tf, start=s, end=e)))
        return bars_to_frame(raw)

    def stock_bars(self, symbols, timeframe_: str = "1Day", start: DateLike = None, end: DateLike = None,
                   feed: Optional[str] = None, adjustment: str = "raw") -> pd.DataFrame:
        syms, tf, s, e = _symbols(symbols), timeframe(timeframe_), _dt(start), _end(end) if feed else _clamp_end(end)
        raw = {}
        for i in range(0, len(syms), BATCH):
            raw.update(self.stocks.get_stock_bars(StockBarsRequest(symbol_or_symbols=syms[i:i + BATCH], timeframe=tf, start=s, end=e,
                                                                   feed=feed, adjustment=adjustment)))
        return bars_to_frame(raw)

    def option_contracts(self, underlying_symbols, **filters) -> pd.DataFrame:
        """filters: status, type, style, expiration_date[_gte|_lte], strike_price_gte/lte, root_symbol."""
        filters = {k: str(v) if k.startswith("strike") else v for k, v in filters.items()}
        out, token = [], None
        while True:
            req = GetOptionContractsRequest(underlying_symbols=_symbols(underlying_symbols), limit=10000, page_token=token,
                                            **{"status": "active", **filters})
            resp = self.trading.get_option_contracts(req)
            out += [c.model_dump(mode="json") for c in resp.option_contracts]
            token = resp.next_page_token
            if not token:
                return contracts_to_frame(out)

    def option_chain(self, underlying: str, **filters) -> pd.DataFrame:
        """filters: type, strike_price_gte/lte, expiration_date[_gte|_lte], root_symbol, updated_since."""
        req = OptionChainRequest(underlying_symbol=underlying.upper(), feed=self.feed, **filters)
        return snapshots_to_frame(self.options.get_option_chain(req))

    def option_snapshots(self, symbols) -> pd.DataFrame:
        syms, raw = _symbols(symbols), {}
        for i in range(0, len(syms), BATCH):
            raw.update(self.options.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=syms[i:i + BATCH], feed=self.feed)))
        return snapshots_to_frame(raw)
