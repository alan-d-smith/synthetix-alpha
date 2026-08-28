"""Alpaca market data: option contracts, option/stock bars, option chain snapshots (greeks/IV)."""

from __future__ import annotations

import datetime as dt
import time
from typing import Iterable, Optional, Union

import httpx
import pandas as pd

from synthetix_alpha import config
from synthetix_alpha.data.alpaca.occ import parse_occ_symbol

DateLike = Union[dt.date, dt.datetime, str, None]
BAR_FIELDS = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trade_count", "vw": "vwap"}
GREEKS = ("delta", "gamma", "theta", "vega", "rho")
CONTRACT_COLUMNS = ["symbol", "name", "status", "tradable", "expiration_date", "underlying_symbol", "type", "style",
                    "strike_price", "multiplier", "size", "root_symbol", "close_price", "close_price_date", "open_interest"]
CHAIN_COLUMNS = ["underlying", "expiration", "type", "strike", "bid", "ask", "mid", "bid_size", "ask_size",
                 "quote_time", "last", "trade_time", "iv", *GREEKS, "volume"]


class AlpacaAPIError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"{status} {url}: {body}")
        self.status = status


def _ts(v):
    if isinstance(v, dt.datetime):
        v = v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
        return v.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return v.isoformat() if isinstance(v, dt.date) else v


def _clamp_end(end):  # free plan: data from the last 15 min is gated (SIP / OPRA agreement)
    cutoff, e = _ts(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=16)), _ts(end)
    return cutoff if e is None or (e + "T23:59:59Z" if len(e) == 10 else e) > cutoff else end


def _symbols(s: Union[str, Iterable[str]]) -> list[str]:
    return [x.strip() for x in s.split(",")] if isinstance(s, str) else [str(x) for x in s]


def bars_to_frame(pages: Iterable[dict]) -> pd.DataFrame:
    rows = [{"timestamp": b["t"], "symbol": sym, **{n: b.get(k) for k, n in BAR_FIELDS.items()}}
            for page in pages for sym, bars in (page or {}).items() for b in bars or []]
    df = pd.DataFrame(rows, columns=["timestamp", "symbol", *BAR_FIELDS.values()])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values(["symbol", "timestamp"]).set_index("timestamp")


def snapshots_to_frame(pages: Iterable[dict]) -> pd.DataFrame:
    rows = []
    for page in pages:
        for sym, s in (page or {}).items():
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


def contracts_to_frame(pages: Iterable[list]) -> pd.DataFrame:
    df = pd.DataFrame([c for p in pages for c in p or []], columns=CONTRACT_COLUMNS if not any(pages) else None)
    for c in ("strike_price", "multiplier", "close_price", "open_interest"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).dt.date
    return df.set_index("symbol").sort_values(["expiration_date", "strike_price", "type"])


class AlpacaClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, *, data_url: str = config.DATA_URL,
                 trading_url: str = config.TRADING_URL, feed: str = config.OPTIONS_FEED, max_retries: int = 3,
                 transport: Optional[httpx.BaseTransport] = None):
        if api_key is None:
            api_key, api_secret = config.credentials()
        self.data_url, self.trading_url, self.feed, self.max_retries = data_url, trading_url, feed, max_retries
        self._http = httpx.Client(headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
                                  timeout=30, transport=transport)

    def _get(self, url: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(self.max_retries + 1):
            r = self._http.get(url, params=params)
            if r.status_code == 429 and attempt < self.max_retries:
                time.sleep(float(r.headers.get("Retry-After", 2**attempt)))
                continue
            if r.status_code >= 400:
                raise AlpacaAPIError(r.status_code, r.text, str(r.url))
            return r.json()

    def _pages(self, url: str, params: dict, key: str) -> list:
        token, out = None, []
        while True:
            data = self._get(url, {**params, "page_token": token})
            out.append(data.get(key))
            token = data.get("next_page_token")
            if not token:
                return out

    def _batched(self, url: str, symbols, params: dict, key: str) -> list:
        syms = _symbols(symbols)
        return [p for i in range(0, len(syms), 100)
                for p in self._pages(url, {**params, "symbols": ",".join(syms[i:i + 100])}, key)]

    def option_bars(self, symbols, timeframe: str = "1Day", start: DateLike = None, end: DateLike = None) -> pd.DataFrame:
        params = {"timeframe": timeframe, "start": _ts(start), "end": _ts(_clamp_end(end)), "limit": 10000}
        return bars_to_frame(self._batched(f"{self.data_url}/v1beta1/options/bars", symbols, params, "bars"))

    def stock_bars(self, symbols, timeframe: str = "1Day", start: DateLike = None, end: DateLike = None,
                   feed: Optional[str] = None, adjustment: str = "raw") -> pd.DataFrame:
        params = {"timeframe": timeframe, "start": _ts(start), "end": _ts(end if feed else _clamp_end(end)), "feed": feed,
                  "adjustment": adjustment, "limit": 10000}
        return bars_to_frame(self._batched(f"{self.data_url}/v2/stocks/bars", symbols, params, "bars"))

    def option_contracts(self, underlying_symbols, **filters) -> pd.DataFrame:
        """filters: status, type, expiration_date[_gte|_lte], strike_price_gte/lte, root_symbol."""
        params = {"underlying_symbols": ",".join(_symbols(underlying_symbols)), "status": "active", "limit": 10000,
                  **{k: _ts(v) for k, v in filters.items()}}
        return contracts_to_frame(self._pages(f"{self.trading_url}/v2/options/contracts", params, "option_contracts"))

    def option_chain(self, underlying: str, **filters) -> pd.DataFrame:
        """filters: type, strike_price_gte/lte, expiration_date[_gte|_lte], root_symbol, updated_since."""
        params = {"feed": self.feed, "limit": 1000, **{k: _ts(v) for k, v in filters.items()}}
        url = f"{self.data_url}/v1beta1/options/snapshots/{underlying.upper()}"
        return snapshots_to_frame(self._pages(url, params, "snapshots"))

    def option_snapshots(self, symbols) -> pd.DataFrame:
        params = {"feed": self.feed, "limit": 1000}
        return snapshots_to_frame(self._batched(f"{self.data_url}/v1beta1/options/snapshots", symbols, params, "snapshots"))
