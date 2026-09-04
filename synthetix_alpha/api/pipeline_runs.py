"""Dry-run pipeline requests for the dashboard adapter."""

from __future__ import annotations

import datetime as dt
from typing import Any


def serialize_pipeline_result(result: Any) -> dict[str, Any]:
    """Convert PipelineResult into a JSON-safe dry-run response."""
    candidates = getattr(result, "candidates", None)
    if candidates is None:
        candidate_count = 0
    elif hasattr(candidates, "index"):
        candidate_count = int(len(candidates.index))
    else:
        candidate_count = int(len(candidates))

    decisions = list(getattr(result, "decisions", []) or [])
    approved = list(getattr(result, "approved_by_critic", []) or [])
    rejected = list(getattr(result, "rejected_by_critic", []) or [])
    formed = list(getattr(result, "formed_orders", []) or [])
    executions = list(getattr(result, "executions", []) or [])
    errors = [str(e) for e in (getattr(result, "errors", []) or [])]

    risk_decision = getattr(result, "risk_decision", None)
    risk_approved = list(getattr(risk_decision, "approved", []) or []) if risk_decision else []
    risk_halts = list(getattr(risk_decision, "halts", []) or []) if risk_decision else []

    timestamp = getattr(result, "timestamp", None)
    if isinstance(timestamp, dt.datetime):
        as_of = timestamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        as_of = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "dryRun": True,
        "status": "error" if errors and candidate_count == 0 and not decisions else "complete",
        "asOf": as_of,
        "summary": {
            "screened": candidate_count,
            "criticApproved": len(approved),
            "criticRejected": len(rejected),
            "formedOrders": len(formed),
            "riskApproved": len(risk_approved),
            "riskHalts": len(risk_halts),
            "executions": len(executions),
        },
        "critic": [
            {
                "ticker": getattr(d, "ticker", None),
                "decision": getattr(d, "decision", None),
                "confidence": getattr(d, "confidence", None),
            }
            for d in decisions
        ],
        "riskHalts": risk_halts,
        "executions": executions,
        "errors": errors,
        "detail": _detail_line(
            screened=candidate_count,
            approved=len(approved),
            risk_approved=len(risk_approved),
            halts=len(risk_halts),
            errors=errors,
        ),
    }


def _detail_line(
    *,
    screened: int,
    approved: int,
    risk_approved: int,
    halts: int,
    errors: list[str],
) -> str:
    if errors and screened == 0 and approved == 0:
        return f"Dry pipeline finished with errors: {errors[0]}"
    parts = [
        f"screened {screened}",
        f"critic-approved {approved}",
        f"risk-approved {risk_approved}",
        f"halts {halts}",
    ]
    suffix = f" Errors: {len(errors)}." if errors else " No live orders submitted."
    return "Dry pipeline complete — " + ", ".join(parts) + "." + suffix


def run_dry_pipeline(
    *,
    orchestrator_factory: Any | None = None,
    iv_rv_min: float = 1.25,
    limit: int = 15,
) -> dict[str, Any]:
    """Execute PipelineOrchestrator.run_daily with dry_run forced True."""
    if orchestrator_factory is None:
        from synthetix_alpha.pipeline.orchestrator import PipelineOrchestrator

        orchestrator_factory = PipelineOrchestrator

    orchestrator = orchestrator_factory()
    result = orchestrator.run_daily(iv_rv_min=iv_rv_min, limit=limit, dry_run=True)

    # Cache risk-approved formed orders for later operator paper submission.
    try:
        from synthetix_alpha.api.trades import cache_overview_trades

        cache_overview_trades(
            formed_orders=list(getattr(result, "formed_orders", []) or []),
            risk_decision=getattr(result, "risk_decision", None),
            critique_decisions=list(getattr(result, "decisions", []) or []),
        )
    except Exception:
        pass

    return serialize_pipeline_result(result)
