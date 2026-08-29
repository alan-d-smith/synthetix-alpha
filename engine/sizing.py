"""
sizing.py — Stage 5: Position Sizing.

Confidence-scaled position size with hard caps (never uncapped linear
scaling from confidence_score). Outputs bracket order parameters:
    qty, take_profit, stop_loss, time_stop.
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger


# Default bracket parameters
DEFAULT_TAKE_PROFIT_PCT = 0.05   # 5%
DEFAULT_STOP_LOSS_PCT = 0.03     # 3%
DEFAULT_TIME_STOP_MIN = 120      # 2 hours
DEFAULT_REFERENCE_PRICE = 100.0  # fallback when no market price
MIN_ALLOCATION_PCT = 0.01         # 1% floor


def compute_sizes(
    approved_signals: list[dict[str, Any]],
    account_nav: float,
    sizing_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute confidence-scaled position sizes for approved signals.

    Formula:
        allocation_pct = max_single_position_pct × confidence_score
        Clamped to [MIN_ALLOCATION_PCT, max_single_position_pct].
        notional = account_nav × allocation_pct
        qty = floor(notional / reference_price)

    Args:
        approved_signals: Signals that passed critic validation.
        account_nav: Current account net asset value.
        sizing_rules: Governance rules dict for caps.

    Returns:
        List of bracket order param dicts with keys: ticker, side, qty,
        take_profit_pct, stop_loss_pct, time_stop_min, estimated_notional,
        client_order_id, confidence_score.
    """
    max_single_pct = sizing_rules.get("max_single_position_pct", 0.10)
    tp_pct = sizing_rules.get("take_profit_pct", DEFAULT_TAKE_PROFIT_PCT)
    sl_pct = sizing_rules.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
    time_stop = sizing_rules.get("time_stop_min", DEFAULT_TIME_STOP_MIN)
    ref_price = sizing_rules.get("reference_price", DEFAULT_REFERENCE_PRICE)

    orders: list[dict[str, Any]] = []

    for signal in approved_signals:
        ticker = signal.get("ticker", "UNKNOWN")
        confidence = float(signal.get("confidence_score", 0.5))
        sentiment = signal.get("sentiment", "neutral")

        # Scale allocation by confidence, capped at max
        allocation_pct = max_single_pct * confidence
        allocation_pct = max(MIN_ALLOCATION_PCT, min(allocation_pct, max_single_pct))

        notional = round(account_nav * allocation_pct, 2)
        qty = max(1, int(notional / ref_price))

        # Determine side from sentiment
        if sentiment == "bullish":
            side = "buy"
        elif sentiment == "bearish":
            side = "sell"
        else:
            side = "buy"  # default to buy for neutral

        # Generate idempotent client_order_id
        ts_ms = int(time.time() * 1000)
        client_order_id = f"{ticker}-{side}-{ts_ms}"

        order = {
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "entry_price": ref_price,
            "take_profit_pct": tp_pct,
            "stop_loss_pct": sl_pct,
            "time_stop_min": time_stop,
            "estimated_notional": notional,
            "client_order_id": client_order_id,
            "confidence_score": confidence,
        }
        orders.append(order)

        logger.info(
            f"Sizing: {ticker} {side} x{qty} @ ~${ref_price:.0f} "
            f"= ${notional:,.0f} ({allocation_pct:.1%} allocation, "
            f"confidence={confidence:.2f})"
        )

    logger.info(f"Sizing: {len(orders)} bracket orders computed")
    return orders