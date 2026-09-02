"""Tests for the dashboard adapter GATHER integration."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from synthetix_alpha.api.gather import critic_input_to_candidate_fields, run_gather
from synthetix_alpha.api.overview import (
    apply_gather,
    build_overview,
    build_pipeline_summary,
    enrich_candidates_with_gather,
    map_candidates,
)


def _gather_input(
    ticker: str,
    *,
    company_name: str = "",
    sector: str = "",
    headlines: list[str] | None = None,
    analyst_consensus: float | None = None,
    insider_mspr: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        company_name=company_name,
        sector=sector,
        recent_headlines=headlines or [],
        analyst_consensus=analyst_consensus,
        insider_mspr=insider_mspr,
    )


def test_critic_input_to_candidate_fields() -> None:
    fields = critic_input_to_candidate_fields(
        _gather_input(
            "MPC",
            company_name="Marathon Petroleum Corp",
            sector="Oil & Gas Refining & Marketing",
            headlines=["Headline one", "Headline two"],
            analyst_consensus=1.2,
            insider_mspr=-4.5,
        )
    )
    assert fields["company"] == "Marathon Petroleum Corp"
    assert fields["sector"] == "Oil & Gas Refining & Marketing"
    assert fields["headlines"] == ["Headline one", "Headline two"]
    assert fields["analystConsensus"] == 1.2
    assert fields["insiderMspr"] == -4.5


def test_enrich_candidates_with_gather_merges_by_ticker() -> None:
    base = map_candidates(
        pd.DataFrame(
            {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
            index=["MPC", "PSX"],
        ),
        as_of="2026-09-03T00:00:00Z",
    )
    inputs = [
        _gather_input("MPC", company_name="Marathon Petroleum Corp", sector="Energy", headlines=["MPC news"]),
        _gather_input("PSX", company_name="Phillips 66", sector="Energy", headlines=["PSX news"]),
    ]

    enriched = enrich_candidates_with_gather(base, inputs)
    assert enriched[0]["company"] == "Marathon Petroleum Corp"
    assert enriched[0]["headlines"] == ["MPC news"]
    assert enriched[1]["company"] == "Phillips 66"
    assert "Gathered company context" in enriched[0]["critic"]["thesis"]


def test_enrich_candidates_leaves_missing_tickers_screener_only() -> None:
    base = map_candidates(
        pd.DataFrame(
            {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
            index=["MPC", "PSX"],
        ),
        as_of="2026-09-03T00:00:00Z",
    )
    enriched = enrich_candidates_with_gather(base, [_gather_input("MPC", company_name="Marathon Petroleum Corp")])
    assert enriched[0]["company"] == "Marathon Petroleum Corp"
    assert enriched[1]["company"] == ""


def test_run_gather_uses_orchestrator_helpers() -> None:
    screen_df = pd.DataFrame(
        {"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]},
        index=["MPC"],
    )

    class FakeOrch:
        def _gather_macro(self, result) -> dict:
            result.errors.append("MACRO: fred unavailable")
            return {}

        def _gather_per_ticker(self, result, tickers, macro) -> list[SimpleNamespace]:
            assert tickers == ["MPC"]
            return [_gather_input("MPC", company_name="Marathon Petroleum Corp", headlines=["MPC headline"])]

    inputs, errors = run_gather(screen_df, orchestrator=FakeOrch())
    assert len(inputs) == 1
    assert inputs[0].company_name == "Marathon Petroleum Corp"
    assert errors == ["MACRO: fred unavailable"]


def test_run_gather_empty_dataframe() -> None:
    inputs, errors = run_gather(pd.DataFrame())
    assert inputs == []
    assert errors == []


def test_run_gather_handles_none_per_ticker_result() -> None:
    screen_df = pd.DataFrame(
        {"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]},
        index=["MPC"],
    )

    class FakeOrch:
        def _gather_macro(self, result) -> dict:
            result.errors.append("MACRO: FredClient requires an API key.")
            return {}

        def _gather_per_ticker(self, result, tickers, macro):
            return None

    inputs, errors = run_gather(screen_df, orchestrator=FakeOrch())
    assert inputs == []
    assert "MACRO: FredClient requires an API key." in errors


def test_apply_gather_handles_none_inputs_without_crashing() -> None:
    base = map_candidates(
        pd.DataFrame({"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]}, index=["MPC"]),
        as_of="2026-09-03T00:00:00Z",
    )

    def none_gather(_df: object) -> tuple[None, list[str]]:
        return None, ["MACRO: FredClient requires an API key."]

    enriched, errors, warnings, inputs = apply_gather(
        base, pd.DataFrame(index=["MPC"]), gather_fn=none_gather
    )
    assert enriched[0]["company"] == ""
    assert inputs == []
    assert errors == ["MACRO: FredClient requires an API key."]
    assert any("no enriched candidates" in warning for warning in warnings)


def test_apply_gather_failure_returns_warning() -> None:
    base = map_candidates(
        pd.DataFrame({"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]}, index=["MPC"]),
        as_of="2026-09-03T00:00:00Z",
    )

    def boom(_df: object) -> tuple[list[SimpleNamespace], list[str]]:
        raise RuntimeError("finnhub unavailable")

    enriched, errors, warnings, _inputs = apply_gather(base, pd.DataFrame(index=["MPC"]), gather_fn=boom)
    assert enriched[0]["company"] == ""
    assert errors == []
    assert any("Gather unavailable" in warning for warning in warnings)
    assert "finnhub unavailable" in warnings[0]


def test_apply_gather_partial_errors() -> None:
    base = map_candidates(
        pd.DataFrame(
            {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
            index=["MPC", "PSX"],
        ),
        as_of="2026-09-03T00:00:00Z",
    )

    def partial(_df: object) -> tuple[list[SimpleNamespace], list[str]]:
        return [_gather_input("MPC", company_name="Marathon Petroleum Corp")], ["GATHER PSX: finnhub timeout"]

    enriched, errors, warnings, _inputs = apply_gather(base, pd.DataFrame(index=["MPC", "PSX"]), gather_fn=partial)
    assert enriched[0]["company"] == "Marathon Petroleum Corp"
    assert enriched[1]["company"] == ""
    assert errors == ["GATHER PSX: finnhub timeout"]
    assert warnings == []


def test_build_pipeline_summary_screen_and_gather_stages() -> None:
    pipeline = build_pipeline_summary(
        as_of="2026-09-03T12:34:56Z",
        screen_count=2,
        gathered_count=1,
        gather_errors=["GATHER PSX: finnhub timeout"],
        gathered_tickers=["MPC"],
    )
    screen = next(stage for stage in pipeline["stages"] if stage["stage"] == "SCREEN")
    gather = next(stage for stage in pipeline["stages"] if stage["stage"] == "GATHER")
    critique = next(stage for stage in pipeline["stages"] if stage["stage"] == "CRITIQUE")

    assert screen["status"] == "complete"
    assert screen["result"] == "2 candidates"
    assert gather["status"] == "complete"
    assert gather["result"] == "1 enriched"
    assert critique["status"] == "pending"
    assert critique["result"] == "0 critiqued"
    assert pipeline["events"] == [{
        "id": "gather-1",
        "timestamp": "12:34:56",
        "stage": "GATHER",
        "ticker": "MPC",
        "status": "complete",
        "detail": "Macro, company context, analyst and news inputs collected.",
    }]
    assert pipeline["errors"] == ["GATHER PSX: finnhub timeout"]


def test_build_overview_includes_gathered_candidates() -> None:
    screen_df = pd.DataFrame(
        {"iv": [28.0, 30.0], "hv": [19.0, 20.0], "iv_rv": [1.47, 1.35], "iv_rank": [0.76, 0.7]},
        index=["MPC", "PSX"],
    )

    def fake_gather(_df: object) -> tuple[list[SimpleNamespace], list[str]]:
        return [
            _gather_input("MPC", company_name="Marathon Petroleum Corp", sector="Energy", headlines=["MPC headline"]),
            _gather_input("PSX", company_name="Phillips 66", sector="Energy", analyst_consensus=0.8),
        ], []

    def fake_critique(_inputs: list[SimpleNamespace]) -> tuple[list[SimpleNamespace], str]:
        return [], "live"

    snapshot = build_overview(
        account_fn=lambda: {"equity": "1000", "cash": "500"},
        exposure_fn=lambda: {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []},
        rules_loader=lambda: type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        candidates_fn=lambda: screen_df,
        gather_fn=fake_gather,
        critique_fn=fake_critique,
    )

    assert snapshot["candidates"][0]["company"] == "Marathon Petroleum Corp"
    assert snapshot["candidates"][1]["analystConsensus"] == 0.8
    gather = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "GATHER")
    assert gather["result"] == "2 enriched"
    assert len(snapshot["pipeline"]["events"]) == 2
