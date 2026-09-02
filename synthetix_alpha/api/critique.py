"""Reuse the pipeline CRITIQUE stage for the dashboard adapter."""

from __future__ import annotations

from typing import Any


def mock_critic_for_ticker(ticker: str) -> dict[str, Any]:
    """Honest frontend critic placeholder when the LLM is in mock mode."""
    return {
        "ticker": ticker,
        "decision": "PENDING",
        "confidence": 0,
        "regimeSummary": "",
        "thesis": "Mock LLM output — critic has not evaluated this setup with a live model.",
        "riskFactors": [],
        "suggestedSizeMultiplier": 1.0,
    }


def critic_decision_to_frontend(decision: Any) -> dict[str, Any]:
    """Map a pipeline CriticDecision into frontend Candidate.critic fields."""
    return {
        "ticker": decision.ticker,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "regimeSummary": decision.regime_summary,
        "thesis": decision.thesis,
        "riskFactors": list(decision.risk_factors),
        "suggestedSizeMultiplier": decision.suggested_size_multiplier,
    }


def enrich_candidates_with_mock_critique(
    candidates: list[dict[str, Any]],
    inputs: list[Any],
) -> list[dict[str, Any]]:
    """Mark gathered candidates as critique-pending when only mock LLM output is available."""
    tickers = {str(inp.ticker).upper() for inp in inputs}
    enriched: list[dict[str, Any]] = []
    for cand in candidates:
        merged = dict(cand)
        if str(cand["ticker"]).upper() in tickers:
            merged["critic"] = mock_critic_for_ticker(str(cand["ticker"]))
        enriched.append(merged)
    return enriched


def critic_uses_mock(orchestrator: object) -> bool:
    """Return True when the critic LLM client is in mock mode."""
    llm = orchestrator._critic._llm
    return bool(getattr(llm, "_mock", False))


def run_critique(
    inputs: list[Any],
    *,
    orchestrator: object | None = None,
    consistency: bool = False,
) -> tuple[list[Any], str]:
    """Run CriticAgent on gathered inputs (single pass by default for the adapter)."""
    if not inputs:
        return [], "none"

    if orchestrator is None:
        from synthetix_alpha.pipeline.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator(mock_llm=False)

    if critic_uses_mock(orchestrator):
        return [], "mock"

    decisions = orchestrator._critic.evaluate_batch(inputs, consistency=consistency)
    return decisions, "live"
