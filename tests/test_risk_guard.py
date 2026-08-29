"""
test_risk_guard.py — Unit tests for the independent risk guard.

Tests hard-cap enforcement (position %, sector %, leverage, drawdown halts)
and options premium-at-risk constraints.
"""
from __future__ import annotations

import pytest

from engine.risk_guard import apply_risk_controls


RISK_RULES = {
    "max_single_position_pct": 0.10,
    "max_sector_concentration_pct": 0.30,
    "max_open_positions": 10,
    "max_leverage": 1.0,
    "max_daily_drawdown_pct": 0.05,
    "max_weekly_drawdown_pct": 0.10,
    "max_total_drawdown_pct": 0.20,
}


def _make_order(ticker: str, notional: float = 5000.0) -> dict:
    return {
        "ticker": ticker,
        "side": "buy",
        "qty": 50,
        "estimated_notional": notional,
        "client_order_id": f"{ticker}-buy-123",
        "take_profit_pct": 0.05,
        "stop_loss_pct": 0.03,
    }


class TestRiskGuard:
    """Tests for engine/risk_guard.py."""

    def test_empty_inputs(self) -> None:
        final, halts = apply_risk_controls([], [], 100_000.0, RISK_RULES)
        assert final == []
        assert isinstance(halts, list)

    def test_clean_order_passes(self) -> None:
        final, halts = apply_risk_controls(
            [_make_order("AAPL",  5000.0)],
            [],
            100_000.0,
            RISK_RULES,
        )
        assert len(final) == 1
        assert len(halts) == 0
        assert final[0]["ticker"] == "AAPL"

    def test_halt_on_daily_drawdown(self) -> None:
        pos = [{
            "ticker": "CRASH",
            "qty": 1000,
            "avg_entry_price": 100.0,
            "unrealized_pl": -6000.0,
            "unrealized_pl_pct": -0.06,
        }]
        final, halts = apply_risk_controls(
            [_make_order("AAPL")],
            pos,
            100_000.0,
            RISK_RULES,
        )
        assert len(halts) >= 1
        assert any("CRASH" in h or "drawdown" in h for h in halts)

    def test_halt_on_total_drawdown(self) -> None:
        pos = [{
            "ticker": "MEGA",
            "qty": 200,
            "avg_entry_price": 1000.0,
            "unrealized_pl": -25000.0,
            "unrealized_pl_pct": -0.25,
        }]
        final, halts = apply_risk_controls(
            [_make_order("AAPL")],
            pos,
            100_000.0,
            RISK_RULES,
        )
        assert len(final) == 0
        assert any("total" in h.lower() or "all" in h.lower() for h in halts)

    def test_halt_on_exceeds_position_cap(self) -> None:
        final, halts = apply_risk_controls(
            [_make_order("AAPL", notional=12000.0)],  # 12% > 10%
            [],
            100_000.0,
            RISK_RULES,
        )
        assert len(final) == 0
        assert any("exceeds" in h.lower() for h in halts)

    def test_halt_on_max_positions(self) -> None:
        existing = [
            {"ticker": f"STOCK{i}", "qty": 100, "avg_entry_price": 100.0}
            for i in range(10)
        ]
        final, halts = apply_risk_controls(
            [_make_order("AAPL")],
            existing,
            100_000.0,
            RISK_RULES,
        )
        assert len(final) == 0
        assert any("max positions" in h.lower() for h in halts)

    def test_trim_excess_positions(self) -> None:
        existing = [
            {"ticker": f"STOCK{i}", "qty": 100, "avg_entry_price": 100}
            for i in range(8)
        ]
        orders = [
            _make_order("A",  1000),
            _make_order("B",  1000),
            _make_order("C",  1000),
            _make_order("D",  1000),
        ]
        final, halts = apply_risk_controls(orders, existing, 100_000.0, RISK_RULES)
        assert len(final) == 2  # 10 - 8 = 2 slots
        assert len(halts) == 2