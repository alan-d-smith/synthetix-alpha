import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha import config
from synthetix_alpha.data import BarStore, OptionBarsDataSource, chain_bars, dolt

RAW = pd.DataFrame({
    "date": ["2024-01-15", "2024-01-15", "2024-01-17", "2024-01-15"],
    "act_symbol": ["SPY", "SPY", "SPY", "BRK.B"],
    "expiration": ["2024-01-31"] * 4, "strike": [477.0, 477.0, 477.0, 360.0], "call_put": ["Call", "Put", "Call", "Call"],
    "bid": [6.29, 5.0, 7.0, 1.0], "ask": [6.32, 5.1, 7.1, 1.2], "vol": [0.1085, 0.11, 0.1, 0.2],
    "delta": [0.54, -0.46, 0.6, 0.5], "gamma": [0.03] * 4, "theta": [-0.2] * 4, "vega": [0.4] * 4, "rho": [0.1] * 4,
})
VOL = pd.DataFrame({"date": ["2024-01-15", "2024-01-16"], "act_symbol": ["SPY", "SPY"], "hv_current": [0.1, 0.12],
                    "iv_current": [0.13, 0.14], "iv_year_high_date": ["2023-10-27", "2023-10-27"]})


@pytest.fixture
def fake_dolt(monkeypatch, tmp_path):
    calls = []

    def query(sql, db=None):
        calls.append(sql)
        if "HASHOF" in sql:
            return pd.DataFrame({"h": ["abc123"]})
        raw = VOL if "volatility_history" in sql else RAW
        year = sql.split("BETWEEN '")[1][:4]
        return raw[raw["date"].str.startswith(year)]

    monkeypatch.setattr(dolt, "query", query)
    monkeypatch.setattr(config, "DOLT_CACHE", tmp_path)
    return calls


def test_chains_layout(fake_dolt):
    chains = dolt.load_chains(["spy", "BRK.B"], dt.date(2024, 1, 1), dt.date(2024, 1, 16))
    assert chains.index.names == ["date", "symbol"] and len(chains) == 3  # 01-17 row filtered out by end date
    call = chains.loc[(dt.date(2024, 1, 15), "SPY240131C00477000")]
    assert (call["type"], call["mid"], call["iv"], call["delta"], call["underlying"]) == ("call", 6.305, 0.1085, 0.54, "SPY")
    assert call["quote_time"] == pd.Timestamp("2024-01-15 21:00", tz="UTC") and pd.isna(call["volume"])
    assert "BRKB240131C00360000" in chains.loc[dt.date(2024, 1, 15)].index
    assert list(chains.columns) == list(dolt.CHAIN_COLUMNS)


def test_cache_per_symbol_year(fake_dolt):
    dolt.load_chains(["SPY"], dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    dolt.load_chains(["SPY"], dt.date(2024, 1, 1), dt.date(2024, 12, 31))  # cache hit
    assert sum("option_chain" in c for c in fake_dolt) == 1
    dolt.load_chains(["SPY", "BRK.B"], dt.date(2023, 6, 1), dt.date(2024, 6, 1))  # 2023 both + 2024 BRK.B
    assert sum("option_chain" in c for c in fake_dolt) == 3
    assert (config.DOLT_CACHE / "abc123" / "option_chain" / "BRK.B_2023.parquet").exists()


def test_volatility_and_bars(fake_dolt):
    vol = dolt.load_volatility(["SPY"], dt.date(2024, 1, 1), dt.date(2024, 1, 31))
    assert vol.loc[(dt.date(2024, 1, 16), "SPY"), "iv_current"] == 0.14 and vol["iv_year_high_date"].iloc[0] == dt.date(2023, 10, 27)
    chains = dolt.load_chains(["SPY"], dt.date(2024, 1, 1), dt.date(2024, 1, 31))
    store = BarStore(client=object())
    store.add("option", "1Day", chain_bars(chains))
    ds = OptionBarsDataSource(symbol="SPY240131C00477000", store=store)
    assert list(ds.get_data()) == [6.305, 7.05]
