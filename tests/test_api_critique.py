"""Tests for the dashboard adapter CRITIQUE integration."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from synthetix_alpha.api.critique import (
    critic_decision_to_frontend,
    critic_uses_mock,
    enrich_candidates_with_mock_critique,
    mock_critic_for_ticker,
    run_critique,
)
from synthetix_alpha.api.overview import (
    apply_critique,
    build_overview,
    build_pipeline_summary,
    count_critique_buckets,
    enrich_candidates_with_critique,
    map_candidates,
)


def _decision(
    ticker: str,
    *,
    decision: str = "APPROVED",
    confidence: int = 82,
    regime_summary: str = "Elevated IV in risk-off tape.",
    thesis: str = "Sell premium into rich vol.",
    risk_factors: list[str] | None = None,
    suggested_size_multiplier: float = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        decision=decision,
        confidence=confidence,
        regime_summary=regime_summary,
        thesis=thesis,
        risk_factors=risk_factors or ["Earnings in two weeks"],
        suggested_size_multiplier=suggested_size_multiplier,
    )


def test_critic_decision_to_frontend_maps_fields() -> None:
    mapped = critic_decision_to_frontend(
        _decision(
            "MPC",
            decision="REJECTED",
            confidence=45,
            regime_summary="Macro stress",
            thesis="Spread too tight.",
            risk_factors=["Liquidity", "Macro"],
            suggested_size_multiplier=0.5,
        )
    )
    assert mapped == {
        "ticker": "MPC",
        "decision": "REJECTED",
        "confidence": 45,
        "regimeSummary": "Macro stress",
        "thesis": "Spread too tight.",
        "riskFactors": ["Liquidity", "Macro"],
        "suggestedSizeMultiplier": 0.5,
    }


def test_enrich_candidates_with_critique_merges_by_ticker() -> None:
    base = map_candidates(
        pd.DataFrame(
            {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
            index=["MPC", "PSX"],
        ),
        as_of="2026-09-03T00:00:00Z",
    )
    decisions = [
        _decision("MPC", decision="APPROVED", confidence=88, thesis="Rich IV supports short vol."),
        _decision("PSX", decision="REJECTED", confidence=40, thesis="Setup lacks edge."),
    ]

    enriched = enrich_candidates_with_critique(base, decisions)
    assert enriched[0]["critic"]["decision"] == "APPROVED"
    assert enriched[0]["critic"]["confidence"] == 88
    assert enriched[0]["critic"]["regimeSummary"] == "Elevated IV in risk-off tape."
    assert enriched[1]["critic"]["decision"] == "REJECTED"
    assert enriched[1]["critic"]["thesis"] == "Setup lacks edge."


def test_count_critique_buckets_matches_orchestrator_threshold() -> None:
    decisions = [
        _decision("MPC", decision="APPROVED", confidence=88),
        _decision("PSX", decision="APPROVED", confidence=65),
        _decision("XOM", decision="REJECTED", confidence=90),
    ]
    approved, rejected = count_critique_buckets(decisions)
    assert approved == 1
    assert rejected == 2


def test_apply_critique_mock_mode_adds_warning() -> None:
    base = map_candidates(
        pd.DataFrame({"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]}, index=["MPC"]),
        as_of="2026-09-03T00:00:00Z",
    )
    inputs = [SimpleNamespace(ticker="MPC")]

    def fake_critique(_inputs: list[object]) -> tuple[list[SimpleNamespace], str]:
        return [], "mock"

    enriched, errors, warnings, decisions, mode = apply_critique(base, inputs, critique_fn=fake_critique)
    assert mode == "mock"
    assert enriched[0]["critic"]["ticker"] == "MPC"
    assert enriched[0]["critic"]["decision"] == "PENDING"
    assert enriched[0]["critic"]["confidence"] == 0
    assert "Mock LLM output" in enriched[0]["critic"]["thesis"]
    assert errors == []
    assert decisions == []
    assert any("mock LLM output" in warning for warning in warnings)


def test_apply_critique_failure_keeps_pending_and_warns() -> None:
    base = map_candidates(
        pd.DataFrame({"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]}, index=["MPC"]),
        as_of="2026-09-03T00:00:00Z",
    )
    inputs = [SimpleNamespace(ticker="MPC")]

    def boom(_inputs: list[object]) -> tuple[list[SimpleNamespace], str]:
        raise RuntimeError("openai timeout")

    enriched, errors, warnings, decisions, mode = apply_critique(base, inputs, critique_fn=boom)
    assert mode == "none"
    assert enriched[0]["critic"]["decision"] == "PENDING"
    assert errors == ["CRITIQUE: openai timeout"]
    assert any("Critic unavailable" in warning for warning in warnings)
    assert decisions == []


def test_apply_critique_live_mode_no_mock_warning() -> None:
    base = map_candidates(
        pd.DataFrame({"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]}, index=["MPC"]),
        as_of="2026-09-03T00:00:00Z",
    )
    inputs = [SimpleNamespace(ticker="MPC")]

    def fake_critique(_inputs: list[object]) -> tuple[list[SimpleNamespace], str]:
        return [_decision("MPC", decision="APPROVED", confidence=91)], "live"

    _enriched, _errors, warnings, _decisions, mode = apply_critique(base, inputs, critique_fn=fake_critique)
    assert mode == "live"
    assert not any("mock LLM output" in warning for warning in warnings)


def test_run_critique_uses_consistency_false_by_default() -> None:
    inputs = [SimpleNamespace(ticker="MPC")]
    calls: list[bool] = []

    class FakeCritic:
        def evaluate_batch(self, batch, *, consistency: bool = False) -> list[SimpleNamespace]:
            calls.append(consistency)
            return [_decision("MPC")]

    class FakeOrch:
        def __init__(self) -> None:
            self._critic = FakeCritic()
            self._critic._llm = SimpleNamespace(_mock=False)

    decisions, mode = run_critique(inputs, orchestrator=FakeOrch(), consistency=False)
    assert calls == [False]
    assert len(decisions) == 1
    assert mode == "live"


def test_critic_uses_mock_detects_llm_flag() -> None:
    orch = SimpleNamespace(_critic=SimpleNamespace(_llm=SimpleNamespace(_mock=True)))
    assert critic_uses_mock(orch) is True
    orch._critic._llm._mock = False
    assert critic_uses_mock(orch) is False


def test_run_critique_skips_mock_llm_calls() -> None:
    inputs = [SimpleNamespace(ticker="MPC")]
    calls = {"count": 0}

    class FakeCritic:
        def evaluate_batch(self, batch, *, consistency: bool = False) -> list[SimpleNamespace]:
            calls["count"] += 1
            return [_decision("MOCK: ticker", decision="APPROVED", confidence=50, thesis="MOCK: thesis")]

    class FakeOrch:
        def __init__(self) -> None:
            self._critic = FakeCritic()
            self._critic._llm = SimpleNamespace(_mock=True)

    decisions, mode = run_critique(inputs, orchestrator=FakeOrch(), consistency=False)
    assert calls["count"] == 0
    assert decisions == []
    assert mode == "mock"


def test_mock_critic_for_ticker_uses_pending_and_real_symbol() -> None:
    critic = mock_critic_for_ticker("MPC")
    assert critic["ticker"] == "MPC"
    assert critic["decision"] == "PENDING"
    assert critic["confidence"] == 0


def test_enrich_candidates_with_mock_critique_preserves_tickers() -> None:
    base = map_candidates(
        pd.DataFrame(
            {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
            index=["MPC", "PSX"],
        ),
        as_of="2026-09-03T00:00:00Z",
    )
    inputs = [SimpleNamespace(ticker="MPC"), SimpleNamespace(ticker="PSX")]

    enriched = enrich_candidates_with_mock_critique(base, inputs)
    assert enriched[0]["critic"]["ticker"] == "MPC"
    assert enriched[1]["critic"]["ticker"] == "PSX"
    assert enriched[0]["critic"]["decision"] == "PENDING"
    assert enriched[1]["critic"]["decision"] == "PENDING"


def test_build_pipeline_summary_reports_mock_critique_as_pending() -> None:
    pipeline = build_pipeline_summary(
        as_of="2026-09-03T12:34:56Z",
        screen_count=2,
        gathered_count=2,
        gather_errors=[],
        gathered_tickers=["MPC", "PSX"],
        critique_decisions=[],
        critique_mode="mock",
    )
    critique = next(stage for stage in pipeline["stages"] if stage["stage"] == "CRITIQUE")
    assert critique["status"] == "pending"
    assert critique["result"] == "2 pending (mock critic)"
    critique_events = [event for event in pipeline["events"] if event["stage"] == "CRITIQUE"]
    assert len(critique_events) == 2
    assert critique_events[0]["ticker"] == "MPC"
    assert critique_events[1]["ticker"] == "PSX"
    assert critique_events[0]["status"] == "pending"
    assert "Mock LLM output" in critique_events[0]["detail"]


def test_build_pipeline_summary_includes_critique_stage() -> None:
    pipeline = build_pipeline_summary(
        as_of="2026-09-03T12:34:56Z",
        screen_count=2,
        gathered_count=2,
        gather_errors=[],
        gathered_tickers=["MPC", "PSX"],
        critique_decisions=[
            _decision("MPC", decision="APPROVED", confidence=88),
            _decision("PSX", decision="REJECTED", confidence=55),
        ],
    )
    critique = next(stage for stage in pipeline["stages"] if stage["stage"] == "CRITIQUE")
    assert critique["status"] == "complete"
    assert critique["result"] == "1 approved · 1 rejected (conf >= 70)"
    assert len(pipeline["events"]) == 4
    assert pipeline["events"][2]["stage"] == "CRITIQUE"
    assert pipeline["events"][2]["ticker"] == "MPC"
    assert pipeline["events"][3]["status"] == "blocked"


def test_build_overview_includes_critique_decisions() -> None:
    screen_df = pd.DataFrame(
        {"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]},
        index=["MPC"],
    )

    def fake_gather(_df: object) -> tuple[list[SimpleNamespace], list[str]]:
        return [SimpleNamespace(ticker="MPC", company_name="Marathon Petroleum Corp", sector="Energy", recent_headlines=["MPC headline"], analyst_consensus=None, insider_mspr=None)], []

    def fake_critique(_inputs: list[object]) -> tuple[list[SimpleNamespace], str]:
        return [_decision("MPC", decision="APPROVED", confidence=88, thesis="Rich IV supports short vol.")], "live"

    snapshot = build_overview(
        account_fn=lambda: {"equity": "1000", "cash": "500"},
        exposure_fn=lambda: {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []},
        rules_loader=lambda: type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        candidates_fn=lambda: screen_df,
        gather_fn=fake_gather,
        critique_fn=fake_critique,
    )

    assert snapshot["candidates"][0]["critic"]["decision"] == "APPROVED"
    assert snapshot["candidates"][0]["critic"]["confidence"] == 88
    critique = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "CRITIQUE")
    assert critique["status"] == "complete"
    assert "1 approved" in critique["result"]
    assert not any("Critic decisions are not available" in warning for warning in snapshot["warnings"])
