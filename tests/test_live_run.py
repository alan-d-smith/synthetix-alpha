import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.live import cli, equity


class FakeClient:
    def __init__(self, frame):
        self.frame = frame

    def stock_bars(self, symbols, *a, **k):
        return self.frame


def _bars(symbols, n=300):
    idx = pd.bdate_range("2025-01-01", periods=n)
    rows = []
    for i, s in enumerate(symbols):
        rows.append(pd.DataFrame({"symbol": s, "close": [10 * (1 + (i + 1) * 0.002) ** j for j in range(n)]}, index=idx))
    return pd.concat(rows)


def test_momentum_ranks_strongest_first():
    syms = ["SLOW", "MID", "FAST"]
    r = equity.momentum(syms, FakeClient(_bars(syms)))
    assert list(r.index) == ["FAST", "MID", "SLOW"] and r["FAST"] > r["SLOW"]


def test_momentum_drops_short_history():
    assert equity.momentum(["A"], FakeClient(_bars(["A"], n=50))).empty


def test_momentum_empty_when_no_bars():
    assert equity.momentum(["A"], FakeClient(pd.DataFrame())).empty


def test_equity_order_is_market_by_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a, **k: seen.update(args=a) or {"status": "accepted"})
    cli.submit_equity("AAPL", 5, "buy", dry_run=True)
    assert "--type" in seen["args"] and "market" in seen["args"] and "--dry-run" in seen["args"]
    cli.submit_equity("AAPL", 5, "buy", limit_price=10.0, dry_run=False)
    assert "limit" in seen["args"] and "--dry-run" not in seen["args"]


def test_mleg_payload_uses_order_class_and_legs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a, **k: seen.update(args=a) or {})
    legs = [{"symbol": "X", "side": "short", "ratio": 1}, {"symbol": "Y", "side": "long", "ratio": 1}]
    cli.submit(legs, 2, -1.5, "coid-1", dry_run=True)
    assert "mleg" in seen["args"] and "--legs" in seen["args"]
    assert seen["args"][seen["args"].index("--limit-price") + 1] == "1.50"  # absolute net price


def test_cli_raises_on_error_envelope(monkeypatch):
    class R:
        stdout, stderr = '{"error": "authentication required"}', ""
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(cli, "_env", lambda: {})
    with pytest.raises(RuntimeError, match="authentication required"):
        cli.account()


def test_gap_fade_ranks_by_volatility_adjusted_gap(monkeypatch):
    import numpy as np
    import pandas as pd
    from synthetix_alpha.live import intraday
    from zoneinfo import ZoneInfo
    today = dt.datetime.now(ZoneInfo("America/New_York")).date()
    idx = [today - dt.timedelta(days=29 - i) for i in range(30)]   # newest bar is today, as live
    rng = np.random.default_rng(0)
    # A is calm, B is volatile. On the last day both gap down 2%, so in units of their own
    # volatility A's gap is the larger shock and must rank first.
    cl = pd.DataFrame({"A": 100 + rng.normal(0, 0.1, 30).cumsum(),
                       "B": 100 + rng.normal(0, 3.0, 30).cumsum(),
                       "C": 100 + rng.normal(0, 1.0, 30).cumsum()}, index=idx)
    op = cl.shift(1) * 1.001
    op.iloc[-1] = cl.iloc[-2] * 0.98
    op.iloc[0] = cl.iloc[0]
    monkeypatch.setattr(intraday, "panels", lambda *a, **k: (op, cl))
    picks = intraday.rank_today(object(), n=2)
    assert list(picks.index)[0] == "A", "the calm name's 2% gap is the bigger volatility-adjusted shock"
    assert "z" in picks.columns and picks["z"].iloc[0] < 0

    orders = intraday.plan(100_000.0, object(), n=2, budget_pct=0.4)
    assert sum(o["notional"] for o in orders) <= 100_000.0 * 0.4 + 1
    sent = []
    monkeypatch.setattr(intraday.cli, "submit_equity", lambda *a, **k: sent.append(a) or {"status": "accepted"})
    monkeypatch.setattr(intraday.cli, "run", lambda *a, **k: sent.append(a) or {"status": "accepted"})
    intraday.enter(orders[:1], dry_run=True)
    assert any("cls" in a for a in sent), "exit must be market-on-close so the sleeve never holds overnight"


def test_rank_today_needs_history_for_volatility(monkeypatch):
    import pandas as pd
    from synthetix_alpha.live import intraday
    idx = [dt.date(2026, 1, 1), dt.date(2026, 1, 2)]
    short = pd.DataFrame({"A": [100.0, 98.0]}, index=idx)
    monkeypatch.setattr(intraday, "panels", lambda *a, **k: (short, short))
    assert intraday.rank_today(object()).empty


def _crypto_panel(drop_pct, hours=24 * 9):
    """Calm and volatile pairs; the calm one slides `drop_pct` over the last 24h, spread across bars.

    Spreading the move matters: concentrating it in one bar inflates the same rolling volatility that
    divides it, so the z-score saturates instead of growing.
    """
    import numpy as np
    import pandas as pd
    end = pd.Timestamp.now(tz="America/New_York").normalize()
    idx = pd.date_range(end=end, periods=hours, freq="h", tz="America/New_York")
    rng = np.random.default_rng(0)
    calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, hours)))
    wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, hours)))
    px = pd.DataFrame({"CALM/USD": calm, "WILD/USD": wild}, index=idx)
    step = (1 + drop_pct) ** (1 / 24)
    tail = px["CALM/USD"].iloc[-25] * np.power(step, np.arange(1, 25))
    px.iloc[-24:, px.columns.get_loc("CALM/USD")] = tail
    return px


def test_crypto_signal_scales_by_each_pairs_volatility():
    from synthetix_alpha.live import crypto
    # a 6% drop is enormous for the calm pair and unremarkable for the volatile one
    z = crypto.zscore(_crypto_panel(-0.06))
    assert z["CALM/USD"] < z["WILD/USD"]
    assert crypto.signals(_crypto_panel(-0.06), threshold=3.5).index.tolist() == ["CALM/USD"]


def test_crypto_signal_silent_without_dislocation():
    from synthetix_alpha.live import crypto
    assert crypto.signals(_crypto_panel(-0.0005), threshold=3.5).empty


def test_crypto_plan_respects_budget_and_concurrency():
    from synthetix_alpha.live import crypto
    orders = crypto.plan(100_000.0, budget_pct=0.15, px=_crypto_panel(-0.06))
    assert len(orders) <= crypto.MAX_CONCURRENT
    assert sum(o["notional"] for o in orders) <= 100_000.0 * 0.15 + 1
    assert all(o["exit_after_hours"] == crypto.HOLD for o in orders)


def test_crypto_plan_empty_when_quiet():
    from synthetix_alpha.live import crypto
    assert crypto.plan(100_000.0, px=_crypto_panel(-0.0005)) == []


def test_exit_waits_for_fill_and_uses_filled_quantity(monkeypatch):
    from synthetix_alpha.live import intraday
    calls = []

    def fake_submit(symbol, qty, side, *a, **k):
        calls.append(("buy", symbol, qty))
        return {"id": f"id-{symbol}", "status": "accepted"}

    def fake_order(oid):
        return {"status": "filled", "filled_qty": "7"}   # asked for 10, got 7

    def fake_run(*args, **k):
        calls.append(("exit", args[args.index("--symbol") + 1], args[args.index("--qty") + 1]))
        return {"status": "accepted"}

    monkeypatch.setattr(intraday.cli, "submit_equity", fake_submit)
    monkeypatch.setattr(intraday.cli, "order", fake_order)
    monkeypatch.setattr(intraday.cli, "run", fake_run)
    monkeypatch.setattr(intraday.time, "sleep", lambda s: None)
    out = intraday.enter([{"symbol": "AAA", "qty": 10, "notional": 1000}], dry_run=False)
    assert [c[0] for c in calls] == ["buy", "exit"], "the buy must be submitted before the exit"
    assert calls[1][2] == "7.0", "exit quantity must be what actually filled, not what was requested"
    assert out[0]["filled_qty"] == 7.0


def test_no_exit_placed_when_buy_does_not_fill(monkeypatch):
    from synthetix_alpha.live import intraday
    sent = []
    monkeypatch.setattr(intraday.cli, "submit_equity", lambda *a, **k: {"id": "x", "status": "accepted"})
    monkeypatch.setattr(intraday.cli, "order", lambda oid: {"status": "new", "filled_qty": "0"})
    monkeypatch.setattr(intraday.cli, "cancel", lambda oid: {"status": "canceled"})
    monkeypatch.setattr(intraday.cli, "run", lambda *a, **k: sent.append(a) or {"status": "accepted"})
    monkeypatch.setattr(intraday.time, "sleep", lambda s: None)
    out = intraday.enter([{"symbol": "AAA", "qty": 10}], dry_run=False, wait_seconds=0)
    assert not any("cls" in a for a in sent), "an unfilled buy must not get a sell, or the account goes short"
    assert out[0]["exit"].startswith("no fill")


def test_partial_fill_is_cancelled_before_the_exit_is_sized(monkeypatch):
    """A partial fill must be frozen by cancelling the remainder.

    Sizing the exit to the partial quantity while the rest of the buy is still working means the remainder
    fills afterwards and is carried overnight, which this sleeve must never do.
    """
    from synthetix_alpha.live import intraday
    sent, cancelled, state = [], [], {"filled_qty": "5", "status": "partially_filled"}

    def fake_cancel(oid):
        cancelled.append(oid)
        state.update(status="canceled")      # cancelling freezes the quantity at 5
        return {"status": "canceled"}

    monkeypatch.setattr(intraday.cli, "submit_equity", lambda *a, **k: {"id": "oid1", "status": "accepted"})
    monkeypatch.setattr(intraday.cli, "order", lambda oid: dict(state))
    monkeypatch.setattr(intraday.cli, "cancel", fake_cancel)
    monkeypatch.setattr(intraday.cli, "run", lambda *a, **k: sent.append(a) or {"status": "accepted"})
    monkeypatch.setattr(intraday.time, "sleep", lambda s: None)
    out = intraday.enter([{"symbol": "AAA", "qty": 10}], dry_run=False, wait_seconds=0)
    assert cancelled == ["oid1"], "the unfilled remainder must be cancelled before the exit is sized"
    exits = [a for a in sent if "cls" in a]
    assert len(exits) == 1
    assert exits[0][exits[0].index("--qty") + 1] == "5.0"
    assert out[0]["filled_qty"] == 5.0


def test_flatten_covers_only_the_uncovered_quantity(monkeypatch):
    from synthetix_alpha.live import intraday
    sent = []
    E = "us_equity"
    monkeypatch.setattr(intraday.cli, "positions", lambda: [
        {"symbol": "AAA", "qty": "10", "asset_class": E},   # 4 already resting -> 6 uncovered
        {"symbol": "BBB", "qty": "5", "asset_class": E},    # fully covered -> nothing
        {"symbol": "CCC", "qty": "7", "asset_class": E},    # nothing resting -> all 7
        {"symbol": "DDD", "qty": "-3", "asset_class": E},   # a short is not ours to cover
        {"symbol": "ZZZ260101P00100000", "qty": "1", "asset_class": "us_option"},   # a spread's long leg
    ])
    monkeypatch.setattr(intraday.cli, "orders", lambda status="open": [
        {"symbol": "AAA", "side": "sell", "qty": "4", "filled_qty": "0"},
        {"symbol": "BBB", "side": "sell", "qty": "5", "filled_qty": "0"},
        {"symbol": "CCC", "side": "buy", "qty": "2", "filled_qty": "0"},
    ])
    monkeypatch.setattr(intraday.cli, "run", lambda *a, **k: sent.append(a) or {"status": "accepted"})
    out = {r["symbol"]: r for r in intraday.flatten(dry_run=False)}
    assert set(out) == {"AAA", "CCC"}, "an option leg must never be covered as if it were a loose long"
    assert out["AAA"]["uncovered"] == 6.0 and out["CCC"]["uncovered"] == 7.0
    assert all("cls" in a for a in sent) and len(sent) == 2


def test_flatten_is_a_noop_when_everything_is_covered(monkeypatch):
    from synthetix_alpha.live import intraday
    monkeypatch.setattr(intraday.cli, "positions",
                        lambda: [{"symbol": "AAA", "qty": "10", "asset_class": "us_equity"}])
    monkeypatch.setattr(intraday.cli, "orders", lambda status="open": [
        {"symbol": "AAA", "side": "sell", "qty": "10", "filled_qty": "0"}])
    assert intraday.flatten(dry_run=True) == []


def test_fills_panel_refuses_to_cycle_hues():
    """More underlyings than distinct hues must raise, not silently draw two series the same colour."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import pytest

    from synthetix_alpha.strategy import plots
    idx = pd.date_range("2026-01-01", periods=5)
    series = {f"S{i}": pd.Series(range(5), index=idx, dtype=float)
              for i in range(len(plots.SERIES_FILLS) + 1)}
    fig, ax = plt.subplots()
    with pytest.raises(ValueError, match="cycling"):
        plots.fills_panel(ax, series, {}, normalise=True)
    plt.close(fig)


def test_fill_marker_colours_do_not_collide_with_series_hues():
    """Outcome markers sit on top of the price lines, so their hues must not be in the series palette."""
    from synthetix_alpha.strategy import plots
    assert plots.WIN not in plots.SERIES_FILLS
    assert plots.LOSS not in plots.SERIES_FILLS


def test_screen_falls_back_to_the_snapshot_without_dolt(monkeypatch):
    """Deployment hosts have no 8GB Dolt clone, so the screen must work from the committed slice."""
    from synthetix_alpha.live import screen

    def no_dolt(*a, **k):
        raise RuntimeError("no dolt on this host")

    monkeypatch.setattr(screen, "_scan_dolt", no_dolt)
    monkeypatch.setattr(screen, "_scan_remote", no_dolt)
    out = screen.scan(limit=5)
    assert not out.empty, "the snapshot must carry the screen when Dolt is unavailable"
    assert {"iv_rv", "iv_rank"} <= set(out.columns)
    assert (out["iv_rv"] >= 1.25).all()


def test_snapshot_is_committed_and_small():
    from synthetix_alpha.live import screen
    assert screen.SNAPSHOT.exists(), "the fallback snapshot must ship with the repo"
    assert screen.SNAPSHOT.stat().st_size < 2_000_000, "keep the committed slice small"


def test_screen_prefers_the_remote_api_over_the_static_snapshot(monkeypatch):
    """Order matters: the snapshot ages a day per session, the API does not."""
    import pandas as pd

    from synthetix_alpha.live import screen
    calls = []

    def fail(name):
        def f(*a, **k):
            calls.append(name)
            raise RuntimeError(name)
        return f

    def ok(name):
        def f(*a, **k):
            calls.append(name)
            return pd.DataFrame({"symbol": ["AAA"], "date": ["2026-08-28"], "iv": [0.5],
                                 "hv": [0.25], "iv_rv": [2.0], "iv_rank": [0.9]})
        return f

    monkeypatch.setattr(screen, "_scan_dolt", fail("dolt"))
    monkeypatch.setattr(screen, "_scan_remote", ok("remote"))
    monkeypatch.setattr(screen, "_scan_snapshot", ok("snapshot"))
    out = screen.scan(limit=3)
    assert calls == ["dolt", "remote"], "the snapshot must not be reached while the API answers"
    assert list(out.index) == ["AAA"]


def test_remote_query_coerces_numeric_columns(monkeypatch):
    """The DoltHub API returns every value as a string; comparisons would silently fail on those."""
    from synthetix_alpha.data import dolt

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"query_execution_status": "Success",
                    "rows": [{"symbol": "AAA", "iv_rv": "1.98", "iv_rank": "0.25"}]}

    monkeypatch.setattr(dolt, "query_remote", dolt.query_remote)
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    df = dolt.query_remote("SELECT 1")
    assert df["iv_rv"].dtype.kind == "f" and df["iv_rank"].dtype.kind == "f"
    assert df["symbol"].iloc[0] == "AAA"


def test_liquidate_never_touches_an_option_leg(monkeypatch):
    """A vertical's long leg is not a loose long. Selling it alone leaves the short leg naked."""
    from synthetix_alpha.live import intraday
    sold = []
    monkeypatch.setattr(intraday.cli, "positions", lambda: [
        {"symbol": "SRE", "qty": "75", "asset_class": "us_equity", "market_value": "6000"},
        {"symbol": "VLO261016P00300000", "qty": "1", "asset_class": "us_option", "market_value": "250"},
        {"symbol": "VLO261016P00320000", "qty": "-1", "asset_class": "us_option", "market_value": "-670"},
    ])
    monkeypatch.setattr(intraday.cli, "orders", lambda status="open": [])
    monkeypatch.setattr(intraday.cli, "run", lambda *a, **k: {"status": "accepted"})
    monkeypatch.setattr(intraday, "_market_exit",
                        lambda sym, qty, *, dry_run: sold.append((sym, qty)) or {"status": "accepted"})
    out = intraday.liquidate(dry_run=False)
    assert [r["symbol"] for r in out] == ["SRE"]
    assert sold == [("SRE", 75.0)]


def test_liquidate_cancels_the_resting_close_order_first(monkeypatch):
    """A resting sell in the same name is rejected as a wash trade against our own exit."""
    from synthetix_alpha.live import intraday
    cancelled, sold = [], []
    monkeypatch.setattr(intraday.cli, "positions", lambda: [
        {"symbol": "SRE", "qty": "75", "asset_class": "us_equity", "market_value": "6000"}])
    monkeypatch.setattr(intraday.cli, "orders", lambda status="open": [
        {"id": "abc", "symbol": "SRE", "side": "sell", "qty": "75", "filled_qty": "0"}])
    monkeypatch.setattr(intraday.cli, "cancel", lambda oid: cancelled.append(oid) or {"status": "canceled"})
    monkeypatch.setattr(intraday, "_market_exit",
                        lambda sym, qty, *, dry_run: sold.append((sym, qty)) or {"status": "accepted"})
    intraday.liquidate(dry_run=False)
    assert cancelled == ["abc"], "the resting market-on-close order has to come off before the real exit"
    assert sold == [("SRE", 75.0)]
