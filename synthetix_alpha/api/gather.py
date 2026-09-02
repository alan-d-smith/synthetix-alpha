"""Reuse the pipeline GATHER stage for the dashboard adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable


def critic_input_to_candidate_fields(inp: Any) -> dict[str, Any]:
    """Map a pipeline CriticInput into frontend Candidate context fields."""
    return {
        "company": inp.company_name or "",
        "sector": inp.sector or "",
        "headlines": list(inp.recent_headlines or []),
        "analystConsensus": inp.analyst_consensus,
        "insiderMspr": inp.insider_mspr,
    }


def run_gather(
    screen_df: object,
    *,
    orchestrator: object | None = None,
) -> tuple[list[Any], list[str]]:
    """Run orchestrator GATHER helpers against a screened candidate DataFrame."""
    import pandas as pd

    if screen_df is None or not isinstance(screen_df, pd.DataFrame) or screen_df.empty:
        return [], []

    result = SimpleNamespace(candidates=screen_df, errors=[])
    tickers = [str(t) for t in screen_df.index]

    if orchestrator is None:
        from synthetix_alpha.pipeline.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator(mock_llm=True)

    macro = orchestrator._gather_macro(result)
    inputs = orchestrator._gather_per_ticker(result, tickers, macro) or []
    return inputs, list(result.errors)
