import datetime as dt

from synthetix_alpha.live import window as w


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=w.ET)


def test_entry_is_an_opening_trade_only():
    assert not w.can_enter(at(2026, 9, 8, 9, 30))[0], "09:30 is the open; we deliberately wait until 09:31"
    assert w.can_enter(at(2026, 9, 8, 9, 31))[0]
    assert w.can_enter(at(2026, 9, 8, 10, 30))[0]
    assert not w.can_enter(at(2026, 9, 8, 10, 31))[0], "a late run must not put the book on at the wrong price"


def test_flatten_window_respects_the_market_on_close_cutoff():
    assert not w.can_flatten(at(2026, 9, 8, 15, 29))[0]
    assert w.can_flatten(at(2026, 9, 8, 15, 45))[0]
    assert w.can_flatten(at(2026, 9, 8, 15, 56))[0], "a market order still fills at 15:56"
    assert not w.can_flatten(at(2026, 9, 8, 15, 59))[0], "too close to the bell to trust a fill"


def test_the_windows_outlive_the_competition():
    """The bracket that ended trading at the 4 Sep 2026 snapshot is gone: the books keep running."""
    assert w.can_enter(at(2026, 9, 4, 9, 31))[0], "the Friday after the snapshot is an ordinary session now"
    assert w.can_enter(at(2027, 3, 1, 9, 31))[0]
    assert w.can_flatten(at(2027, 3, 1, 15, 50))[0]


def test_weekends_are_refused():
    assert not w.can_enter(at(2026, 9, 5, 10, 0))[0]
    assert not w.can_flatten(at(2026, 9, 6, 15, 45))[0]


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
    """Each book gets its own runner arguments, so they must not be shared or swapped."""
    from synthetix_alpha.live import schedule as sc
    by_account = {a: extra for _, a, extra in sc.BOOKS}
    for acct, extra in by_account.items():
        assert "--index-long" not in extra, "the books run the gap fade, not the index long"
        n = extra[extra.index("--intraday-top") + 1]
        assert int(n) > 0, f"{acct} must actually trade"
        budget = float(extra[extra.index("--intraday-budget") + 1])
        assert 0 < budget <= 1.5, f"{acct} budget {budget} is outside the sane range"
        gate = extra[extra.index("--vol-gate") + 1] if "--vol-gate" in extra else "0"
        assert gate == "0", f"{acct} must not stand aside on the vol gate"


def test_run_action_builds_a_command_without_crashing(monkeypatch):
    """A NameError in run_action is invisible until the market opens: the scheduler records the failure in
    the state file, marks the action done, and never retries."""
    from synthetix_alpha.live import schedule as sc
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "ok", ""

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return Done()
    monkeypatch.setattr(sc.subprocess, "run", fake)
    for _, account, extra in sc.BOOKS:
        for action in ("enter", "topup", "flatten"):
            out = sc.run_action(action, account, extra, execute=False)
            assert out["rc"] == 0 and "error" not in out
    assert "--account" in seen["cmd"]
