import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.data import yf

DATES = [dt.date(2021, 1, 27), dt.date(2021, 4, 28), dt.date(2021, 7, 27)]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(yf, "CACHE", tmp_path)
    return tmp_path


def seed(cache, symbol, kind, df):
    df.to_parquet(cache / f"{symbol}_{kind}.parquet", index=False)


def test_earnings_dates_read_from_cache(cache):
    seed(cache, "AAPL", "earnings", pd.DataFrame({"date": DATES}))
    got = yf.earnings_dates("AAPL")
    assert list(got) == DATES and got.is_monotonic_increasing


def test_days_to_earnings(cache):
    seed(cache, "AAPL", "earnings", pd.DataFrame({"date": DATES}))
    idx = [dt.date(2021, 1, 20), dt.date(2021, 1, 27), dt.date(2021, 2, 1)]
    d = yf.days_to_earnings("AAPL", idx)
    assert list(d) == [7.0, 0.0, 86.0]  # counts to the next announcement, 0 on the day itself


def test_days_to_earnings_beyond_horizon_is_nan(cache):
    seed(cache, "AAPL", "earnings", pd.DataFrame({"date": [dt.date(2030, 1, 1)]}))
    assert pd.isna(yf.days_to_earnings("AAPL", [dt.date(2021, 1, 1)], horizon=400).iloc[0])


def test_no_earnings_gives_nan_not_error(cache):
    seed(cache, "NONE", "earnings", pd.DataFrame({"date": []}))
    assert yf.days_to_earnings("NONE", [dt.date(2021, 1, 1)]).isna().all()


def test_splits_and_span_detection(cache):
    seed(cache, "AAPL", "splits", pd.DataFrame({"date": [dt.date(2014, 6, 9), dt.date(2020, 8, 31)], "ratio": [7.0, 4.0]}))
    s = yf.splits("AAPL")
    assert s.loc[dt.date(2020, 8, 31)] == 4.0
    assert yf.spans_split("AAPL", dt.date(2020, 1, 1), dt.date(2020, 12, 31)) == dt.date(2020, 8, 31)
    assert yf.spans_split("AAPL", dt.date(2021, 1, 1), dt.date(2021, 12, 31)) is None


def test_missing_splits_returns_empty(cache):
    seed(cache, "SPY", "splits", pd.DataFrame({"date": [], "ratio": []}))
    assert yf.splits("SPY").empty and yf.spans_split("SPY", dt.date(2020, 1, 1), dt.date(2021, 1, 1)) is None
