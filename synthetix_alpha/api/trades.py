"""Operator-approved paper trade submission for the dashboard adapter."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Callable

from synthetix_alpha.api import trade_store
from synthetix_alpha.api.leg_resolution import legs_are_executable
from synthetix_alpha.api.overview import map_formed_order_to_frontend
from synthetix_alpha.live import execution, risk


class TradeSubmissionError(Exception):
    """Structured failure for approve-and-submit."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _structure_label(order: dict[str, Any]) -> str:
    if order.get("structure"):
        return str(order["structure"])
    legs = order.get("legs") or []
    types = {str(leg.get("type")) for leg in legs if leg.get("type") != "stock"}
    if types == {"put"}:
        return "put_credit_spread"
    if types == {"call"}:
        return "call_debit_or_credit"
    return "multi_leg"


def serialize_submission(result: dict[str, Any], *, order: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "unavailable")
    return {
        "ok": status in {"submitted", "pending", "filled", "duplicate", "dry_run"},
        "mode": "paper",
        "symbol": str(order.get("symbol", "")),
        "structure": _structure_label(order),
        "status": status,
        "brokerStatus": result.get("broker_status"),
        "clientOrderId": result.get("client_order_id") or order.get("client_order_id"),
        "orderId": result.get("order_id"),
        "detail": result.get("detail") or "",
        "contracts": int(order.get("contracts") or result.get("contracts") or 1),
        "limitPrice": result.get("limit_price", order.get("limit_price")),
        "net": result.get("net"),
        "legs": map_formed_order_to_frontend(order).get("legs", []),
        "asOf": _now(),
        "filled": status == "filled",
    }


def approve_and_submit(
    *,
    symbol: str | None = None,
    client_order_id: str | None = None,
    risk_fn: Callable[[list[dict]], Any] | None = None,
    submit_fn: Callable[..., dict] | None = None,
    assert_paper_fn: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Validate a cached risk-approved trade and submit to Alpaca PAPER only."""
    assert_paper_fn = assert_paper_fn or execution.assert_paper
    submit_fn = submit_fn or execution.submit

    try:
        assert_paper_fn()
    except Exception as exc:  # noqa: BLE001
        raise TradeSubmissionError(
            "live_trading_refused",
            f"Paper-only enforcement blocked submission: {exc}",
            status_code=403,
        ) from exc

    if os.environ.get("ALPACA_LIVE_TRADE", "").strip().lower() in ("1", "true", "yes"):
        raise TradeSubmissionError(
            "live_trading_refused",
            "ALPACA_LIVE_TRADE is set — dashboard submission is paper-only.",
            status_code=403,
        )

    ref = (client_order_id or symbol or "").strip()
    if not ref:
        raise TradeSubmissionError(
            "missing_reference",
            "Provide symbol or clientOrderId referencing a pipeline-formed trade.",
            status_code=400,
        )

    record = trade_store.get_trade(ref)
    if record is None:
        raise TradeSubmissionError(
            "stale_or_missing_trade",
            "No server-side risk-approved trade found for that reference. Re-run overview/pipeline first.",
            status_code=404,
        )

    if str(record.get("criticDecision", "")).upper() != "APPROVED":
        raise TradeSubmissionError(
            "critic_rejected",
            "Trade is not critic-approved.",
            status_code=400,
            extra={"criticDecision": record.get("criticDecision")},
        )

    if int(record.get("criticConfidence") or 0) < 70:
        raise TradeSubmissionError(
            "critic_rejected",
            "Trade critic confidence is below the required threshold.",
            status_code=400,
            extra={"criticConfidence": record.get("criticConfidence")},
        )

    if str(record.get("riskStatus", "")).upper() != "APPROVED":
        raise TradeSubmissionError(
            "risk_rejected",
            "Trade is not risk-approved.",
            status_code=400,
            extra={"riskStatus": record.get("riskStatus")},
        )

    order = dict(record.get("order") or {})
    legs = list(order.get("legs") or [])
    if not legs_are_executable(legs):
        raise TradeSubmissionError(
            "unresolved_legs",
            "Option legs are placeholders or invalid OCC symbols — submission blocked.",
            status_code=400,
            extra={"resolution": "placeholder"},
        )

    if risk_fn is None:
        from synthetix_alpha.api.risk_gate import run_risk

        risk_fn = run_risk

    decision = risk_fn([order])
    approved = list(getattr(decision, "approved", []) or [])
    approved_symbols = {
        str(item.get("symbol") or item.get("underlying") or "").upper()
        for item in approved
    }
    symbol_key = str(order.get("symbol", "")).upper()
    if symbol_key not in approved_symbols:
        halts = list(getattr(decision, "halts", []) or [])
        raise TradeSubmissionError(
            "risk_rejected",
            "Deterministic risk gate rejected re-validation before submission.",
            status_code=400,
            extra={"halts":halts},
        )

    contracts = int(order.get("contracts") or 1)
    limit_price = float(order.get("limit_price") or 0.0)
    if limit_price == 0.0:
        raise TradeSubmissionError(
            "invalid_limit",
            "Formed order has no executable limit price.",
            status_code=400,
        )

    try:
        result = submit_fn(legs, contracts, limit_price, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "symbol": symbol_key,
            "client_order_id": order.get("client_order_id"),
            "status": "error",
            "detail": str(exc),
            "contracts": contracts,
            "structure": _structure_label(order),
        }
        trade_store.record_execution(payload)
        raise TradeSubmissionError(
            "broker_error",
            f"Alpaca paper submission failed: {exc}",
            status_code=502,
            extra=payload,
        ) from exc

    if result.get("status") == "rejected":
        trade_store.record_execution({**result, "symbol": symbol_key, "structure": _structure_label(order)})
        raise TradeSubmissionError(
            "broker_rejected",
            result.get("detail") or "Alpaca rejected the paper order.",
            status_code=400,
            extra=serialize_submission(result, order=order),
        )

    serialized = serialize_submission(result, order=order)
    trade_store.record_execution({
        **result,
        "symbol": symbol_key,
        "structure": _structure_label(order),
        "contracts": contracts,
        "createdAt": serialized["asOf"],
        "detail": serialized["detail"] or f"Paper order {serialized['status']}",
    })
    return serialized


def get_trade_status(order_id: str, *, status_fn: Callable[[str], dict] | None = None) -> dict[str, Any]:
    """Return truthful Alpaca order state for a broker order id."""
    if not order_id or not str(order_id).strip():
        raise TradeSubmissionError("missing_order_id", "order_id is required.", status_code=400)

    status_fn = status_fn or execution.get_order_status
    try:
        execution.assert_paper()
        raw = status_fn(str(order_id).strip())
    except TradeSubmissionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TradeSubmissionError(
            "broker_error",
            f"Unable to fetch Alpaca order status: {exc}",
            status_code=502,
        ) from exc

    status = str(raw.get("status") or "unavailable")
    return {
        "orderId": raw.get("order_id") or order_id,
        "clientOrderId": raw.get("client_order_id"),
        "status": status,
        "brokerStatus": raw.get("broker_status"),
        "filledQty": raw.get("filled_qty"),
        "filledAvgPrice": raw.get("filled_avg_price"),
        "submittedAt": raw.get("submitted_at"),
        "filledAt": raw.get("filled_at"),
        "filled": status == "filled",
        "asOf": _now(),
        "mode": "paper",
    }


def cache_overview_trades(
    *,
    formed_orders: list[dict],
    risk_decision: Any,
    critique_decisions: list[Any] | None = None,
    candidates: list[dict] | None = None,
) -> None:
    """Persist formed/risk outcomes so approve-and-submit can reference them."""
    approved_symbols = {
        str(order.get("symbol") or order.get("underlying") or "").upper()
        for order in (getattr(risk_decision, "approved", []) or [])
    }
    critic_by_ticker = {
        str(getattr(d, "ticker", "")).upper(): d
        for d in (critique_decisions or [])
    }
    price_by_ticker = {
        str(c.get("ticker", "")).upper(): c.get("price")
        for c in (candidates or [])
    }
    for order in formed_orders:
        symbol = str(order.get("symbol", "")).upper()
        if not symbol:
            continue
        critic = critic_by_ticker.get(symbol)
        decision = getattr(critic, "decision", None) or (
            "APPROVED" if symbol in approved_symbols else "PENDING"
        )
        confidence = int(getattr(critic, "confidence", order.get("confidence") or 0) or 0)
        risk_status = "APPROVED" if symbol in approved_symbols else "HALTED"
        # Only cache critic-approved + risk-approved + executable for submission.
        if str(decision).upper() != "APPROVED" or risk_status != "APPROVED":
            # Still store for honest UI lookup / blocked messaging.
            pass
        trade_store.put_candidate_trade(
            order,
            critic_decision=str(decision).upper(),
            critic_confidence=confidence,
            risk_status=risk_status,
            underlying_price=price_by_ticker.get(symbol),
        )
