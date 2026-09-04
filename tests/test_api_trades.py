"""Paper trade approval/submission API tests — mocked broker only."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from synthetix_alpha.api import trade_store
from synthetix_alpha.api.app import app
from synthetix_alpha.api.trades import TradeSubmissionError, approve_and_submit, get_trade_status
from synthetix_alpha.live import risk

client = TestClient(app)

RESOLVED_LEGS = [
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

PLACEHOLDER_LEGS = [
    {"symbol": "PSX_OCC_PLACEHOLDER", "side": "short", "ratio": 1, "type": "put", "resolved": False},
    {"symbol": "PSX_OCC_PLACEHOLDER", "side": "long", "ratio": 1, "type": "put", "resolved": False},
]


def _seed_trade(*, legs=None, critic="APPROVED", confidence=88, risk_status="APPROVED", limit=-1.5):
    trade_store.clear()
    order = {
        "symbol": "PSX",
        "legs": legs if legs is not None else RESOLVED_LEGS,
        "contracts": 1,
        "limit_price": limit,
        "client_order_id": "sx-test-psx",
        "defined_risk": True,
        "max_loss": 850.0,
        "confidence": confidence,
        "thesis": "IV/RV premium supports a put credit spread.",
        "structure": "put_credit_spread",
        "executable": legs is None or legs is RESOLVED_LEGS,
    }
    trade_store.put_candidate_trade(
        order,
        critic_decision=critic,
        critic_confidence=confidence,
        risk_status=risk_status,
        underlying_price=130.0,
    )
    return order


@pytest.fixture(autouse=True)
def _clean_store():
    trade_store.clear()
    yield
    trade_store.clear()


def test_approve_and_submit_refuses_live_trading(monkeypatch):
    _seed_trade()
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "1")

    def boom():
        raise RuntimeError("ALPACA_LIVE_TRADE is set")

    with pytest.raises(TradeSubmissionError) as exc:
        approve_and_submit(symbol="PSX", assert_paper_fn=boom)
    assert exc.value.code == "live_trading_refused"
    assert exc.value.status_code == 403


def test_approve_and_submit_blocks_risk_rejection():
    _seed_trade(risk_status="HALTED")
    with pytest.raises(TradeSubmissionError) as exc:
        approve_and_submit(
            symbol="PSX",
            assert_paper_fn=lambda: None,
            risk_fn=lambda orders: risk.Decision(approved=[], halts=["HALT PSX"]),
            submit_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not submit")),
        )
    assert exc.value.code == "risk_rejected"


def test_approve_and_submit_blocks_critic_rejection():
    _seed_trade(critic="REJECTED", confidence=40)
    with pytest.raises(TradeSubmissionError) as exc:
        approve_and_submit(
            symbol="PSX",
            assert_paper_fn=lambda: None,
            submit_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not submit")),
        )
    assert exc.value.code == "critic_rejected"


def test_approve_and_submit_blocks_placeholder_legs():
    _seed_trade(legs=PLACEHOLDER_LEGS, limit=-1.5)
    with pytest.raises(TradeSubmissionError) as exc:
        approve_and_submit(
            symbol="PSX",
            assert_paper_fn=lambda: None,
            risk_fn=lambda orders: risk.Decision(approved=orders, halts=[]),
            submit_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not submit")),
        )
    assert exc.value.code == "unresolved_legs"


def test_approve_and_submit_success_mocked_broker():
    order = _seed_trade()
    calls = []

    def fake_submit(legs, contracts, limit_price, *, dry_run=True):
        calls.append({"legs": legs, "contracts": contracts, "limit_price": limit_price, "dry_run": dry_run})
        assert dry_run is False
        return {
            "client_order_id": "sx-test-psx",
            "status": "submitted",
            "broker_status": "accepted",
            "order_id": "ord-paper-123",
            "detail": "Alpaca status: accepted",
            "limit_price": limit_price,
            "net": "credit",
            "contracts": contracts,
        }

    result = approve_and_submit(
        symbol="PSX",
        assert_paper_fn=lambda: None,
        risk_fn=lambda orders: risk.Decision(approved=orders, halts=[]),
        submit_fn=fake_submit,
    )
    assert result["ok"] is True
    assert result["mode"] == "paper"
    assert result["orderId"] == "ord-paper-123"
    assert result["status"] == "submitted"
    assert result["filled"] is False
    assert calls and calls[0]["dry_run"] is False
    executions = trade_store.list_executions()
    assert len(executions) == 1
    assert executions[0]["orderId"] == "ord-paper-123"


def test_approve_and_submit_duplicate_is_idempotent():
    _seed_trade()

    def fake_submit(*_a, **_k):
        return {
            "client_order_id": "sx-test-psx",
            "status": "duplicate",
            "detail": "already submitted today",
            "order_id": "ord-existing",
        }

    result = approve_and_submit(
        symbol="PSX",
        assert_paper_fn=lambda: None,
        risk_fn=lambda orders: risk.Decision(approved=orders, halts=[]),
        submit_fn=fake_submit,
    )
    assert result["status"] == "duplicate"
    assert result["orderId"] == "ord-existing"
    assert result["filled"] is False


def test_approve_and_submit_broker_rejection():
    _seed_trade()

    def fake_submit(*_a, **_k):
        return {
            "client_order_id": "sx-test-psx",
            "status": "rejected",
            "detail": "insufficient buying power",
            "order_id": None,
        }

    with pytest.raises(TradeSubmissionError) as exc:
        approve_and_submit(
            symbol="PSX",
            assert_paper_fn=lambda: None,
            risk_fn=lambda orders: risk.Decision(approved=orders, halts=[]),
            submit_fn=fake_submit,
        )
    assert exc.value.code == "broker_rejected"


def test_http_approve_and_submit_endpoint(monkeypatch):
    _seed_trade()
    monkeypatch.setattr(
        "synthetix_alpha.api.app.approve_and_submit",
        lambda **_: {
            "ok": True,
            "mode": "paper",
            "symbol": "PSX",
            "structure": "put_credit_spread",
            "status": "submitted",
            "orderId": "ord-1",
            "clientOrderId": "sx-test-psx",
            "filled": False,
            "detail": "Alpaca status: accepted",
            "asOf": "2026-09-04T00:00:00Z",
            "legs": [],
            "contracts": 1,
        },
    )
    response = client.post("/v1/trades/approve-and-submit", json={"symbol": "PSX"})
    assert response.status_code == 200
    assert response.json()["orderId"] == "ord-1"
    assert response.json()["filled"] is False


def test_http_approve_blocks_when_missing(monkeypatch):
    monkeypatch.setattr(
        "synthetix_alpha.api.app.approve_and_submit",
        lambda **_: (_ for _ in ()).throw(
            TradeSubmissionError("stale_or_missing_trade", "missing", status_code=404)
        ),
    )
    response = client.post("/v1/trades/approve-and-submit", json={"symbol": "ZZZ"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "stale_or_missing_trade"


def test_http_order_status_endpoint(monkeypatch):
    monkeypatch.setattr(
        "synthetix_alpha.api.app.get_trade_status",
        lambda order_id: {
            "orderId": order_id,
            "status": "pending",
            "brokerStatus": "accepted",
            "filled": False,
            "mode": "paper",
            "asOf": "2026-09-04T00:00:00Z",
        },
    )
    response = client.get("/v1/trades/ord-paper-123")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["filled"] is False


def test_get_trade_status_never_marks_filled_without_broker(monkeypatch):
    status = get_trade_status(
        "ord-1",
        status_fn=lambda _oid: {
            "order_id": "ord-1",
            "status": "pending",
            "broker_status": "accepted",
            "filled_qty": "0",
        },
    )
    assert status["filled"] is False
    assert status["status"] == "pending"


def test_cors_still_allows_all_configured_origins(monkeypatch):
    monkeypatch.setattr("synthetix_alpha.api.app.build_overview", lambda: {"mode": "paper"})
    for origin in (
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "https://synthetix-alpha.vercel.app",
    ):
        response = client.get("/v1/overview", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin
