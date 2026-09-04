"""In-process store for risk-approved paper trades awaiting operator submission."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

_lock = threading.Lock()
_trades: dict[str, dict[str, Any]] = {}
_executions: list[dict[str, Any]] = []


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def clear() -> None:
    with _lock:
        _trades.clear()
        _executions.clear()


def put_candidate_trade(
    order: dict[str, Any],
    *,
    critic_decision: str,
    critic_confidence: int,
    risk_status: str,
    underlying_price: float | None = None,
) -> None:
    """Cache a formed order for later operator approve-and-submit."""
    symbol = str(order.get("symbol", "")).upper()
    if not symbol:
        return
    coid = str(order.get("client_order_id") or "")
    record = {
        "symbol": symbol,
        "order": dict(order),
        "criticDecision": critic_decision,
        "criticConfidence": int(critic_confidence),
        "riskStatus": risk_status,
        "underlyingPrice": underlying_price,
        "updatedAt": _now(),
    }
    with _lock:
        _trades[symbol] = record
        if coid:
            _trades[coid] = record


def get_trade(ref: str) -> dict[str, Any] | None:
    key = str(ref or "").strip()
    if not key:
        return None
    with _lock:
        record = _trades.get(key) or _trades.get(key.upper())
        return dict(record) if record else None


def list_ready_trades() -> list[dict[str, Any]]:
    with _lock:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for record in _trades.values():
            symbol = str(record.get("symbol", ""))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            out.append(dict(record))
        return out


def record_execution(execution: dict[str, Any]) -> None:
    row = {
        "symbol": str(execution.get("symbol", "")),
        "clientOrderId": str(execution.get("client_order_id") or execution.get("clientOrderId") or ""),
        "status": str(execution.get("status", "unavailable")),
        "detail": str(execution.get("detail") or ""),
        "createdAt": str(execution.get("createdAt") or _now()),
        "orderId": execution.get("order_id") or execution.get("orderId"),
        "structure": execution.get("structure"),
        "quantity": execution.get("contracts") or execution.get("quantity"),
    }
    with _lock:
        # Replace prior row for same client order id when present.
        coid = row["clientOrderId"]
        _executions[:] = [e for e in _executions if e.get("clientOrderId") != coid]
        _executions.insert(0, row)


def list_executions(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return [dict(row) for row in _executions[:limit]]
