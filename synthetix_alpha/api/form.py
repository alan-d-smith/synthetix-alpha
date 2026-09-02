"""Reuse the pipeline FORM stage for the dashboard adapter."""

from __future__ import annotations

from typing import Any


def filter_approved_decisions(
    decisions: list[Any],
    *,
    confidence_threshold: int = 70,
) -> list[Any]:
    """Match orchestrator approval semantics for order formation."""
    return [
        decision
        for decision in decisions
        if decision.decision == "APPROVED" and decision.confidence >= confidence_threshold
    ]


def run_form(
    approved: list[Any],
    screen_df: object,
    *,
    orchestrator: object | None = None,
) -> list[dict]:
    """Convert critic-approved decisions into formed order dicts (read-only)."""
    import pandas as pd

    if not approved:
        return []
    if screen_df is None or not isinstance(screen_df, pd.DataFrame) or screen_df.empty:
        return []

    if orchestrator is None:
        from synthetix_alpha.pipeline.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator(mock_llm=True)

    return orchestrator._form_orders(approved, screen_df)
