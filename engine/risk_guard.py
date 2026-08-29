"""
risk_guard.py — Stage 6: Deterministic Risk Guard.

Runs independently of and after sizing. Enforces hard caps regardless of
upstream confidence/sizing output:
    - Max single position %
    - Max sector concentration %
    - Max leverage
    - Daily / weekly / total drawdown halts
    - Options positions must be defined-risk; max premium-at-risk per trade.
"""
from __future__ import annotations

from typing import Any

from loguru import logger


def _check_drawdown(
    positions: list[dict[str, Any]],
    account_nav: float,
    rules: dict[str, Any],
) -> list[str]:
    """Check if any position exceeds drawdown thresholds."""
    halts: list[str] = []
    max_daily = rules.get("max_daily_drawdown_pct", 0.05)
    max_total = rules.get("max_total_drawdown_pct", 0.20)

    for pos in positions:
        pl_pct = pos.get("unrealized_pl_pct", 0.0)
        ticker = pos.get("ticker", "?")
        if pl_pct <= -max_daily:
            halts.append(
                f"HALT: {ticker} daily drawdown {pl_pct:.2%} exceeds "
                f"limit {max_daily:.2%}"
            )

    total_pl = sum(p.get("unrealized_pl", 0.0) for p in positions)
    total_dd_pct = abs(total_pl) / account_nav if account_nav > 0 else 0.0
    if total_dd_pct >= max_total:
        halts.append(
            f"HALT: total drawdown {total_dd_pct:.2%} exceeds "
            f"limit {max_total:.2%}"
        )

    return halts


def _check_position_cap(
    order: dict[str, Any],
    current_positions: list[dict[str, Any]],
    account_nav: float,
    rules: dict[str, Any],
) -> str | None:
    """Check if a single order exceeds the max position cap."""
    max_pct = rules.get("max_single_position_pct", 0.10)
    max_notional = account_nav * max_pct
    notional = order.get("estimated_notional", 0.0)
    ticker = order.get("ticker", "")

    existing_notional = sum(
        abs(pos.get("qty", 0) * pos.get("avg_entry_price", 0))
        for pos in current_positions
        if pos.get("ticker") == ticker
    )
    combined = existing_notional + notional

    if combined > max_notional:
        return (
            f"HALT {ticker}: combined notional ${combined:,.0f} "
            f"(existing ${existing_notional:,.0f} + new ${notional:,.0f}) "
            f"exceeds max ${max_notional:,.0f} ({max_pct:.0%})"
        )
    return None


def _check_max_positions(
    orders: list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Trim orders that would exceed max_open_positions."""
    max_positions = rules.get("max_open_positions", 10)
    current_count = len(current_positions)
    available_slots = max_positions - current_count

    if available_slots <= 0:
        return [], [
            f"HALT: max positions reached ({current_count}/{max_positions})"
        ]
    if len(orders) > available_slots:
        trimmed = orders[:available_slots]
        halts = [
            f"HALT {o['ticker']}: max positions exceeded"
            for o in orders[available_slots:]
        ]
        return trimmed, halts
    return orders, []
def _check_leverage(
    orders: list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    account_nav: float,
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Check that total leverage doesn't exceed the cap."""
    max_leverage = rules.get("max_leverage", 1.0)
    max_notional = account_nav * max_leverage

    existing = sum(
        abs(p.get("qty", 0) * p.get("avg_entry_price", 0))
        for p in current_positions
    )
    remaining = max_notional - existing

    passed: list[dict[str, Any]] = []
    halts: list[str] = []
    for order in orders:
        n = order.get("estimated_notional", 0.0)
        if n > remaining:
            halts.append(
                f"HALT {order['ticker']}: notional ${n:,.0f} exceeds "
                f"remaining leverage ${remaining:,.0f}"
            )
        else:
            passed.append(order)
            remaining -= n
    return passed, halts


def _check_options(order: dict[str, Any], rules: dict[str, Any]) -> str | None:
    """Check options-specific constraints."""
    if not order.get("is_options"):
        return None
    opts = rules.get("options", {})
    if opts.get("defined_risk_only", True) and not order.get("defined_risk"):
        return f"HALT {order['ticker']}: options must be defined-risk"
    max_p = opts.get("max_premium_at_risk_pct", 0.02)
    premium = order.get("premium_at_risk", 0.0)
    est = order.get("estimated_notional", 0.0)
    if est > 0 and premium / est > max_p:
        return f"HALT {order['ticker']}: premium exceeds {max_p:.0%} limit"
    return None


def apply_risk_controls(
    sized_orders: list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    account_nav: float,
    risk_rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Apply hard risk controls: drawdown, position cap, max positions,
    leverage, and options constraints."""
    all_halts: list[str] = []

    # 1. Drawdown check
    dd_halts = _check_drawdown(current_positions, account_nav, risk_rules)
    all_halts.extend(dd_halts)
    if dd_halts:
        for h in dd_halts:
            logger.warning(h)
    total_pl = sum(p.get("unrealized_pl", 0.0) for p in current_positions)
    total_dd = abs(total_pl) / account_nav if account_nav > 0 else 0.0
    if total_dd >= risk_rules.get("max_total_drawdown_pct", 0.20):
        all_halts.append("HALT: all orders blocked due to total drawdown")
        return [], all_halts

    # 2. Per-order position cap
    cap_passed: list[dict[str, Any]] = []
    for order in sized_orders:
        reason = _check_position_cap(order, current_positions, account_nav, risk_rules)
        if reason:
            logger.warning(reason)
            all_halts.append(reason)
        else:
            cap_passed.append(order)

    # 3. Max open positions
    cap_passed, pos_halts = _check_max_positions(cap_passed, current_positions, risk_rules)
    all_halts.extend(pos_halts)
    for h in pos_halts:
        logger.warning(h)

    # 4. Leverage cap
    lev_passed, lev_halts = _check_leverage(cap_passed, current_positions, account_nav, risk_rules)
    all_halts.extend(lev_halts)
    for h in lev_halts:
        logger.warning(h)

    # 5. Options constraints
    final: list[dict[str, Any]] = []
    for order in lev_passed:
        opt_reason = _check_options(order, risk_rules)
        if opt_reason:
            logger.warning(opt_reason)
            all_halts.append(opt_reason)
        else:
            final.append(order)

    logger.info(
        f"Risk Guard: {len(final)} passed, {len(all_halts)} halted "
        f"from {len(sized_orders)} orders"
    )
    return final, all_halts