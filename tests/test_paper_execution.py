"""Leg resolution and paper-only execution helpers."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.api.leg_resolution import (
    estimate_credit_and_max_loss,
    is_valid_occ_symbol,
    legs_are_executable,
    resolve_via_dolt,
)
from synthetix_alpha.live.execution import assert_paper, normalize_broker_status, submit
from synthetix_alpha.pipeline.orchestrator import PipelineOrchestrator, DEFAULT_SPEC
from synthetix_alpha.pipeline.critic import CriticDecision
from synthetix_alpha.strategy.spec import Spec


def test_legs_are_executable_rejects_placeholders():
    assert not legs_are_executable([
        {"symbol": "PSX_OCC_PLACEHOLDER", "type": "put", "resolved": False},
    ])
    assert not legs_are_executable([
        {"symbol": "PSX_OCC_RESOLVED", "type": "put", "resolved": True},
    ])
    assert legs_are_executable([
        {"symbol": "PSX260918P00120000", "type": "put", "side": "short", "ratio": 1, "resolved": True},
        {"symbol": "PSX260918P00110000", "type": "put", "side": "long", "ratio": 1, "resolved": True},
    ])


def test_is_valid_occ_symbol():
    assert is_valid_occ_symbol("PSX260918P00120000")
    assert not is_valid_occ_symbol("PSX_OCC_PLACEHOLDER")


def test_estimate_credit_and_max_loss():
    credit, max_loss = estimate_credit_and_max_loss(
        [
            {"strike": 120.0, "type": "put"},
            {"strike": 110.0, "type": "put"},
        ],
        contracts=1,
    )
    assert credit < 0
    assert max_loss > 0


def test_normalize_broker_status_truthful():
    assert normalize_broker_status("filled") == "filled"
    assert normalize_broker_status("accepted") == "pending"
    assert normalize_broker_status("rejected") == "rejected"
    assert normalize_broker_status("canceled") == "cancelled"


def test_assert_paper_blocks_live(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "true")
    with pytest.raises(RuntimeError, match="paper-only"):
        assert_paper()


def test_submit_defaults_to_dry_run_and_paper(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_LIVE_TRADE", raising=False)
    legs = [
        {"symbol": "PSX260918P00120000", "side": "short", "ratio": 1},
        {"symbol": "PSX260918P00110000", "side": "long", "ratio": 1},
    ]
    result = submit(legs, 1, -1.5, store=tmp_path / "orders.json")
    assert result["status"] == "dry_run"
    assert result["net"] == "credit"


def test_resolve_via_dolt_emits_real_occ(monkeypatch):
    spec = Spec.from_dict(DEFAULT_SPEC)
    expiration = dt.date.today() + dt.timedelta(days=45)
    # Align to Friday-ish date string for OCC
    while expiration.weekday() != 4:
        expiration += dt.timedelta(days=1)
    asof = dt.date.today() - dt.timedelta(days=1)
    chains = pd.DataFrame(
        {
            "date": [asof, asof, asof, asof],
            "expiration": [expiration, expiration, expiration, expiration],
            "type": ["put", "put", "put", "put"],
            "strike": [120.0, 115.0, 110.0, 105.0],
            "delta": [-0.30, -0.22, -0.15, -0.10],
            "underlying_price": [130.0, 130.0, 130.0, 130.0],
            "bid": [2.0, 1.4, 0.9, 0.5],
            "ask": [2.2, 1.6, 1.0, 0.6],
            "mid": [2.1, 1.5, 0.95, 0.55],
            "iv": [0.3, 0.3, 0.3, 0.3],
            "volume": [10, 10, 10, 10],
        }
    ).set_index(pd.Index(["a", "b", "c", "d"], name="symbol"))

    import synthetix_alpha.strategy.data as sdata

    monkeypatch.setattr(sdata, "build", lambda *a, **k: (chains, pd.DataFrame()))
    # Force dolt path by making alpaca resolvers empty
    import synthetix_alpha.api.leg_resolution as lr

    monkeypatch.setattr(lr, "resolve_via_alpaca_chain", lambda *a, **k: [])
    monkeypatch.setattr(lr, "resolve_via_alpaca_contracts", lambda *a, **k: [])

    legs = resolve_via_dolt(spec, "PSX", pd.DataFrame({"price": [130.0]}, index=["PSX"]))
    assert legs_are_executable(legs)
    assert all(is_valid_occ_symbol(leg["symbol"]) for leg in legs)
    assert all(leg.get("resolved") is True for leg in legs)


def test_form_orders_marks_executable_when_resolved(monkeypatch):
    orch = PipelineOrchestrator(mock_llm=True)
    resolved = [
        {
            "symbol": "PSX260918P00120000",
            "side": "short",
            "ratio": 1,
            "type": "put",
            "strike": 120.0,
            "resolved": True,
        },
        {
            "symbol": "PSX260918P00110000",
            "side": "long",
            "ratio": 1,
            "type": "put",
            "strike": 110.0,
            "resolved": True,
        },
    ]
    monkeypatch.setattr(
        "synthetix_alpha.api.leg_resolution.resolve_legs",
        lambda *_a, **_k: resolved,
    )
    decisions = [
        CriticDecision(
            ticker="PSX",
            decision="APPROVED",
            confidence=90,
            regime_summary="",
            thesis="test",
            risk_factors=[],
            suggested_size_multiplier=1.0,
        )
    ]
    orders = orch._form_orders(decisions, pd.DataFrame({"price": [130.0]}, index=["PSX"]))
    assert orders[0]["executable"] is True
    assert orders[0]["limit_price"] < 0
    assert orders[0]["client_order_id"]
    assert legs_are_executable(orders[0]["legs"])


def test_pipeline_summary_ready_for_review():
    from synthetix_alpha.api.overview import build_pipeline_summary

    pipeline = build_pipeline_summary(
        as_of="2026-09-04T00:00:00Z",
        screen_count=1,
        gathered_count=1,
        gather_errors=[],
        gathered_tickers=["PSX"],
        critique_decisions=[],
        critique_mode="live",
        formed_count=1,
        risk_approved_count=1,
        risk_halt_count=0,
        executable_count=1,
    )
    execute = next(s for s in pipeline["stages"] if s["stage"] == "EXECUTE")
    assert execute["status"] == "active"
    assert "operator" in execute["result"].lower() or "review" in execute["result"].lower()
