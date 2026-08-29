"""BarStore (batched, cached bars from any provider) and gs-quant DataSources over it.

Daily sources are indexed by tz-naive NY trading date and also answer datetime states with that day's bar,
so one daily source serves both DAILY (valuation) and REAL_TIME (fills) in PredefinedAssetEngine.
Intraday sources keep a UTC DatetimeIndex.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import InitVar, dataclass
from dataclasses import field as dc_field
from typing import ClassVar, Iterable, Optional, Union
from zoneinfo import ZoneInfo

import pandas as pd
from dataclasses_json import dataclass_json

from gs_quant.backtests.core import ValuationFixingType
from gs_quant.backtests.data_sources import DataManager, DataSource, GenericDataSource, MissingDataStrategy
from gs_quant.base import field_metadata, static_field
from gs_quant.common import BuySell, OptionStyle, OptionType
from gs_quant.data import DataFrequency
from gs_quant.instrument import EqOption, Instrument

from synthetix_alpha.data.alpaca import AlpacaClient
from synthetix_alpha.data.occ import parse_occ_symbol
from synthetix_alpha.data.schema import BAR_COLUMNS

NY = ZoneInfo("America/New_York")
OPTIONS_DATA_START = dt.date(2024, 2, 1)  # Alpaca option history begins here
_INTRADAY = re.compile(r"^\d+(Min|T|Hour|H)$", re.I)
Key = tuple[str, str, str]  # (kind, timeframe, symbol)


def _date(v: Union[dt.date, dt.datetime]) -> dt.date:
    return (v.astimezone(NY) if v.tzinfo else v).date() if isinstance(v, dt.datetime) else v


class BarStore:
    """Caches bars per (kind, timeframe, symbol). Preload with `add`; anything missing is fetched from Alpaca in batches."""

    def __init__(self, client: Optional[AlpacaClient] = None, stock_feed: Optional[str] = None):
        self._client, self.stock_feed = client, stock_feed
        self._bars: dict[Key, pd.DataFrame] = {}
        self._window: dict[Key, tuple[dt.date, dt.date]] = {}

    @property
    def client(self) -> AlpacaClient:
        if self._client is None:
            self._client = AlpacaClient()
        return self._client

    def add(self, kind: str, timeframe: str, bars: pd.DataFrame, start: Optional[dt.date] = None,
            end: Optional[dt.date] = None) -> None:
        """Preload bars in the BAR_COLUMNS layout; the covered window defaults to the bars' own date range."""
        for symbol, b in bars.groupby("symbol", sort=False):
            self._put(kind, timeframe, symbol, b, start or b.index.min().date(), end or b.index.max().date())

    def _put(self, kind, timeframe, symbol, bars, start, end):
        key = (kind, timeframe, symbol)
        if key in self._bars:
            bars = pd.concat([self._bars[key], bars])
            bars = bars[~bars.index.duplicated(keep="last")].sort_index()
            w = self._window[key]
            start, end = min(start, w[0]), max(end, w[1])
        self._bars[key], self._window[key] = bars, (start, end)

    def ensure(self, kind: str, timeframe: str, symbols: Iterable[str], start: dt.date, end: dt.date) -> None:
        todo = {}
        for s in symbols:
            w = self._window.get((kind, timeframe, s))
            if w is None or start < w[0] or end > w[1]:
                todo[s] = (min(start, w[0]), max(end, w[1])) if w else (start, end)
        if not todo:
            return
        lo, hi = min(w[0] for w in todo.values()), max(w[1] for w in todo.values())
        if kind == "option":
            bars = self.client.option_bars(list(todo), timeframe, lo, hi)
        else:
            bars = self.client.stock_bars(list(todo), timeframe, lo, hi, feed=self.stock_feed)
        for s in todo:
            self._put(kind, timeframe, s, bars[bars["symbol"] == s], lo, hi)

    def bars(self, kind: str, timeframe: str, symbol: str) -> pd.DataFrame:
        return self._bars[(kind, timeframe, symbol)]

    def window(self, kind: str, timeframe: str, symbol: str) -> Optional[tuple[dt.date, dt.date]]:
        return self._window.get((kind, timeframe, symbol))


_default_store: Optional[BarStore] = None


def default_store() -> BarStore:
    global _default_store
    if _default_store is None:
        _default_store = BarStore()
    return _default_store


@dataclass_json
@dataclass
class BarsDataSource(DataSource):
    symbol: str
    field: str = "close"
    timeframe: str = "1Day"
    start: Optional[dt.date] = dc_field(default=None, metadata=field_metadata)
    end: Optional[dt.date] = dc_field(default=None, metadata=field_metadata)
    missing_data_strategy: MissingDataStrategy = dc_field(default=MissingDataStrategy.fail, metadata=field_metadata)
    store: InitVar[Optional[BarStore]] = None
    class_type: str = static_field("bars_data_source")

    kind: ClassVar[str]
    floor: ClassVar[dt.date] = dt.date(2000, 1, 1)
    history: ClassVar[dt.timedelta] = dt.timedelta(days=5 * 365)

    def __post_init__(self, store=None):
        self.store = store or default_store()
        if self.field not in BAR_COLUMNS[1:]:
            raise ValueError(f"unknown bar field {self.field!r}")
        self._bars: Optional[pd.DataFrame] = None
        self._source: Optional[GenericDataSource] = None

    @property
    def intraday(self) -> bool:
        return bool(_INTRADAY.match(self.timeframe))

    def _ensure(self, lo: Optional[dt.date], hi: Optional[dt.date]) -> None:
        cached = self.store.window(self.kind, self.timeframe, self.symbol)
        if cached is None:  # cold: pull the default history once
            end = self.end or max(hi or dt.date.min, dt.date.today())
            history = dt.timedelta(days=30) if self.intraday else self.history
            start = self.start or min(lo or dt.date.max, max(self.floor, end - history))
        else:
            start, end = (self.start or lo, self.end or hi) if lo else cached
        self.store.ensure(self.kind, self.timeframe, [self.symbol], start, end)
        bars = self.store.bars(self.kind, self.timeframe, self.symbol)
        if bars is self._bars:
            return
        s = bars[self.field].astype(float).dropna()
        if s.empty:
            raise RuntimeError(f"no {self.timeframe} {self.field} for {self.symbol} in [{start}, {end}]")
        if not self.intraday:
            s.index = s.index.tz_convert(NY).normalize().tz_localize(None)
            s = s[~s.index.duplicated(keep="last")]
        self._bars, self._source = bars, GenericDataSource(s.rename(self.symbol), self.missing_data_strategy)

    def _key(self, state):
        if not self.intraday:
            return pd.Timestamp(_date(state))
        return state.replace(tzinfo=dt.timezone.utc) if isinstance(state, dt.datetime) and state.tzinfo is None else state

    def get_data(self, state=None, **kwargs):
        if state is None:
            self._ensure(None, None)
            return self._source.data_set
        if isinstance(state, Iterable):
            return [self.get_data(s) for s in state]
        self._ensure(_date(state), _date(state))
        return self._source.get_data(self._key(state))

    def get_data_range(self, start, end, **kwargs) -> pd.Series:
        lo = _date(start)
        self._ensure(lo, lo if isinstance(end, int) else _date(end))
        return self._source.get_data_range(self._key(start), end if isinstance(end, int) else self._key(end))


@dataclass_json
@dataclass
class OptionBarsDataSource(BarsDataSource):
    class_type: str = static_field("option_bars_data_source")
    kind: ClassVar[str] = "option"
    floor: ClassVar[dt.date] = OPTIONS_DATA_START
    history: ClassVar[dt.timedelta] = dt.timedelta(days=3650)

    def __post_init__(self, store=None):
        super().__post_init__(store)
        self.symbol = parse_occ_symbol(self.symbol).symbol


@dataclass_json
@dataclass
class StockBarsDataSource(BarsDataSource):
    class_type: str = static_field("stock_bars_data_source")
    kind: ClassVar[str] = "stock"

    def __post_init__(self, store=None):
        super().__post_init__(store)
        self.symbol = self.symbol.upper()


def chain_bars(chains: pd.DataFrame) -> pd.DataFrame:
    """Historical chains ((date, symbol) x CHAIN_COLUMNS) -> daily bars with close = mid, volume; OHLC/vwap NaN."""
    df = chains.reset_index()
    bars = pd.DataFrame({"timestamp": df["quote_time"], "symbol": df["symbol"], "close": df["mid"], "volume": df["volume"]})
    return bars.reindex(columns=["timestamp", *BAR_COLUMNS]).set_index("timestamp")


def to_eq_option(symbol: str, buy_sell: BuySell = BuySell.Buy, number_of_options: float = 1.0) -> EqOption:
    c = parse_occ_symbol(symbol)
    return EqOption(underlier=c.underlying, expiration_date=c.expiration, strike_price=c.strike,
                    option_type=OptionType.Call if c.option_type == "call" else OptionType.Put,
                    option_style=OptionStyle.American, number_of_options=number_of_options, multiplier=100.0,
                    buy_sell=buy_sell, name=c.symbol)


def register(data_manager: DataManager, daily: BarsDataSource, intraday: Optional[BarsDataSource] = None,
             instrument: Optional[Instrument] = None) -> Instrument:
    """Register price sources for PredefinedAssetEngine: `daily` for EOD valuation, `intraday` (or `daily`) for fills."""
    instrument = instrument or to_eq_option(daily.symbol)
    data_manager.add_data_source(daily, DataFrequency.DAILY, instrument, ValuationFixingType.PRICE)
    data_manager.add_data_source(intraday or daily, DataFrequency.REAL_TIME, instrument, ValuationFixingType.PRICE)
    return instrument
