"""The LSE feed cannot be trusted as returned, so these tests are mostly about what must be rejected.

Measured on 2026-09-02: 61% of an AAPL chain had already expired, the server's `dte` was wrong on 1,641 of
2,323 rows, and asking for `max_dte=30` still returned 1,408 expired contracts because the server filters on
that same broken field. Selecting one of those to trade would mean submitting an order for a contract that
stopped existing two months earlier.
"""
import datetime as dt

import pytest

from synthetix_alpha.data import lse

TODAY = dt.date(2026, 9, 2)


def row(ticker, iv=0.25, delta=-0.3, traded="2026-09-02T18:00:00", expiry=None, **kw):
    out = {"ticker": ticker, "iv": iv, "delta": delta, "last_trade_at": traded,
           "expiry": expiry if expiry is not None else (lse.osi_expiry(ticker) or dt.date(2026, 1, 1)).isoformat()}
    out.update(kw)
    return out


def test_osi_expiry_decodes_the_symbol():
    assert lse.osi_expiry("AAPL260702P00110000") == dt.date(2026, 7, 2)
    assert lse.osi_expiry("SPY261016C00500000") == dt.date(2026, 10, 16)
    assert lse.osi_expiry("BRK.B261016P00300000") == dt.date(2026, 10, 16)


def test_osi_expiry_refuses_rubbish():
    for bad in ("", None, "NOTASYMBOL", "AAPL2607", "AAPL269902P00110000"):
        assert lse.osi_expiry(bad) is None


def test_expired_contracts_are_dropped():
    """The headline failure: a contract that expired 62 days ago must never survive."""
    rows = [row("AAPL260702P00110000"),          # expired 2026-07-02
            row("AAPL261016P00300000")]          # live
    out = lse.live_contracts(rows, asof=TODAY)
    assert [r["ticker"] for r in out] == ["AAPL261016P00300000"]


def test_the_servers_dte_field_is_ignored_entirely():
    """The API reported dte=1 for a contract 62 days expired. Trusting it selects a dead contract."""
    r = row("AAPL260702P00110000")
    r["dte"] = 1                                  # exactly what the live API returns
    assert lse.live_contracts([r], asof=TODAY, max_dte=30) == []


def test_dte_is_recomputed_from_the_expiry():
    out = lse.live_contracts([row("AAPL261016P00300000")], asof=TODAY)
    assert out[0]["dte"] == (dt.date(2026, 10, 16) - TODAY).days == 44


def test_a_ticker_that_disagrees_with_its_expiry_column_is_dropped():
    """If the symbol and the column disagree, one of them is wrong and neither can be trusted."""
    assert lse.live_contracts([row("AAPL261016P00300000", expiry="2026-11-20")], asof=TODAY) == []


def test_min_and_max_dte_bracket_the_selection():
    rows = [row("AAPL260904P00300000"),   # 2 days out
            row("AAPL261016P00300000"),   # 44 days
            row("AAPL270115P00300000")]   # 135 days
    got = [r["ticker"] for r in lse.live_contracts(rows, asof=TODAY, min_dte=40, max_dte=90)]
    assert got == ["AAPL261016P00300000"]


def test_absurd_implied_volatility_is_rejected():
    """iv 3.31 (331%) is what an untraded or expired contract looks like, not a real quote."""
    assert lse.live_contracts([row("AAPL261016P00300000", iv=3.31)], asof=TODAY) == []
    assert lse.live_contracts([row("AAPL261016P00300000", iv=0)], asof=TODAY) == []
    assert lse.live_contracts([row("AAPL261016P00300000", iv=None)], asof=TODAY) == []


def test_stale_quotes_are_rejected():
    fresh = row("AAPL261016P00300000", traded="2026-09-01T18:00:00")
    stale = row("AAPL261016P00300000", traded="2026-06-11T17:29:23")
    assert len(lse.live_contracts([fresh], asof=TODAY)) == 1
    assert lse.live_contracts([stale], asof=TODAY) == []


def test_missing_greeks_are_rejected_when_required():
    r = row("AAPL261016P00300000", delta=None)
    assert lse.live_contracts([r], asof=TODAY) == []
    assert len(lse.live_contracts([r], asof=TODAY, require_greeks=False)) == 1


def test_chain_never_calls_the_broken_server_side_filter():
    """max_dte must not be forwarded: the server computes it from the field we know is wrong."""
    seen = {}

    class Fake:
        def options(self, underlying, **kw):
            seen.update(kw)
            return [row("AAPL260702P00110000")] if kw.get("expiry") != "2026-10-16"                 else [row("AAPL260702P00110000"), row("AAPL261016P00300000")]

    out = lse.chain("AAPL", "put", min_dte=40, max_dte=90, client=Fake(), asof=TODAY)
    assert "max_dte" not in seen and "min_dte" not in seen, "server-side dte filtering must never be used"
    assert seen.get("expiry"), "the expiry is pinned explicitly instead"
    assert [r["ticker"] for r in out] == ["AAPL261016P00300000"], "the expired row is still dropped"


def test_a_chain_of_only_expired_contracts_yields_nothing_rather_than_something_wrong():
    class Fake:
        def options(self, underlying, **kw):
            return [row("AAPL260702P00110000"), row("AAPL260706P00120000")]

    assert lse.chain("AAPL", "put", client=Fake(), asof=TODAY) == []


def test_monthly_expiries_are_third_fridays():
    got = lse.monthly_expiries(dt.date(2026, 10, 1), dt.date(2026, 12, 31))
    assert got == [dt.date(2026, 10, 16), dt.date(2026, 11, 20), dt.date(2026, 12, 18)]
    for d in got:
        assert d.weekday() == 4 and 15 <= d.day <= 21, "third Friday of its month"


def test_chain_queries_each_expiry_rather_than_pulling_in_bulk():
    """A bulk pull is exhausted by expired contracts before reaching a live one: on 2026-09-02 an
    unfiltered SPY request returned 5,000 rows, every one already dead."""
    asked = []

    class Fake:
        def options(self, underlying, **kw):
            asked.append(kw.get("expiry"))
            if kw.get("expiry") == "2026-10-16":
                return [row("SPY261016P00300000")]
            return []

    out = lse.chain("SPY", "put", min_dte=40, max_dte=90, client=Fake(), asof=TODAY)
    assert asked == ["2026-10-16", "2026-11-20"], "each expiry in the window is requested explicitly"
    assert [r["ticker"] for r in out] == ["SPY261016P00300000"]


def test_one_failing_expiry_does_not_lose_the_rest_of_the_chain():
    class Flaky:
        def options(self, underlying, **kw):
            if kw.get("expiry") == "2026-10-16":
                raise RuntimeError("upstream blew up")
            return [row("SPY261120P00300000")]

    out = lse.chain("SPY", "put", min_dte=40, max_dte=90, client=Flaky(), asof=TODAY)
    assert [r["ticker"] for r in out] == ["SPY261120P00300000"]


def test_chain_returns_empty_rather_than_raising_when_everything_fails():
    class Dead:
        def options(self, underlying, **kw):
            raise RuntimeError("network down")

    assert lse.chain("SPY", "put", client=Dead(), asof=TODAY) == []
