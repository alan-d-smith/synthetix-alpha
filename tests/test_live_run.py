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
