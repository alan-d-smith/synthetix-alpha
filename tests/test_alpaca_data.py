import datetime as dt

import httpx
import pytest

from gs_quant.backtests.actions import AddTradeAction
from gs_quant.backtests.data_sources import DataManager, MissingDataStrategy
from gs_quant.backtests.predefined_asset_engine import PredefinedAssetEngine
from gs_quant.backtests.strategy import Strategy
from gs_quant.backtests.triggers import DateTrigger, DateTriggerRequirements

from synthetix_alpha.data.alpaca import (
    AlpacaAPIError, AlpacaClient, AlpacaOptionBarsDataSource, AlpacaStockBarsDataSource, BarStore, build_occ_symbol,
    parse_occ_symbol, register, to_eq_option,
)

SYM, PUT = "SPY240816C00550000", "SPY240816P00550000"
DAYS = [dt.date(2024, 8, 5) + dt.timedelta(days=i) for i in range(5)]  # Mon-Fri
CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


def bar(t, c):
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100, "n": 5, "vw": c}


class FakeAlpaca:
    def __init__(self, page_size=1000):
        self.page_size, self.requests, self.rate_limit_once = page_size, [], False
        self.option_bars = {SYM: [bar(f"{d}T04:00:00Z", c) for d, c in zip(DAYS, CLOSES)],
                            PUT: [bar(f"{d}T04:00:00Z", 2 * c) for d, c in zip(DAYS, CLOSES)]}
        self.stock_bars = {"SPY": [bar(f"{d}T04:00:00Z", 500 + c) for d, c in zip(DAYS, CLOSES)]}
        self.snapshots = {
            SYM: {"latestQuote": {"bp": 1.0, "ap": 1.2, "t": "2024-08-05T19:59:59Z"}, "latestTrade": {"p": 1.1},
                  "impliedVolatility": 0.2, "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.3, "rho": 0.01},
                  "dailyBar": {"v": 42}},
            PUT: {"latestQuote": {"bp": 2.0, "ap": 2.4}, "greeks": {"delta": -0.5}},
        }
        self.contracts = [{"symbol": SYM, "expiration_date": "2024-08-16", "type": "call", "strike_price": "550",
                           "multiplier": "100", "close_price": "9.5", "open_interest": "1234", "underlying_symbol": "SPY"}]

    def _page(self, items, params):
        off = int(params.get("page_token") or 0)
        return items[off:off + self.page_size], (str(off + self.page_size) if off + self.page_size < len(items) else None)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        p, path = dict(request.url.params), request.url.path
        if self.rate_limit_once:
            self.rate_limit_once = False
            return httpx.Response(429, headers={"Retry-After": "0"})
        if path in ("/v1beta1/options/bars", "/v2/stocks/bars"):
            src = self.option_bars if "options" in path else self.stock_bars
            items = [(s, b) for s in p["symbols"].split(",") for b in src.get(s, []) if p.get("start", "") <= b["t"] <= p.get("end", "9")]
            page, token = self._page(items, p)
            bars = {}
            for s, b in page:
                bars.setdefault(s, []).append(b)
            return httpx.Response(200, json={"bars": bars, "next_page_token": token})
        if path.startswith("/v1beta1/options/snapshots"):
            syms = p["symbols"].split(",") if "symbols" in p else [s for s in self.snapshots if s.startswith(path.rsplit("/", 1)[1])]
            page, token = self._page([s for s in syms if s in self.snapshots and p.get("type", parse_occ_symbol(s).option_type) == parse_occ_symbol(s).option_type], p)
            return httpx.Response(200, json={"snapshots": {s: self.snapshots[s] for s in page}, "next_page_token": token})
        if path == "/v2/options/contracts":
            page, token = self._page(self.contracts, p)
            return httpx.Response(200, json={"option_contracts": page, "next_page_token": token})
        return httpx.Response(404, text="nope")


@pytest.fixture
def fake():
    return FakeAlpaca()


@pytest.fixture
def client(fake):
    return AlpacaClient("k", "s", data_url="https://data.test", trading_url="https://paper.test", transport=httpx.MockTransport(fake))


@pytest.fixture
def store(client):
    return BarStore(client)


def test_occ_roundtrip():
    occ = parse_occ_symbol("spy240816c00550000")
    assert occ == ("SPY", dt.date(2024, 8, 16), "call", 550.0) and occ.symbol == SYM
    assert build_occ_symbol("SPXW", "2025-01-17", "put", 5990.5) == "SPXW250117P05990500"
    with pytest.raises(ValueError):
        parse_occ_symbol("SPY")


def test_option_bars_pagination_and_frame(fake, client):
    fake.page_size = 2
    df = client.option_bars(SYM, "1Day", dt.date(2024, 8, 5), dt.date(2024, 8, 10))
    assert len(fake.requests) == 3 and "page_token=2" in str(fake.requests[1].url)
    assert list(df["close"]) == CLOSES and str(df.index.tz) == "UTC"
    assert dict(fake.requests[0].url.params)["start"] == "2024-08-05"


def test_symbols_are_batched_by_100(fake, client):
    client.option_bars([f"X{i:03d}240816C00001000" for i in range(250)])
    assert len(fake.requests) == 3


def test_chain_and_contracts(fake, client):
    chain = client.option_chain("SPY", type="call")
    assert list(chain.index) == [SYM] and chain.loc[SYM, "mid"] == pytest.approx(1.1) and chain.loc[SYM, "delta"] == 0.5
    assert dict(fake.requests[-1].url.params)["feed"] == "indicative"
    assert len(client.option_chain("SPY")) == 2 and client.option_chain("QQQ").empty
    contracts = client.option_contracts("SPY", expiration_date_lte=dt.date(2024, 9, 1))
    assert contracts.loc[SYM, "strike_price"] == 550.0 and contracts.loc[SYM, "open_interest"] == 1234
    assert dict(fake.requests[-1].url.params)["expiration_date_lte"] == "2024-09-01"
    assert "strike_price" in client.option_contracts("QQQ").columns


def test_retry_and_errors(fake, client, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    fake.rate_limit_once = True
    assert len(client.option_snapshots([SYM])) == 1 and len(fake.requests) == 2
    with pytest.raises(AlpacaAPIError):
        client._get("https://data.test/missing", {})


def test_daily_datasource(fake, store):
    ds = AlpacaOptionBarsDataSource(symbol=SYM, field="c", store=store, missing_data_strategy=MissingDataStrategy.fill_forward)
    assert not fake.requests  # lazy
    assert ds.get_data(dt.date(2024, 8, 6)) == 11.0
    assert ds.get_data(dt.datetime(2024, 8, 6, 23, 0)) == 11.0  # datetime -> that trading day
    assert list(ds.get_data_range(dt.date(2024, 8, 8), 3)) == [10.0, 11.0, 12.0]
    assert list(ds.get_data_range(dt.date(2024, 8, 6), dt.date(2024, 8, 8))) == [12.0, 13.0]
    assert ds.get_data(dt.date(2024, 8, 10)) == 14.0  # weekend -> fill forward
    assert len(fake.requests) == 1 and ds.get_data().name == SYM
    assert AlpacaOptionBarsDataSource.from_dict(ds.to_dict()) == ds
    with pytest.raises(ValueError):
        AlpacaOptionBarsDataSource(symbol=SYM, field="bogus")


def test_store_batches_and_shares(fake, store):
    store.ensure("option", "1Day", [SYM, PUT], DAYS[0], DAYS[-1])
    call = AlpacaOptionBarsDataSource(symbol=SYM, store=store)
    put = AlpacaOptionBarsDataSource(symbol=PUT, field="open", store=store)
    assert call.get_data(DAYS[1]) == 11.0 and put.get_data(DAYS[1]) == 22.0
    assert len(fake.requests) == 1 and dict(fake.requests[0].url.params)["symbols"] == f"{SYM},{PUT}"


def test_intraday_datasource_and_window_widening(fake, store):
    fake.option_bars[SYM] = [bar("2024-08-05T14:30:00Z", 1.0), bar("2024-08-05T14:31:00Z", 2.0)]
    ds = AlpacaOptionBarsDataSource(symbol=SYM, timeframe="1Min", store=store)
    assert ds.get_data(dt.datetime(2024, 8, 5, 14, 31)) == 2.0
    assert ds.get_data(dt.datetime(2024, 8, 5, 14, 31, tzinfo=dt.timezone.utc)) == 2.0
    first = dict(fake.requests[0].url.params)["start"]
    ds.get_data_range(dt.datetime(2024, 8, 5, 14, 30), dt.datetime(2024, 8, 5, 14, 31))
    assert len(fake.requests) == 1
    fake.option_bars[SYM].insert(0, bar("2024-06-03T14:30:00Z", 0.5))
    assert ds.get_data(dt.datetime(2024, 6, 3, 14, 30)) == 0.5 and dict(fake.requests[1].url.params)["start"] < first


def test_stock_datasource(fake, store):
    ds = AlpacaStockBarsDataSource(symbol="spy", store=store, start=DAYS[0], end=DAYS[-1])
    assert ds.get_data(DAYS[2]) == 512.0 and "/v2/stocks/bars" in str(fake.requests[0].url)


def test_backtest_with_predefined_asset_engine(store):
    dm = DataManager()
    option = register(dm, AlpacaOptionBarsDataSource(symbol=SYM, store=store, missing_data_strategy=MissingDataStrategy.fill_forward))
    assert option == to_eq_option(SYM) and option.name == SYM
    trigger = DateTrigger(DateTriggerRequirements([dt.datetime(2024, 8, 5, 20, 0)]), AddTradeAction(option, dt.timedelta(days=2)))
    perf = PredefinedAssetEngine(dm).run_backtest(Strategy(None, trigger), start=DAYS[0], end=DAYS[-1], frequency="D").performance
    assert perf[dt.date(2024, 8, 7)] - perf[dt.date(2024, 8, 5)] == pytest.approx(2.0)  # bought 10, sold 12
    assert perf[dt.date(2024, 8, 9)] == perf[dt.date(2024, 8, 7)]
