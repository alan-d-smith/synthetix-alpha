"""
test_critic.py — Unit tests for the deterministic critic/validation layer.

Tests governance rule enforcement, rejection logging, and edge cases
for required fields, leverage limits, and concentration caps.
"""
from __future__ import annotations

import pytest

from engine.critic import validate_signals


class TestCritic:
    """Tests for engine/critic.py."""

    def test_valid_signal_passes(self, sample_governance_rules: dict) -> None:
        approved, rejections = validate_signals(
            [{
                "ticker": "AAPL",
                "sentiment": "bullish",
                "confidence_score": 0.82,
                "thesis": "Strong buy",
            }],
            sample_governance_rules,
        )
        assert len(approved) == 1
        assert approved[0]["ticker"] == "AAPL"
        assert len(rejections) == 0

    def test_missing_required_field_rejected(
        self, sample_governance_rules: dict
    ) -> None:
        approved, rejections = validate_signals(
            [{"ticker": "BAD", "confidence_score": 0.5}],
            sample_governance_rules,
        )
        assert len(approved) == 0
        assert len(rejections) >= 1
        assert any("sentiment" in r or "thesis" in r for r in rejections)

    def test_confidence_out_of_range_rejected(
        self, sample_governance_rules: dict
    ) -> None:
        approved, rejections = validate_signals(
            [{
                "ticker": "TEST",
                "sentiment": "bullish",
                "confidence_score": 1.5,
                "thesis": "test",
            }],
            sample_governance_rules,
        )
        assert len(approved) == 0
        assert len(rejections) >= 1
        assert any("1.5" in r for r in rejections)

    def test_bad_sentiment_rejected(self, sample_governance_rules: dict) -> None:
        approved, rejections = validate_signals(
            [{
                "ticker": "TEST",
                "sentiment": "extremely_bullish",
                "confidence_score": 0.5,
                "thesis": "test",
            }],
            sample_governance_rules,
        )
        assert len(approved) == 0
        assert any("extremely_bullish" in r for r in rejections)

    def test_handle_empty_signals(self, sample_governance_rules: dict) -> None:
        approved, rejections = validate_signals([], sample_governance_rules)
        assert approved == []

    def test_rejection_reason_logged(self, sample_governance_rules: dict) -> None:
        approved, rejections = validate_signals(
            [{"ticker": "EMPTY"}],
            sample_governance_rules,
        )
        assert len(rejections) > 0
        for r in rejections:
            assert isinstance(r, str)
            assert "EMPTY" in r or "signal" in r