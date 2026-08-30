import datetime as dt

from synthetix_alpha.live import window as w


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=w.ET)


def test_nothing_trades_before_the_window_opens():
    assert not w.can_enter(at(2026, 8, 31, 9, 30))[0], "09:30 is the open; we deliberately wait until 09:31"
    assert not w.can_enter(at(2026, 8, 30, 12, 0))[0], "the Sunday before must be refused"
    assert not w.can_flatten(at(2026, 8, 31, 9, 30))[0]


def test_entry_opens_at_0931_on_the_first_session():
    ok, why = w.can_enter(at(2026, 8, 31, 9, 31))
    assert ok, why


def test_entry_is_an_opening_trade_only():
    assert w.can_enter(at(2026, 8, 31, 10, 30))[0]
    assert not w.can_enter(at(2026, 8, 31, 10, 31))[0], "a late run must not put the book on at the wrong price"


def test_flatten_window_respects_the_market_on_close_cutoff():
    assert not w.can_flatten(at(2026, 8, 31, 15, 29))[0]
    assert w.can_flatten(at(2026, 8, 31, 15, 45))[0]
    assert not w.can_flatten(at(2026, 8, 31, 15, 56))[0], "market-on-close orders stop being accepted at 15:50"


def test_nothing_trades_after_equity_is_measured():
    """Equity is read at Thursday's close, so Friday cannot help and must not be traded."""
    assert w.can_enter(at(2026, 9, 3, 9, 45))[0], "Thursday is the last session that counts"
    assert not w.can_enter(at(2026, 9, 4, 9, 45))[0]
    assert not w.can_flatten(at(2026, 9, 4, 15, 45))[0]


def test_weekends_inside_the_window_are_refused():
    assert not w.can_enter(at(2026, 9, 5, 10, 0))[0]


def test_scheduler_fires_each_action_once_per_day(tmp_path, monkeypatch):
    from synthetix_alpha.live import schedule as sc
    monkeypatch.setattr(sc, "STATE", tmp_path / "state.json")
    t = at(2026, 8, 31, 9, 31)
    first = sc.due(t)
    assert sorted(a[1] for a in first) == ["deployed", "research"]
    for action, account, _ in first:
        sc._mark(f"{t.date().isoformat()}:{action}:{account}", {"state": "done"})
    assert sc.due(t) == [], "an action already recorded must not run again after a restart"
    assert len(sc.due(at(2026, 9, 1, 9, 31))) == 2, "the next session starts fresh"


def test_scheduler_runs_both_books_on_separate_accounts():
    from synthetix_alpha.live import schedule as sc
    accounts = {a for _, a, _ in sc.BOOKS}
    baskets = {b for _, _, b in sc.BOOKS}
    assert accounts == {"research", "deployed"}
    assert baskets == {10, 20}, "n=10 on research, n=20 on deployed"
