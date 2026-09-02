"""Reuse the pipeline RISK gate for the dashboard adapter."""

from __future__ import annotations

from typing import Any, Callable


def run_risk(
    formed_orders: list[dict],
    *,
    exposure_fn: Callable[[], dict] | None = None,
    rules_loader: Callable[[], Any] | None = None,
) -> Any:
    """Run formed orders through the deterministic risk gate (read-only)."""
    from synthetix_alpha.live import execution, risk

    if not formed_orders:
        return risk.Decision()

    exposure_fn = exposure_fn or execution.open_exposure
    rules_loader = rules_loader or risk.Rules.load

    exposure = exposure_fn()
    rules = rules_loader()
    return risk.apply(
        formed_orders,
        exposure.get("positions", []),
        float(exposure.get("nav") or 0.0),
        rules,
    )
