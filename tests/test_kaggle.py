import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.data import BarStore, OptionBarsDataSource, StockBarsDataSource, chain_bars
from synthetix_alpha.data import kaggle

HEADER = ("[QUOTE_UNIXTIME], [QUOTE_READTIME], [QUOTE_DATE], [QUOTE_TIME_HOURS], [UNDERLYING_LAST], [EXPIRE_DATE], "
          "[EXPIRE_UNIX], [DTE], [C_DELTA], [C_GAMMA], [C_VEGA], [C_THETA], [C_RHO], [C_IV], [C_VOLUME], [C_LAST], "
          "[C_SIZE], [C_BID], [C_ASK], [STRIKE], [P_BID], [P_ASK], [P_SIZE], [P_LAST], [P_DELTA], [P_GAMMA], [P_VEGA], "
          "[P_THETA], [P_RHO], [P_IV], [P_VOLUME], [STRIKE_DISTANCE], [STRIKE_DISTANCE_PCT]")


def row(date, last, strike, c_bid, c_ask, p_bid, p_ask):
    return (f"0, {date} 16:00, {date}, 16.0, {last}, 2021-03-05, 0, 4.0, 0.5, 0.1, 0.2, -0.3, 0.01,  0.25, 10, 0, "
            f"1 x 2, {c_bid}, {c_ask}, {strike}, {p_bid}, {p_ask}, 3 x 4, 0, -0.5, 0.1, 0.2, -0.3, -0.01, , , 0, 0")


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "qqq_a.csv").write_text("\n".join([HEADER, row("2021-03-01", 323.5, 320.0, 10.0, 11.0, 5.0, 6.0),
                                                   row("2021-03-01", 323.5, 325.0, 7.0, 8.0, 8.0, 9.0)]))
    (tmp_path / "qqq_b.csv").write_text("\n".join([HEADER, row("2021-03-01", 323.5, 325.0, 7.0, 8.0, 8.0, 9.0),  # duplicate
                                                   row("2021-03-02", 325.0, 320.0, 12.0, 13.0, 4.0, 5.0)]))
    return tmp_path


def test_to_chains_layout(folder):
    chains = kaggle.load_chains("qqq", folder, cache=False)
    assert chains.index.names == ["date", "symbol"] and len(chains) == 6  # multi-file, de-duplicated
    snap = chains.loc[dt.date(2021, 3, 1)]
    call = snap.loc["QQQ210305C00320000"]
    assert (call["type"], call["strike"], call["mid"], call["delta"], call["iv"]) == ("call", 320.0, 10.5, 0.5, 0.25)
    assert (call["bid_size"], call["ask_size"], call["expiration"]) == (1, 2, dt.date(2021, 3, 5))
    assert call["quote_time"] == pd.Timestamp("2021-03-01 21:00", tz="UTC")
    put = snap.loc["QQQ210305P00325000"]
    assert put["mid"] == 8.5 and put["delta"] == -0.5 and pd.isna(put["iv"]) and pd.isna(put["volume"])


def test_parquet_cache_roundtrip(folder):
    chains = kaggle.load_chains("QQQ", folder)
    assert (folder / "qqq_chains.parquet").exists()
    pd.testing.assert_frame_equal(kaggle.load_chains("QQQ", folder), chains)


def test_bars_feed_the_store(folder):
    chains = kaggle.load_chains("QQQ", folder, cache=False)
    store = BarStore(client=object())  # any fetch would blow up
    store.add("option", "1Day", chain_bars(chains))
    store.add("stock", "1Day", kaggle.underlying_bars(chains))
    call = OptionBarsDataSource(symbol="QQQ210305C00320000", store=store)
    assert list(call.get_data()) == [10.5, 12.5] and call.get_data(dt.date(2021, 3, 2)) == 12.5
    assert store.window("option", "1Day", "QQQ210305C00320000") == (dt.date(2021, 3, 1), dt.date(2021, 3, 2))
    assert StockBarsDataSource(symbol="QQQ", store=store).get_data(dt.date(2021, 3, 2)) == 325.0
    with pytest.raises(RuntimeError):  # column exists but the source has no vwap
        OptionBarsDataSource(symbol="QQQ210305C00320000", field="vwap", store=store).get_data(dt.date(2021, 3, 1))
