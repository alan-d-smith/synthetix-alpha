"""
test_integration.py — End-to-end pipeline smoke test.

Tests the full 7-stage flow from universe through dry-run order preview
without hitting any live APIs.
"""
from __future__ import annotations

import pytest


class TestPipelineIntegration:
    """Smoke tests for the full 7-stage pipeline."""

    def test_stage_order_imports(self) -> None:
        """All 7 pipeline stages must be importable."""
        # Stage 1: configs (not code, but loaded from YAML)
        # Stage 2: quant screener
        from engine.quant_screener import screen_universe

        # Stage 3: research agent
        from agents.research_agent import research_tickers

        # Stage 4: critic
        from engine.critic import validate_signals

        # Stage 5: sizing
        from engine.sizing import compute_sizes

        # Stage 6: risk guard
        from engine.risk_guard import apply_risk_controls

        # Stage 7: execution
        from execution.alpaca_client import preview_order, submit_bracket_order
        from execution.alpaca_client import monitor_positions

        # All must be callable
        assert callable(screen_universe)
        assert callable(research_tickers)
        assert callable(validate_signals)
        assert callable(compute_sizes)
        assert callable(apply_risk_controls)
        assert callable(preview_order)
        assert callable(submit_bracket_order)
        assert callable(monitor_positions)

    def test_pydantic_schema_models(self) -> None:
        """All Pydantic model classes must be importable and instantiable."""
        from utils.schemas import (
            QuantSignal,
            ResearchOutput,
            BracketOrder,
            Position,
            GovernanceRules,
        )

        # Test QuantSignal
        qs = QuantSignal(ticker="AAPL", vwap_deviation=0.02, rvol=2.5, rsi=32.0)
        assert qs.ticker == "AAPL"

        # Test ResearchOutput
        ro = ResearchOutput(
            ticker="AAPL",
            sentiment="bullish",
            confidence_score=0.82,
            thesis="Strong growth",
            macro_alignment="aligned",
        )
        assert ro.confidence_score == 0.82

        # Test BracketOrder
        bo = BracketOrder(
            ticker="AAPL",
            side="buy",
            qty=100,
            take_profit_pct=0.05,
            stop_loss_pct=0.03,
            estimated_notional=18000.0,
            client_order_id="sx-test123",
            confidence_score=0.80,
        )
        assert bo.qty == 100

        # Test GovernanceRules defaults
        gr = GovernanceRules()
        assert gr.max_leverage == 1.0
        assert gr.max_single_position_pct == 0.10

    def test_no_forbidden_imports(self) -> None:
        """Must never import gs_quant.session, GsSession, or gs_quant.markets."""
        forbidden = ["gs_quant.session", "GsSession", "gs_quant.markets"]

        import engine.quant_screener as qs

        source_path = qs.__file__ or ""
        with open(source_path, "r") as f:
            code = f.read()
        for term in forbidden:
            assert term not in code, f"Forbidden import '{term}' found in quant_screener.py"