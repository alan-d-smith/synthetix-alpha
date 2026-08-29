"""
test_sizing.py — Unit tests for confidence-scaled position sizing.

Tests qty computation, hard-cap enforcement, and bracket order output
structure (take_profit, stop_loss, time_stop).
"""
from __future__ import annotations

import pytest

from engine.sizing import compute_sizes


GOVERNANCE = {
    "max_single_position_pct": 0.10,
    "max_leverage": 1.0,
}


class TestSizing:
    """Tests for engine/sizing.py."""

    def test_returns_list(self) -> None:
        results = compute_sizes([], 100_000.0, GOVERNANCE)
        assert isinstance(results, list)
        assert results == []

    def test_high_confidence_near_max_allocation(self) -> None:
        results = compute_sizes(
            [{"ticker": "AAPL", "sentiment": "bullish", "confidence_score": 0.95}],
            100_000.0,
            GOVERNANCE,
        )
        assert len(results) == 1
        order = results[0]
        assert order["estimated_notional"] == pytest.approx(9500.0, abs=10)
        assert order["qty"] >= 1

    def test_never_uncapped_scaling(self) -> None:
        results = compute_sizes(
            [{"ticker": "AAPL", "sentiment": "bullish", "confidence_score": 0.999}],
            100_000.0,
            GOVERNANCE,
        )
        max_allowed = 100_000.0 * GOVERNANCE["max_single_position_pct"]
        for order in results:
            assert order["estimated_notional"] <= max_allowed

    def test_low_confidence_floor(self) -> None:
        results = compute_sizes(
            [{"ticker": "AAPL", "sentiment": "neutral", "confidence_score": 0.001}],
            100_000.0,
            GOVERNANCE,
        )
        assert len(results) == 1
        assert results[0]["estimated_notional"] >= 1000.0  # 1% floor

    def test_bracket_order_keys_present(self) -> None:
        results = compute_sizes(
            [{"ticker": "AAPL", "sentiment": "bullish", "confidence_score": 0.7}],
            100_000.0,
            GOVERNANCE,
        )
        required = {
            "ticker", "side", "qty", "take_profit_pct", "stop_loss_pct",
            "time_stop_min", "estimated_notional", "client_order_id",
            "confidence_score",
        }
        for order in results:
            missing = required - set(order.keys())
            assert not missing, f"Missing keys: {missing}"

    def test_bearish_gets_sell_side(self) -> None:
        results = compute_sizes(
            [{"ticker": "AAPL", "sentiment": "bearish", "confidence_score": 0.6}],
            100_000.0,
            GOVERNANCE,
        )
        assert results[0]["side"] == "sell"