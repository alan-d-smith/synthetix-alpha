import datetime as dt

import pytest
from alpaca.trading.models import OptionContract, OptionContractsResponse

from gs_quant.backtests.actions import AddTradeAction
from gs_quant.backtests.data_sources import DataManager, MissingDataStrategy
from gs_quant.backtests.predefined_asset_engine import PredefinedAssetEngine
from gs_quant.backtests.strategy import Strategy
from gs_quant.backtests.triggers import DateTrigger, DateTriggerRequirements

from synthetix_alpha.data import (
    AlpacaClient, BarStore, OptionBarsDataSource, StockBarsDataSource, build_occ_symbol, parse_occ_symbol, register, to_eq_option,
)
from synthetix_alpha.data.alpaca import timeframe

SYM, PUT = "SPY240816C00550000", "SPY240816P00550000"
DAYS = [dt.date(2024, 8, 5) + dt.timedelta(days=i) for i in range(5)]  # Mon-Fri
CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


def bar(t, c):
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100, "n": 5, "vw": c}


class FakeSDK:
    """Stands in for the three alpaca-py clients; records every request object."""

    def __init__(self):
        self.requests = []
        self.option_bars = {SYM: [bar(f"{d}T04:00:00Z", c) for d, c in zip(DAYS, CLOSES)],
                            PUT: [bar(f"{d}T04:00:00Z", 2 * c) for d, c in zip(DAYS, CLOSES)]}
        self.stock_bars = {"SPY": [bar(f"{d}T04:00:00Z", 500 + c) for d, c in zip(DAYS, CLOSES)]}
        self.snapshots = {
            SYM: {"latestQuote": {"bp": 1.0, "ap": 1.2, "t": "2024-08-05T19:59:59Z"}, "latestTrade": {"p": 1.1},
                  "impliedVolatility": 0.2, "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.3, "rho": 0.01},
                  "dailyBar": {"v": 42}},
            PUT: {"latestQuote": {"bp": 2.0, "ap": 2.4}, "greeks": {"delta": -0.5}},
        }
        self.contracts = [OptionContract(id="1", symbol=SYM, name="SPY Aug 16 2024 550 Call", status="active", tradable=True,
                                         expiration_date=dt.date(2024, 8, 16), root_symbol="SPY", underlying_symbol="SPY",
                                         underlying_asset_id="b28f4066-5c6d-479b-a2af-85dc1a8f16fb", type="call", style="american",
                                         strike_price=550.0, size="100", open_interest="1234", close_price="9.5")]

    def _bars(self, src, req):
        self.requests.append(req)
        s = req.start.strftime("%Y-%m-%dT%H:%M:%SZ") if req.start else ""
        e = req.end.strftime("%Y-%m-%dT%H:%M:%SZ") if req.end else "9"
        syms = [req.symbol_or_symbols] if isinstance(req.symbol_or_symbols, str) else req.symbol_or_symbols
        return {k: v for k in syms if (v := [b for b in src.get(k, []) if s <= b["t"] <= e])}

    def get_option_bars(self, req):
        return self._bars(self.option_bars, req)

    def get_stock_bars(self, req):
        return self._bars(self.stock_bars, req)

    def get_option_chain(self, req):
        self.requests.append(req)
        t = req.type.value if req.type else None
        return {k: v for k, v in self.snapshots.items() if k.startswith(req.underlying_symbol) and t in (None, parse_occ_symbol(k).option_type)}

    def get_option_snapshot(self, req):
        self.requests.append(req)
        return {k: self.snapshots[k] for k in req.symbol_or_symbols if k in self.snapshots}

    def get_option_contracts(self, req):
        self.requests.append(req)
        page = 0 if req.page_token is None else int(req.page_token)
        items = self.contracts if req.underlying_symbols == ["SPY"] else []
        return OptionContractsResponse(option_contracts=items[page:page + 1], next_page_token=str(page + 1) if page + 1 < len(items) else None)


@pytest.fixture
def fake():
    return FakeSDK()


@pytest.fixture
def client(fake):
    return AlpacaClient(options=fake, stocks=fake, trading=fake)


@pytest.fixture
def store(client):
    return BarStore(client)


def test_occ_roundtrip():
    occ = parse_occ_symbol("spy240816c00550000")
    assert occ == ("SPY", dt.date(2024, 8, 16), "call", 550.0) and occ.symbol == SYM
    assert build_occ_symbol("SPXW", "2025-01-17", "put", 5990.5) == "SPXW250117P05990500"
    with pytest.raises(ValueError):
        parse_occ_symbol("SPY")


def test_timeframes():
    assert str(timeframe("15Min")) == "15Min" and str(timeframe("1Day")) == "1Day" and str(timeframe("2Hour")) == "2Hour"
    with pytest.raises(ValueError):
        timeframe("fortnight")


def test_option_bars_frame_and_window(fake, client):
    df = client.option_bars(SYM, "1Day", dt.date(2024, 8, 6), dt.date(2024, 8, 8))
    assert list(df["close"]) == [11.0, 12.0, 13.0] and str(df.index.tz) == "UTC" and list(df.columns)[0] == "symbol"
    req = fake.requests[0]
    assert (req.start, req.end) == (dt.datetime(2024, 8, 6), dt.datetime(2024, 8, 9))  # inclusive dates; SDK stores naive UTC
    client.option_bars(SYM, "1Day", dt.date(2024, 8, 5), dt.date.today() + dt.timedelta(days=5))
    assert fake.requests[-1].end < dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)  # clamped for the free plan


def test_symbols_are_batched_by_100(fake, client):
    client.option_bars([f"X{i:03d}240816C00001000" for i in range(250)])
    assert [len(r.symbol_or_symbols) for r in fake.requests] == [100, 100, 50]


def test_chain_snapshots_and_contracts(fake, client):
    chain = client.option_chain("SPY", type="call")
    assert list(chain.index) == [SYM] and chain.loc[SYM, "mid"] == pytest.approx(1.1) and chain.loc[SYM, "delta"] == 0.5
    assert chain.loc[SYM, "volume"] == 42 and fake.requests[-1].feed.value == "indicative"
    assert len(client.option_chain("SPY")) == 2 and client.option_chain("QQQ").empty
    assert len(client.option_snapshots([SYM, PUT])) == 2
    contracts = client.option_contracts("SPY", expiration_date_lte=dt.date(2024, 9, 1), strike_price_gte=500)
    assert contracts.loc[SYM, "strike_price"] == 550.0 and contracts.loc[SYM, "open_interest"] == 1234
    assert fake.requests[-1].strike_price_gte == "500" and str(fake.requests[-1].expiration_date_lte) == "2024-09-01"
    assert "strike_price" in client.option_contracts("QQQ").columns


def test_daily_datasource(fake, store):
    ds = OptionBarsDataSource(symbol=SYM, store=store, missing_data_strategy=MissingDataStrategy.fill_forward)
    assert not fake.requests  # lazy
    assert ds.get_data(dt.date(2024, 8, 6)) == 11.0
    assert ds.get_data(dt.datetime(2024, 8, 6, 23, 0)) == 11.0  # datetime -> that trading day
    assert list(ds.get_data_range(dt.date(2024, 8, 8), 3)) == [10.0, 11.0, 12.0]
    assert list(ds.get_data_range(dt.date(2024, 8, 6), dt.date(2024, 8, 8))) == [12.0, 13.0]
    assert ds.get_data(dt.date(2024, 8, 10)) == 14.0  # weekend -> fill forward
    assert len(fake.requests) == 1 and ds.get_data().name == SYM
    assert OptionBarsDataSource.from_dict(ds.to_dict()) == ds
    with pytest.raises(ValueError):
        OptionBarsDataSource(symbol=SYM, field="bogus")


def test_store_batches_and_shares(fake, store):
    store.ensure("option", "1Day", [SYM, PUT], DAYS[0], DAYS[-1])
    call = OptionBarsDataSource(symbol=SYM, store=store)
    put = OptionBarsDataSource(symbol=PUT, field="open", store=store)
    assert call.get_data(DAYS[1]) == 11.0 and put.get_data(DAYS[1]) == 22.0
    assert len(fake.requests) == 1 and fake.requests[0].symbol_or_symbols == [SYM, PUT]


def test_intraday_datasource_and_window_widening(fake, store):
    fake.option_bars[SYM] = [bar("2024-08-05T14:30:00Z", 1.0), bar("2024-08-05T14:31:00Z", 2.0)]
    ds = OptionBarsDataSource(symbol=SYM, timeframe="1Min", store=store)
    assert ds.get_data(dt.datetime(2024, 8, 5, 14, 31)) == 2.0
    assert ds.get_data(dt.datetime(2024, 8, 5, 14, 31, tzinfo=dt.timezone.utc)) == 2.0
    first = fake.requests[0].start
    ds.get_data_range(dt.datetime(2024, 8, 5, 14, 30), dt.datetime(2024, 8, 5, 14, 31))
    assert len(fake.requests) == 1
    fake.option_bars[SYM].insert(0, bar("2024-06-03T14:30:00Z", 0.5))
    assert ds.get_data(dt.datetime(2024, 6, 3, 14, 30)) == 0.5 and fake.requests[1].start < first


def test_stock_datasource(fake, store):
    ds = StockBarsDataSource(symbol="spy", store=store, start=DAYS[0], end=DAYS[-1])
    assert ds.get_data(DAYS[2]) == 512.0 and fake.requests[0].symbol_or_symbols == ["SPY"]


def test_backtest_with_predefined_asset_engine(store):
    dm = DataManager()
    option = register(dm, OptionBarsDataSource(symbol=SYM, store=store, missing_data_strategy=MissingDataStrategy.fill_forward))
    assert option == to_eq_option(SYM) and option.name == SYM
    trigger = DateTrigger(DateTriggerRequirements([dt.datetime(2024, 8, 5, 20, 0)]), AddTradeAction(option, dt.timedelta(days=2)))
    perf = PredefinedAssetEngine(dm).run_backtest(Strategy(None, trigger), start=DAYS[0], end=DAYS[-1], frequency="D").performance
    assert perf[dt.date(2024, 8, 7)] - perf[dt.date(2024, 8, 5)] == pytest.approx(2.0)  # bought 10, sold 12
    assert perf[dt.date(2024, 8, 9)] == perf[dt.date(2024, 8, 7)]
