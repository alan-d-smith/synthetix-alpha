"""The WRDS client's job is mostly to work around the API's quirks, so that is what is tested."""
import pandas as pd
import pytest

from synthetix_alpha.data import wrds


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    """Serves a canned sequence of pages and records what was asked for."""

    def __init__(self, pages, options=None):
        self.pages, self.options_payload, self.calls = list(pages), options or {}, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self.pages.pop(0))

    def options(self, url):
        return FakeResponse(self.options_payload)


def _patch(monkeypatch, client):
    monkeypatch.setenv("WRDS", "tok")
    monkeypatch.setattr(wrds.httpx, "Client", lambda **kw: client)


def test_get_follows_pagination_and_stops_at_the_last_page(monkeypatch):
    c = FakeClient([{"results": [{"date": "2024-01-02", "x": 1}], "next": "PAGE2"},
                    {"results": [{"date": "2024-01-03", "x": 2}], "next": None}])
    _patch(monkeypatch, c)
    df = wrds.get("crsp.dsf")
    assert list(df["x"]) == [1, 2]
    assert c.calls[1][0] == "PAGE2", "the next link is followed verbatim"
    assert c.calls[1][1] is None, "params must not be resent with the next link, which already carries them"


def test_get_ignores_the_count_field_entirely(monkeypatch):
    """The API reports a stale count that survives across unrelated queries; only rows are real."""
    c = FakeClient([{"count": 4411, "results": [], "next": None}])
    _patch(monkeypatch, c)
    assert wrds.get("crsp.dsf", date="2025-03-31").empty


def test_get_parses_dates(monkeypatch):
    c = FakeClient([{"results": [{"date": "2024-06-28"}], "next": None}])
    _patch(monkeypatch, c)
    assert wrds.get("crsp.dsf")["date"].iloc[0].isoformat() == "2024-06-28"


def test_fields_reports_which_columns_can_be_filtered(monkeypatch):
    """Unregistered filters are dropped silently, so knowing which bind is the difference between a
    filtered query and a full table scan that looks like it worked."""
    c = FakeClient([], options={"fields": {"date": {"filter_field": True, "type": "date"},
                                           "days": {"filter_field": False, "type": "float"},
                                           "secid": {"filter_field": True, "type": "float"}}})
    _patch(monkeypatch, c)
    f = wrds.fields("optionm.stdopd2024")
    assert set(f[f["filterable"]]["column"]) == {"date", "secid"}
    assert set(f[~f["filterable"]]["column"]) == {"days"}


def test_atm_iv_filters_maturity_and_side_client_side(monkeypatch):
    """days and cp_flag are not filterable server-side, so the module must not trust the response."""
    rows = [{"date": "2024-01-02", "days": 10.0, "cp_flag": "P", "impl_volatility": 0.9,
             "premium": 1.0, "vega": 1.0, "strike_price": 1.0},
            {"date": "2024-01-02", "days": 30.0, "cp_flag": "C", "impl_volatility": 0.5,
             "premium": 1.0, "vega": 1.0, "strike_price": 1.0},
            {"date": "2024-01-02", "days": 30.0, "cp_flag": "P", "impl_volatility": 0.26,
             "premium": 1.0, "vega": 1.0, "strike_price": 1.0}]
    c = FakeClient([{"results": rows, "next": None}])
    _patch(monkeypatch, c)
    out = wrds.atm_iv(107525, 2024, days=30, cp="P")
    assert len(out) == 1 and out["iv"].iloc[0] == pytest.approx(0.26)


def test_secids_prefers_the_most_recent_mapping(monkeypatch):
    """Tickers get reused: SPY maps to a defunct issuer as well as the SPDR trust."""
    c = FakeClient([{"results": [{"secid": 7571, "effect_date": "1996-01-02"},
                                 {"secid": 109820, "effect_date": "2005-01-03"}], "next": None}])
    _patch(monkeypatch, c)
    assert wrds.secids(["SPY"]) == {"SPY": 109820}


def test_token_is_required(monkeypatch):
    monkeypatch.delenv("WRDS", raising=False)
    with pytest.raises(RuntimeError, match="WRDS"):
        wrds.token()
