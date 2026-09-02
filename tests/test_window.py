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
    assert w.can_flatten(at(2026, 8, 31, 15, 56))[0], "a market order still fills at 15:56"
    assert not w.can_flatten(at(2026, 8, 31, 15, 59))[0], "too close to the bell to trust a fill"


def test_nothing_trades_after_equity_is_measured():
    """Equity is snapshotted at 09:30 Friday, so Friday cannot help and must not be traded."""
    assert w.can_enter(at(2026, 9, 3, 9, 45))[0], "Thursday is the last session that counts"
    assert not w.can_enter(at(2026, 9, 4, 9, 45))[0]
    assert not w.can_flatten(at(2026, 9, 4, 15, 45))[0]


def test_the_whole_final_session_is_tradeable():
    """The failure that matters is stopping early on Thursday, not running late."""
    assert w.can_enter(at(2026, 9, 3, 9, 31))[0], "Thursday's entry must not be cut off"
    assert w.can_flatten(at(2026, 9, 3, 15, 50))[0], "Thursday's first flatten pass"
    assert w.can_flatten(at(2026, 9, 3, 15, 56))[0], "Thursday's second flatten pass"
    assert w.LAST_CLOSE < w.CLOSES, "the guard has to outlive the last close it is protecting"


def test_friday_pre_open_is_supervised_but_untradeable():
    """The guard stays open across the final overnight; the sub-windows are what keep Friday shut."""
    assert w._within(at(2026, 9, 4, 8, 0))[0], "still inside the window, so a crash there is still watched"
    assert not w.can_enter(at(2026, 9, 4, 8, 0))[0]
    assert not w.can_enter(at(2026, 9, 4, 9, 31))[0], "the snapshot lands at 09:30, before entry could ever open"
    assert not w.can_flatten(at(2026, 9, 4, 8, 0))[0]


def test_weekends_inside_the_window_are_refused():
    assert not w.can_enter(at(2026, 9, 5, 10, 0))[0]


def test_scheduler_fires_each_action_once_per_day(tmp_path, monkeypatch):
    from synthetix_alpha.live import schedule as sc
    monkeypatch.setattr(sc, "STATE", tmp_path / "state.json")
    t = at(2026, 8, 31, 9, 31)
    first = sc.due(t)
    assert sorted(a[1] for a in first) == ["deployed", "research"]
    for _, account, _, name in first:
        sc._mark(f"{t.date().isoformat()}:{name}:{account}", {"state": "done"})
    assert sc.due(t) == [], "an action already recorded must not run again after a restart"
    assert len(sc.due(at(2026, 9, 1, 9, 31))) == 2, "the next session starts fresh"


def test_both_flatten_passes_are_scheduled_on_the_final_session(tmp_path, monkeypatch):
    """Thursday has no session after it, so a missed cover cannot be repaired the next morning."""
    from synthetix_alpha.live import schedule as sc
    monkeypatch.setattr(sc, "STATE", tmp_path / "state.json")
    t = at(2026, 9, 3, 15, 56)
    passes = [(a[1], a[3]) for a in sc.due(t) if a[0] == "flatten"]
    assert sorted(passes) == [("deployed", "flatten0"), ("deployed", "flatten1"),
                              ("research", "flatten0"), ("research", "flatten1")]
    sc._mark("2026-09-03:flatten0:research", {"state": "done"})
    remaining = [(a[1], a[3]) for a in sc.due(t) if a[0] == "flatten"]
    assert ("research", "flatten1") in remaining, "the second pass still runs when the first already has"
    assert ("research", "flatten0") not in remaining


def test_scheduler_runs_both_books_on_separate_accounts():
    """Two accounts, never the same one twice: a mix-up would double the size on one book and leave
    the other idle."""
    from synthetix_alpha.live import schedule as sc
    accounts = [a for _, a, _ in sc.BOOKS]
    assert sorted(accounts) == ["deployed", "research"]
    assert len(set(accounts)) == len(accounts), "each account must appear exactly once"
    for _, _, extra in sc.BOOKS:
        assert extra, "every book needs its own runner arguments"
        assert len(extra) % 2 == 0, "runner arguments come in flag/value pairs"


def test_scheduler_passes_each_book_its_own_strategy():
    """The books deliberately run different strategies, so the arguments must not be shared or swapped."""
    from synthetix_alpha.live import schedule as sc
    by_account = {a: extra for _, a, extra in sc.BOOKS}
    assert "--index-long" in by_account["research"], "research runs the levered index long"
    assert "--index-long" not in by_account["deployed"], "deployed runs the gap fade, not the index"
    assert "--intraday-budget" in by_account["deployed"]
