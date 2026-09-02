"""Tests for the dashboard adapter FORM and RISK integration."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from synthetix_alpha.api.form import filter_approved_decisions, run_form
from synthetix_alpha.api.overview import apply_form, apply_risk, build_overview, build_pipeline_summary
from synthetix_alpha.api.risk_gate import run_risk
from synthetix_alpha.live import risk


def _decision(
    ticker: str,
    *,
    decision: str = "APPROVED",
    confidence: int = 82,
    suggested_size_multiplier: float = 1.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        decision=decision,
        confidence=confidence,
        regime_summary="",
        thesis="Rich IV supports short vol.",
        risk_factors=[],
        suggested_size_multiplier=suggested_size_multiplier,
    )


def _screen_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"iv": [28.0], "hv": [19.0], "iv_rv": [1.47], "iv_rank": [0.76]},
        index=["MPC"],
    )


def _rules() -> object:
    return type(
        "Rules",
        (),
        {
            "max_open_positions": 10,
            "max_premium_at_risk_pct": 0.02,
            "max_leverage": 1.0,
            "max_single_position_pct": 0.10,
            "max_daily_drawdown_pct": 0.05,
            "max_total_drawdown_pct": 0.20,
            "defined_risk_only": True,
        },
    )()


def test_filter_approved_decisions_matches_threshold() -> None:
    decisions = [
        _decision("MPC", decision="APPROVED", confidence=88),
        _decision("PSX", decision="APPROVED", confidence=65),
        _decision("XOM", decision="REJECTED", confidence=90),
    ]
    approved = filter_approved_decisions(decisions, confidence_threshold=70)
    assert [d.ticker for d in approved] == ["MPC"]


def test_apply_form_skips_mock_critique() -> None:
    formed, errors, warnings = apply_form(
        _screen_df(),
        [],
        critique_mode="mock",
    )
    assert formed == []
    assert errors == []
    assert warnings == []


def test_apply_form_calls_form_for_live_approved_decisions() -> None:
    decisions = [_decision("MPC", decision="APPROVED", confidence=88)]
    calls: list[tuple[list[str], object]] = []

    def fake_form(approved: list[object], screen_df: object) -> list[dict]:
        calls.append(([d.ticker for d in approved], screen_df))
        return [{"symbol": "MPC", "defined_risk": True, "max_loss": 2000.0}]

    formed, errors, warnings = apply_form(
        _screen_df(),
        decisions,
        critique_mode="live",
        form_fn=fake_form,
    )
    assert calls[0][0] == ["MPC"]
    assert list(calls[0][1].index) == ["MPC"]
    assert len(formed) == 1
    assert formed[0]["symbol"] == "MPC"
    assert errors == []
    assert warnings == []


def test_apply_form_ignores_pending_frontend_decisions_without_live_mode() -> None:
    formed, errors, warnings = apply_form(
        _screen_df(),
        [],
        critique_mode="none",
    )
    assert formed == []
    assert errors == []
    assert warnings == []


def test_run_form_delegates_to_orchestrator() -> None:
    class FakeOrch:
        def _form_orders(self, approved: list[object], candidates: pd.DataFrame) -> list[dict]:
            return [{"symbol": approved[0].ticker, "legs": [], "defined_risk": True, "max_loss": 2000.0}]

    orders = run_form([_decision("MPC")], _screen_df(), orchestrator=FakeOrch())
    assert orders[0]["symbol"] == "MPC"


def test_run_risk_uses_exposure_and_rules() -> None:
    formed = [{"symbol": "MPC", "defined_risk": True, "max_loss": 100.0}]
    exposure = {"nav": 100_000.0, "positions": [], "unprotected": []}
    decision = run_risk(
        formed,
        exposure_fn=lambda: exposure,
        rules_loader=_rules,
    )
    assert len(decision.approved) == 1
    assert decision.halts == []


def test_run_risk_surfaces_halts() -> None:
    formed = [{"symbol": "MPC", "defined_risk": True, "max_loss": 50_000.0}]
    exposure = {"nav": 100_000.0, "positions": [], "unprotected": []}
    decision = run_risk(
        formed,
        exposure_fn=lambda: exposure,
        rules_loader=_rules,
    )
    assert decision.approved == []
    assert len(decision.halts) == 1
    assert "HALT MPC" in decision.halts[0]


def test_apply_risk_returns_halts_and_errors() -> None:
    formed = [{"symbol": "MPC", "defined_risk": True, "max_loss": 50_000.0}]

    def fake_risk(_orders: list[dict]) -> risk.Decision:
        return risk.Decision(approved=[], halts=["HALT MPC: risk too high"])

    decision, halts, warnings, errors = apply_risk(formed, risk_fn=fake_risk)
    assert decision is not None
    assert halts == ["HALT MPC: risk too high"]
    assert errors == []
    assert any("halted" in warning.lower() for warning in warnings)


def test_build_pipeline_summary_reports_form_and_risk() -> None:
    pipeline = build_pipeline_summary(
        as_of="2026-09-03T12:34:56Z",
        screen_count=1,
        gathered_count=1,
        gather_errors=[],
        gathered_tickers=["MPC"],
        critique_decisions=[_decision("MPC", decision="APPROVED", confidence=88)],
        critique_mode="live",
        formed_count=1,
        risk_approved_count=1,
        risk_halt_count=0,
    )
    form = next(stage for stage in pipeline["stages"] if stage["stage"] == "FORM")
    risk_stage = next(stage for stage in pipeline["stages"] if stage["stage"] == "RISK")
    assert form["status"] == "complete"
    assert form["result"] == "1 orders formed"
    assert risk_stage["status"] == "complete"
    assert risk_stage["result"] == "1 approved · 0 halted"


def test_build_pipeline_summary_mock_form_and_risk_stay_pending() -> None:
    pipeline = build_pipeline_summary(
        as_of="2026-09-03T12:34:56Z",
        screen_count=1,
        gathered_count=1,
        gather_errors=[],
        gathered_tickers=["MPC"],
        critique_mode="mock",
    )
    form = next(stage for stage in pipeline["stages"] if stage["stage"] == "FORM")
    risk_stage = next(stage for stage in pipeline["stages"] if stage["stage"] == "RISK")
    assert form["status"] == "pending"
    assert "mock critic" in form["result"]
    assert risk_stage["status"] == "pending"
    assert "mock critic" in risk_stage["result"]


def test_build_overview_form_to_risk_without_execution(monkeypatch) -> None:
    screen_df = _screen_df()
    submit_calls: list[dict] = []

    def fake_submit(*_args, **_kwargs) -> dict:
        submit_calls.append({"called": True})
        return {"status": "submitted"}

    monkeypatch.setattr("synthetix_alpha.live.execution.submit", fake_submit)

    def fake_gather(_df: object) -> tuple[list[SimpleNamespace], list[str]]:
        return [
            SimpleNamespace(
                ticker="MPC",
                company_name="Marathon Petroleum Corp",
                sector="Energy",
                recent_headlines=["MPC headline"],
                analyst_consensus=None,
                insider_mspr=None,
            )
        ], []

    def fake_critique(_inputs: list[object]) -> tuple[list[SimpleNamespace], str]:
        return [_decision("MPC", decision="APPROVED", confidence=88)], "live"

    def fake_form(approved: list[object], _screen_df: object) -> list[dict]:
        return [{"symbol": approved[0].ticker, "defined_risk": True, "max_loss": 100.0, "legs": []}]

    def fake_risk(_orders: list[dict]) -> risk.Decision:
        return risk.Decision(approved=_orders, halts=[])

    snapshot = build_overview(
        account_fn=lambda: {"equity": "100000", "cash": "50000"},
        exposure_fn=lambda: {"nav": 100_000.0, "cash": 50_000.0, "positions": [], "unprotected": []},
        rules_loader=_rules,
        candidates_fn=lambda: screen_df,
        gather_fn=fake_gather,
        critique_fn=fake_critique,
        form_fn=fake_form,
        risk_fn=fake_risk,
    )

    assert submit_calls == []
    form = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "FORM")
    risk_stage = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "RISK")
    assert form["result"] == "1 orders formed"
    assert risk_stage["result"] == "1 approved · 0 halted"
    assert snapshot["executions"] == []


def test_build_overview_surfaces_risk_halts(monkeypatch) -> None:
    monkeypatch.setattr("synthetix_alpha.live.execution.submit", lambda *_a, **_k: {"status": "submitted"})

    snapshot = build_overview(
        account_fn=lambda: {"equity": "100000", "cash": "50000"},
        exposure_fn=lambda: {"nav": 100_000.0, "cash": 50_000.0, "positions": [], "unprotected": []},
        rules_loader=_rules,
        candidates_fn=lambda: _screen_df(),
        gather_fn=lambda _df: ([SimpleNamespace(ticker="MPC", company_name="MPC", sector="Energy", recent_headlines=["h"], analyst_consensus=None, insider_mspr=None)], []),
        critique_fn=lambda _inputs: ([_decision("MPC", decision="APPROVED", confidence=88)], "live"),
        form_fn=lambda approved, _df: [{"symbol": approved[0].ticker, "defined_risk": True, "max_loss": 50_000.0}],
        risk_fn=lambda _orders: risk.Decision(approved=[], halts=["HALT MPC: risk $50,000 exceeds 2.0% of NAV"]),
    )

    risk_stage = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "RISK")
    assert risk_stage["result"] == "0 approved · 1 halted"
    assert any("HALT MPC" in error for error in snapshot["pipeline"]["errors"])
    assert any("halted" in warning.lower() for warning in snapshot["warnings"])


def test_build_overview_mock_critique_produces_zero_formed_orders(monkeypatch) -> None:
    form_calls = {"count": 0}

    def counting_form(*_args, **_kwargs) -> list[dict]:
        form_calls["count"] += 1
        return [{"symbol": "MPC"}]

    monkeypatch.setattr("synthetix_alpha.live.execution.submit", lambda *_a, **_k: {"status": "submitted"})

    snapshot = build_overview(
        account_fn=lambda: {"equity": "1000", "cash": "500"},
        exposure_fn=lambda: {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []},
        rules_loader=_rules,
        candidates_fn=lambda: _screen_df(),
        gather_fn=lambda _df: ([SimpleNamespace(ticker="MPC", company_name="MPC", sector="Energy", recent_headlines=["h"], analyst_consensus=None, insider_mspr=None)], []),
        critique_fn=lambda _inputs: ([], "mock"),
        form_fn=counting_form,
    )

    assert form_calls["count"] == 0
    form = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "FORM")
    assert form["status"] == "pending"
    assert "mock critic" in form["result"]
