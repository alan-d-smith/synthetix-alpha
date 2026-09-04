"""Component connectivity tests for the pipeline package."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from synthetix_alpha.pipeline import (
    CriticAgent,
    CriticDecision,
    CriticInput,
    LLMAPIError,
    LLMClient,
    PipelineOrchestrator,
    PipelineResult,
)
from synthetix_alpha.pipeline.critic import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# LLMClient tests
# ---------------------------------------------------------------------------


def test_llm_mock_complete() -> None:
    llm = LLMClient(mock=True)
    assert llm._mock is True
    out = llm.complete("system", "user")
    assert isinstance(out, str)
    assert "MOCK:" in out


def test_llm_mock_structured() -> None:
    llm = LLMClient(mock=True)
    d = llm.complete_structured("sys", "user", CriticDecision)
    assert isinstance(d, CriticDecision)
    assert d.decision in ("APPROVED", "REJECTED")
    assert 1 <= d.confidence <= 100
    assert d.suggested_size_multiplier in (0.5, 0.75, 1.0)


def test_llm_strip_json_plain() -> None:
    assert LLMClient._strip_json('{"a":1}') == '{"a":1}'


def test_llm_strip_json_fenced() -> None:
    result = LLMClient._strip_json("```json\n{\"a\":1}\n```")
    assert result == '{"a":1}'


def test_llm_strip_json_ws() -> None:
    assert LLMClient._strip_json("  {\"a\":1}  ") == '{"a":1}'


def test_llm_default_mock_mode() -> None:
    old_openai = os.environ.pop("OPENAI_API_KEY", None)
    old_featherless = os.environ.pop("FEATHERLESS_API_KEY", None)
    try:
        llm = LLMClient()
        assert llm._mock is True
    finally:
        if old_openai:
            os.environ["OPENAI_API_KEY"] = old_openai
        if old_featherless:
            os.environ["FEATHERLESS_API_KEY"] = old_featherless


def test_llm_key_disables_mock() -> None:
    old = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "sk-fake-test-key"
    try:
        llm = LLMClient(mock=False)
        assert llm._mock is False
    finally:
        if old:
            os.environ["OPENAI_API_KEY"] = old
        else:
            os.environ.pop("OPENAI_API_KEY", None)
# ---------------------------------------------------------------------------
# CriticInput / CriticDecision model tests
# ---------------------------------------------------------------------------


def test_critic_input_validates() -> None:
    inp = CriticInput(ticker="SPY", iv=0.30, hv=0.20, iv_rv=1.5, iv_rank=0.85)
    assert inp.ticker == "SPY"


def test_critic_input_all_fields() -> None:
    inp = CriticInput(
        ticker="AAPL", iv=0.35, hv=0.24, iv_rv=1.46, iv_rank=0.90,
        rsi=55.0, bollinger_pos=0.6, macd=0.001,
        company_name="Apple Inc.", sector="Technology",
        market_cap=3_500_000_000_000, analyst_consensus=1.5,
        insider_mspr=-20.0, recent_headlines=["Apple beats estimates"],
        yield_curve=0.25, hy_spread=3.5, nfci=-0.1,
    )
    assert inp.company_name == "Apple Inc."
    assert inp.recent_headlines == ["Apple beats estimates"]


def test_critic_decision_defaults() -> None:
    d = CriticDecision(ticker="SPY")
    assert d.decision == "APPROVED"
    assert d.confidence == 50
    assert d.suggested_size_multiplier == 1.0
    assert d.risk_factors == []
    assert d.thesis == ""


def test_critic_decision_bounds() -> None:
    with pytest.raises(Exception):
        CriticDecision(ticker="X", confidence=0)
    with pytest.raises(Exception):
        CriticDecision(ticker="X", confidence=101)
    with pytest.raises(Exception):
        CriticDecision(ticker="X", suggested_size_multiplier=0.4)
    with pytest.raises(Exception):
        CriticDecision(ticker="X", suggested_size_multiplier=0.6)
    with pytest.raises(Exception):
        CriticDecision(ticker="X", suggested_size_multiplier=0.8)
    with pytest.raises(Exception):
        CriticDecision(ticker="X", decision="PENDING")  # not a Literal option


def test_critic_decision_discrete_multipliers() -> None:
    """Only 0.5, 0.75, and 1.0 are valid size multipliers."""
    for v in (0.5, 0.75, 1.0):
        d = CriticDecision(ticker="SPY", suggested_size_multiplier=v)
        assert d.suggested_size_multiplier == v


def test_critic_decision_valid_decisions() -> None:
    """APPROVED and REJECTED are the only valid decision strings."""
    d1 = CriticDecision(ticker="X", decision="APPROVED")
    assert d1.decision == "APPROVED"
    d2 = CriticDecision(ticker="X", decision="REJECTED")
    assert d2.decision == "REJECTED"


# ---------------------------------------------------------------------------
# CriticAgent tests
# ---------------------------------------------------------------------------


def test_critic_agent_mock_evaluate() -> None:
    llm = LLMClient(mock=True)
    critic = CriticAgent(llm=llm)
    inp = CriticInput(
        ticker="SPY", iv=0.30, hv=0.20, iv_rv=1.5, iv_rank=0.85,
        yield_curve=0.15, hy_spread=3.0, nfci=-0.1,
    )
    d = critic.evaluate(inp)
    assert isinstance(d, CriticDecision)
    assert d.ticker


def test_critic_agent_mock_batch() -> None:
    llm = LLMClient(mock=True)
    critic = CriticAgent(llm=llm)
    inputs = [
        CriticInput(ticker="SPY", iv=0.30, hv=0.20, iv_rv=1.5, iv_rank=0.85),
        CriticInput(ticker="QQQ", iv=0.25, hv=0.17, iv_rv=1.47, iv_rank=0.72),
    ]
    results = critic.evaluate_batch(inputs)
    assert len(results) == 2
    assert all(isinstance(d, CriticDecision) for d in results)


def test_critic_agent_mock_batch_consistency() -> None:
    """Ensemble voting with mock LLM: all 3 runs return identical structured output."""
    llm = LLMClient(mock=True)
    critic = CriticAgent(llm=llm)
    inp = CriticInput(ticker="SPY", iv=0.30, hv=0.20, iv_rv=1.5, iv_rank=0.85)
    results = critic.evaluate_batch([inp], consistency=True)
    assert len(results) == 1
    assert results[0].decision in ("APPROVED", "REJECTED")
    assert 1 <= results[0].confidence <= 100
    assert results[0].suggested_size_multiplier in (0.5, 0.75, 1.0)


def test_critic_evaluate_with_consistency() -> None:
    """Single input through ensemble voting: should return a valid CriticDecision."""
    llm = LLMClient(mock=True)
    critic = CriticAgent(llm=llm)
    inp = CriticInput(
        ticker="SPY", iv=0.35, hv=0.22, iv_rv=1.59, iv_rank=0.88,
        yield_curve=0.10, hy_spread=3.0, nfci=-0.2,
    )
    d = critic.evaluate_with_consistency(inp)
    assert isinstance(d, CriticDecision)
    assert d.ticker == "SPY"
    assert d.decision in ("APPROVED", "REJECTED")
    assert 1 <= d.confidence <= 100
    assert d.suggested_size_multiplier in (0.5, 0.75, 1.0)


def test_llm_seed_parameter() -> None:
    """LLMClient accepts and stores a seed parameter."""
    llm = LLMClient(mock=True, seed=12345)
    assert llm._seed == 12345


# ---------------------------------------------------------------------------
# PipelineOrchestrator tests
# ---------------------------------------------------------------------------


def test_orchestrator_instantiation() -> None:
    orch = PipelineOrchestrator(mock_llm=True, confidence_threshold=70)
    assert orch._confidence_threshold == 70
    assert isinstance(orch._critic, CriticAgent)


def test_orchestrator_default_spec() -> None:
    orch = PipelineOrchestrator(mock_llm=True)
    spec = orch._get_spec()
    assert spec.name == "default_put_credit_spread"
    assert len(spec.legs) == 2


def test_orchestrator_custom_threshold() -> None:
    orch = PipelineOrchestrator(mock_llm=True, confidence_threshold=85)
    assert orch._confidence_threshold == 85


def test_pipeline_result_dataclass() -> None:
    r = PipelineResult()
    assert r.candidates.empty
    assert r.decisions == []
    assert r.approved_by_critic == []
    assert r.formed_orders == []
    assert r.errors == []
    assert r.risk_decision is None


def test_pipeline_result_with_formed_orders() -> None:
    r = PipelineResult()
# ---------------------------------------------------------------------------
# Cross-module import connectivity
# ---------------------------------------------------------------------------


def test_cross_module_data() -> None:
    from synthetix_alpha.data.finnhub_client import FinnhubClient  # noqa: F401
    from synthetix_alpha.data.fred_client import FredClient  # noqa: F401


def test_cross_module_strategy() -> None:
    from synthetix_alpha.strategy.spec import Spec  # noqa: F401
    from synthetix_alpha.strategy.data import technicals  # noqa: F401


def test_cross_module_live() -> None:
    from synthetix_alpha.live import execution, risk  # noqa: F401
    from synthetix_alpha.live.execution import client_order_id  # noqa: F401


def test_cross_module_pipeline() -> None:
    from synthetix_alpha.pipeline import (
        LLMClient, CriticAgent, CriticInput, CriticDecision,
        PipelineOrchestrator, PipelineResult, LLMAPIError, main,
    )  # noqa: F401


# ---------------------------------------------------------------------------
# Order formation (abstract / no chain)
# ---------------------------------------------------------------------------


def test_form_orders_without_chain(monkeypatch) -> None:
    import synthetix_alpha.api.leg_resolution as lr

    monkeypatch.setattr(lr, "resolve_via_alpaca_chain", lambda *a, **k: [])
    monkeypatch.setattr(lr, "resolve_via_alpaca_contracts", lambda *a, **k: [])
    monkeypatch.setattr(lr, "resolve_via_dolt", lambda *a, **k: [])

    orch = PipelineOrchestrator(mock_llm=True)
    decisions = [
        CriticDecision(
            ticker="SPY", decision="APPROVED", confidence=80,
            regime_summary="", thesis="test", risk_factors=[],
            suggested_size_multiplier=1.0,
        ),
    ]
    candidates = pd.DataFrame(
        {"iv": [30.0], "hv": [20.0], "iv_rv": [1.5], "iv_rank": [0.85]},
        index=["SPY"],
    )
    orders = orch._form_orders(decisions, candidates)
    assert len(orders) == 1
    o = orders[0]
    assert o["symbol"] == "SPY"
    assert o["defined_risk"] is True
    assert o["max_loss"] == pytest.approx(2000.0)
    assert o["confidence"] == 80
    assert len(o["legs"]) == 2
    assert o["executable"] is False


def test_execute_orders_delegates_to_execution(monkeypatch) -> None:
    from synthetix_alpha.pipeline import orchestrator as orch_module

    calls = []

    def fake_submit(legs, contracts, limit_price, *, dry_run=True):
        calls.append((legs, contracts, limit_price, dry_run))
        return {
            "client_order_id": "test-coid",
            "status": "dry_run",
            "net": "credit",
        }

    monkeypatch.setattr(orch_module.execution, "submit", fake_submit)

    orch = PipelineOrchestrator(mock_llm=True)
    legs = [
        {"symbol": "SPY260930P00760000", "side": "short", "ratio": 1},
        {"symbol": "SPY260930P00740000", "side": "long", "ratio": 1},
    ]

    result = orch._execute_orders(
        [{
            "symbol": "SPY",
            "legs": legs,
            "contracts": 2,
            "limit_price": -1.50,
            "client_order_id": "test-coid",
        }],
        dry_run=True,
    )

    assert result[0]["symbol"] == "SPY"
    assert result[0]["status"] == "dry_run"
    assert calls == [(legs, 2, -1.50, True)]



def test_resolve_legs_abstract(monkeypatch) -> None:
    """Falls back to placeholder symbols when no chain data is available."""
    import synthetix_alpha.api.leg_resolution as lr
    import synthetix_alpha.strategy.data as sdata

    monkeypatch.setattr(sdata, "build", lambda *a, **k: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr(lr, "resolve_via_alpaca_chain", lambda *a, **k: [])
    monkeypatch.setattr(lr, "resolve_via_alpaca_contracts", lambda *a, **k: [])
    orch = PipelineOrchestrator(mock_llm=True)
    spec = orch._get_spec()
    legs = orch._resolve_legs(spec, "SPY", pd.DataFrame())
    assert len(legs) == 2
    assert all("OCC_PLACEHOLDER" in l["symbol"] for l in legs)
    assert all(l.get("resolved") is False for l in legs)


def test_resolve_legs_uses_real_symbols_when_chain_is_available(monkeypatch) -> None:
    """Resolved path emits real OCC symbols (not placeholders)."""
    import pytest

    from synthetix_alpha.api.leg_resolution import is_valid_occ_symbol, legs_are_executable
    from synthetix_alpha.strategy.data import build as build_chain

    try:
        chains, _ = build_chain("SPY", source="dolt")
    except Exception as e:
        pytest.skip(f"no chain data available: {type(e).__name__}")
    if chains.empty:
        pytest.skip("no chain data available")

    import synthetix_alpha.api.leg_resolution as lr

    # Prefer dolt path for this unit test (deterministic offline data).
    monkeypatch.setattr(lr, "resolve_via_alpaca_chain", lambda *a, **k: [])
    monkeypatch.setattr(lr, "resolve_via_alpaca_contracts", lambda *a, **k: [])

    orch = PipelineOrchestrator(mock_llm=True)
    legs = orch._resolve_legs(orch._get_spec(), "SPY", pd.DataFrame({"price": [500.0]}, index=["SPY"]))
    assert len(legs) == 2
    assert legs_are_executable(legs)
    assert all(is_valid_occ_symbol(l["symbol"]) for l in legs)
    assert all("OCC_PLACEHOLDER" not in l["symbol"] for l in legs)


def test_system_prompt_fields_match_schema() -> None:
    fields = {"ticker", "decision", "confidence", "regime_summary",
              "thesis", "risk_factors", "suggested_size_multiplier"}
    for f in fields:
        assert f in SYSTEM_PROMPT, f"Missing field '{f}' in SYSTEM_PROMPT"