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
    idx = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
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


def _crypto_panel(drop_pct):
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-08-01", periods=24 * 9, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, len(idx))))
    wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(idx))))
    px = pd.DataFrame({"CALM/USD": calm, "WILD/USD": wild}, index=idx)
    px.iloc[-1, px.columns.get_loc("CALM/USD")] = px.iloc[-25]["CALM/USD"] * (1 + drop_pct)
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
