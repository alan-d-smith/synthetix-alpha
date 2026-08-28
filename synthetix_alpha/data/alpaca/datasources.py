"""gs-quant DataSources over a shared, batched BarStore.

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

from synthetix_alpha.data.alpaca.client import BAR_FIELDS, AlpacaClient
from synthetix_alpha.data.alpaca.occ import parse_occ_symbol

NY = ZoneInfo("America/New_York")
OPTIONS_DATA_START = dt.date(2024, 2, 1)
_INTRADAY = re.compile(r"^\d+(Min|T|Hour|H)$", re.I)
Key = tuple[str, str, str]  # (kind, timeframe, symbol)


def _date(v: Union[dt.date, dt.datetime]) -> dt.date:
    return (v.astimezone(NY) if v.tzinfo else v).date() if isinstance(v, dt.datetime) else v


class BarStore:
    """Caches bars per (kind, timeframe, symbol); missing symbols/windows are fetched in batched requests."""

    def __init__(self, client: Optional[AlpacaClient] = None, stock_feed: Optional[str] = None):
        self._client, self.stock_feed = client, stock_feed
        self._bars: dict[Key, pd.DataFrame] = {}
        self._window: dict[Key, tuple[dt.date, dt.date]] = {}

    @property
    def client(self) -> AlpacaClient:
        if self._client is None:
            self._client = AlpacaClient()
        return self._client

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
            bars = self.client.option_bars(list(todo), timeframe, lo, hi + dt.timedelta(days=1))
        else:
            bars = self.client.stock_bars(list(todo), timeframe, lo, hi + dt.timedelta(days=1), feed=self.stock_feed)
        for s in todo:
            self._bars[(kind, timeframe, s)] = bars[bars["symbol"] == s]
            self._window[(kind, timeframe, s)] = (lo, hi)

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
class AlpacaBarsDataSource(DataSource):
    symbol: str
    field: str = "close"
    timeframe: str = "1Day"
    start: Optional[dt.date] = dc_field(default=None, metadata=field_metadata)
    end: Optional[dt.date] = dc_field(default=None, metadata=field_metadata)
    missing_data_strategy: MissingDataStrategy = dc_field(default=MissingDataStrategy.fail, metadata=field_metadata)
    store: InitVar[Optional[BarStore]] = None
    class_type: str = static_field("alpaca_bars_data_source")

    kind: ClassVar[str]
    floor: ClassVar[dt.date] = dt.date(2000, 1, 1)
    history: ClassVar[dt.timedelta] = dt.timedelta(days=5 * 365)

    def __post_init__(self, store=None):
        self.store = store or default_store()
        self.field = BAR_FIELDS.get(self.field, self.field)
        if self.field not in BAR_FIELDS.values():
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
        s = bars[self.field].astype(float)
        if s.empty:
            raise RuntimeError(f"no {self.timeframe} bars for {self.symbol} in [{start}, {end}]")
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
class AlpacaOptionBarsDataSource(AlpacaBarsDataSource):
    class_type: str = static_field("alpaca_option_bars_data_source")
    kind: ClassVar[str] = "option"
    floor: ClassVar[dt.date] = OPTIONS_DATA_START
    history: ClassVar[dt.timedelta] = dt.timedelta(days=3650)

    def __post_init__(self, store=None):
        super().__post_init__(store)
        self.symbol = parse_occ_symbol(self.symbol).symbol


@dataclass_json
@dataclass
class AlpacaStockBarsDataSource(AlpacaBarsDataSource):
    class_type: str = static_field("alpaca_stock_bars_data_source")
    kind: ClassVar[str] = "stock"

    def __post_init__(self, store=None):
        super().__post_init__(store)
        self.symbol = self.symbol.upper()


def to_eq_option(symbol: str, buy_sell: BuySell = BuySell.Buy, number_of_options: float = 1.0) -> EqOption:
    c = parse_occ_symbol(symbol)
    return EqOption(underlier=c.underlying, expiration_date=c.expiration, strike_price=c.strike,
                    option_type=OptionType.Call if c.option_type == "call" else OptionType.Put,
                    option_style=OptionStyle.American, number_of_options=number_of_options, multiplier=100.0,
                    buy_sell=buy_sell, name=c.symbol)


def register(data_manager: DataManager, daily: AlpacaBarsDataSource, intraday: Optional[AlpacaBarsDataSource] = None,
             instrument: Optional[Instrument] = None) -> Instrument:
    """Register price sources for PredefinedAssetEngine: `daily` for EOD valuation, `intraday` (or `daily`) for fills."""
    instrument = instrument or to_eq_option(daily.symbol)
    data_manager.add_data_source(daily, DataFrequency.DAILY, instrument, ValuationFixingType.PRICE)
    data_manager.add_data_source(intraday or daily, DataFrequency.REAL_TIME, instrument, ValuationFixingType.PRICE)
    return instrument
