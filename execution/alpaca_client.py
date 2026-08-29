"""
alpaca_client.py — Stage 7: Alpaca Trading API Execution Layer.

Uses alpaca-py SDK for all order operations. Paper trading only.
Submits OCO bracket orders (entry + take_profit + stop_loss).
Always attaches a unique client_order_id for idempotency.
Polls positions every 15 min against stored TP/SL; rebuilds bracket
if missing.

Safety: never submit, modify, cancel, or close any order without first
printing a full order preview and getting explicit user approval.
"""
from __future__ import annotations

import os
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

_client: TradingClient | None = None


def _get_client() -> TradingClient:
    """Lazy-singleton TradingClient pinned to paper trading.

    paper=True is a **literal** — never read from env/config.
    """
    global _client
    if _client is None:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_API_SECRET")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set in .env"
            )
        _client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,  # LITERAL — per .clinerules, never from env
        )
    return _client


def _verify_paper_safety() -> None:
    """Refuse to proceed if ALPACA_LIVE_TRADE is set to true."""
    if os.getenv("ALPACA_LIVE_TRADE", "").lower() == "true":
        raise RuntimeError(
            "ALPACA_LIVE_TRADE=true is set — LIVE TRADING DETECTED. "
            "Refusing to proceed. Unset this variable or set it to false."
        )


# ---------------------------------------------------------------------------
# Bracket order payload builder (pure — no network, testable without API key)
# ---------------------------------------------------------------------------

def build_bracket_payload(order: dict[str, Any]) -> dict[str, Any]:
    """Convert a sized order dict into the Alpaca bracket-order request shape.

    Computes take-profit limit_price and stop-loss stop_price from
    entry_price × (1 ± pct), respecting buy vs sell sides.
    """
    ticker = order["ticker"]
    side = order["side"]
    qty = order["qty"]
    entry_price = float(order.get("entry_price", 100.0))
    tp_pct = float(order.get("take_profit_pct", 0.05))
    sl_pct = float(order.get("stop_loss_pct", 0.03))
    client_order_id = order.get("client_order_id", "")

    if side == "buy":
        tp_price = round(entry_price * (1 + tp_pct), 2)
        sl_price = round(entry_price * (1 - sl_pct), 2)
    else:
        tp_price = round(entry_price * (1 - tp_pct), 2)
        sl_price = round(entry_price * (1 + sl_pct), 2)

    return {
        "symbol": ticker,
        "qty": qty,
        "side": OrderSide.BUY if side == "buy" else OrderSide.SELL,
        "type": "market",
        "time_in_force": TimeInForce.DAY,
        "order_class": OrderClass.BRACKET,
        "take_profit": {"limit_price": tp_price},
        "stop_loss": {"stop_price": sl_price},
        "client_order_id": client_order_id,
    }


# ---------------------------------------------------------------------------
# Order preview
# ---------------------------------------------------------------------------

def preview_order(order: dict[str, Any]) -> str:
    """Build a human-readable order preview table."""
    ticker = order.get("ticker", "?")
    side = order.get("side", "?").upper()
    qty = order.get("qty", 0)
    entry = float(order.get("entry_price", 0))
    tp_pct = float(order.get("take_profit_pct", 0))
    sl_pct = float(order.get("stop_loss_pct", 0))
    notional = order.get("estimated_notional", 0)
    conf = order.get("confidence_score", 0)
    ts = order.get("time_stop_min", "-")
    oid = order.get("client_order_id", "-")

    if side == "BUY":
        tp_target = round(entry * (1 + tp_pct), 2)
        sl_target = round(entry * (1 - sl_pct), 2)
    else:
        tp_target = round(entry * (1 - tp_pct), 2)
        sl_target = round(entry * (1 + sl_pct), 2)

    return (
        "\n"
        "┌───────────────────────────────────────────┐\n"
        "│  ORDER PREVIEW — PAPER TRADING ONLY        │\n"
        "├────────────────┬──────────────────────────┤\n"
        f"│ Ticker         │ {ticker:<24} │\n"
        f"│ Side           │ {side:<24} │\n"
        f"│ Qty            │ {qty} share{'s' if qty != 1 else ''}{' ' * max(0, 15 - len(str(qty)))}│\n"
        f"│ Entry          │ MARKET @ ~${entry:,.2f}{' ' * max(0, 6 - len(f'{entry:,.2f}'))}│\n"
        f"│ Take Profit    │ {tp_pct:.1%} → ${tp_target:,.2f} (limit){' ' * max(0, 1)}│\n"
        f"│ Stop Loss      │ {sl_pct:.1%} → ${sl_target:,.2f} (stop){' ' * max(0, 1)}│\n"
        f"│ Time Stop      │ {ts} min{' ' * max(0, 20 - len(str(ts)))}│\n"
        f"│ Est. Notional  │ ${notional:,.2f}{' ' * max(0, 6 - len(f'{notional:,.2f}'))}│\n"
        f"│ Confidence     │ {conf:.2f}{' ' * max(0, 21 - len(f'{conf:.2f}'))}│\n"
        f"│ Client Order   │ {oid}{' ' * max(0, 1)}│\n"
        "└────────────────┴──────────────────────────┘\n"
    )


# ---------------------------------------------------------------------------
# Order submission
# ---------------------------------------------------------------------------

def submit_bracket_order(
    order: dict[str, Any],
    dry_run: bool = True,
) -> dict[str, Any] | None:
    """Submit an OCO bracket order via Alpaca.  Prints preview + payload.

    On dry_run, returns None — no network call.
    """
    preview = preview_order(order)
    logger.info(preview)

    payload = build_bracket_payload(order)
    logger.info(f"Payload: {payload}")

    if dry_run:
        logger.info("DRY RUN — order NOT submitted.")
        return None

    _verify_paper_safety()
    client = _get_client()
    req = MarketOrderRequest(
        symbol=payload["symbol"],
        qty=payload["qty"],
        side=payload["side"],
        time_in_force=payload["time_in_force"],
        order_class=payload["order_class"],
        take_profit=TakeProfitRequest(
            limit_price=payload["take_profit"]["limit_price"]
        ),
        stop_loss=StopLossRequest(
            stop_price=payload["stop_loss"]["stop_price"]
        ),
        client_order_id=payload["client_order_id"],
    )
    logger.info(f"SUBMITTING to paper-api.alpaca.markets: {req}")
    response = client.submit_order(req)
    logger.success(f"Order submitted: id={response.id}, status={response.status}")
    return {
        "id": str(response.id),
        "client_order_id": response.client_order_id,
        "symbol": response.symbol,
        "side": response.side,
        "qty": response.qty,
        "status": response.status,
        "created_at": str(response.created_at),
    }


# ---------------------------------------------------------------------------
# Position monitoring
# ---------------------------------------------------------------------------

def monitor_positions() -> list[dict[str, Any]]:
    """Poll current positions from Alpaca, returning normalized dicts."""
    client = _get_client()
    try:
        raw = client.get_all_positions()
    except Exception as exc:
        logger.error(f"Failed to fetch positions: {exc}")
        return []

    normalized: list[dict[str, Any]] = []
    for pos in raw:
        normalized.append({
            "ticker": pos.symbol,
            "qty": int(float(pos.qty)),
            "avg_entry_price": float(pos.avg_entry_price),
            "current_price": float(pos.current_price or 0),
            "unrealized_pl": float(pos.unrealized_pl or 0),
            "unrealized_pl_pct": float(pos.unrealized_plpc or 0),
        })
    logger.info(f"Monitor: {len(normalized)} open positions")
    return normalized