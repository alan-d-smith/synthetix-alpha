"""Build the dashboard overview snapshot from existing live modules."""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from synthetix_alpha.api.research import load_performance
from synthetix_alpha.api.ttl_cache import (
    CRITIQUE_TTL,
    GATHER_TTL,
    SCREEN_TTL,
    critique_cache,
    gather_cache,
    screen_cache,
)

_PIPELINE_STAGES = [
    ("SCREEN", "Screen"),
    ("GATHER", "Gather"),
    ("CRITIQUE", "Critique"),
    ("FORM", "Form"),
    ("RISK", "Risk"),
    ("EXECUTE", "Execute"),
]

_UNAVAILABLE_WARNINGS = [
    "Execution ledger is not available in adapter v1.",
    "Daily and total drawdown are not tracked for live paper NAV in adapter v1.",
    "Premium at risk for open positions is not computed in adapter v1.",
]

_DEFAULT_CONFIDENCE_THRESHOLD = 70


def _position_notional(positions: list[dict]) -> float:
    return sum(abs(float(p.get("qty", 0)) * float(p.get("avg_entry_price", 0))) for p in positions)


def _underlying(symbol: str, asset_class: str) -> str | None:
    if "option" in asset_class.lower():
        s = symbol.strip().upper()
        if len(s) >= 16 and s[-8:].isdigit() and s[-9] in "CP" and s[-15:-9].isdigit():
            return s[:-15]
        return None
    return symbol


def map_portfolio(
    account: dict,
    exposure: dict,
    rules: Any,
    *,
    as_of: str,
) -> tuple[dict[str, Any], list[str]]:
    """Map Alpaca account + exposure into PortfolioSnapshot fields."""
    warnings: list[str] = []
    positions_raw = exposure.get("positions") or []
    nav = float(exposure.get("nav") or account.get("equity") or 0)
    cash = float(exposure.get("cash") or account.get("cash") or 0)
    unprotected = {str(item.get("symbol", "")) for item in (exposure.get("unprotected") or [])}

    positions = []
    aggregate_unrealized = 0.0
    for pos in positions_raw:
        symbol = str(pos.get("symbol", ""))
        asset_class = str(pos.get("asset_class") or "us_equity")
        unrealized = float(pos.get("unrealized_pl") or 0)
        aggregate_unrealized += unrealized
        underlying = _underlying(symbol, asset_class)
        mapped = {
            "symbol": symbol,
            "quantity": float(pos.get("qty", 0)),
            "averageEntryPrice": float(pos.get("avg_entry_price", 0)),
            "unrealizedPnl": unrealized,
            "protected": symbol not in unprotected,
        }
        if underlying:
            mapped["underlying"] = underlying
        positions.append(mapped)

    premium_cap = nav * rules.max_premium_at_risk_pct if nav > 0 else 0.0
    remaining_leverage = max(nav * rules.max_leverage - _position_notional(positions_raw), 0.0)

    if account.get("buying_power") is not None:
        warnings.append("Buying power is available from Alpaca but is not shown in PortfolioSnapshot v1.")

    return {
        "nav": nav,
        "cash": cash,
        "aggregateUnrealizedPnl": aggregate_unrealized,
        "positions": positions,
        "maxPositions": rules.max_open_positions,
        "premiumAtRisk": 0.0,
        "premiumAtRiskCap": round(premium_cap, 2),
        "remainingLeverage": round(remaining_leverage, 2),
        "dailyDrawdown": None,
        "totalDrawdown": None,
        "hardHalt": None,
    }, warnings


def _vol_decimal(value: object) -> float:
    """Map screener IV/HV to frontend decimals (matches pipeline critic scaling)."""
    v = float(value)
    return v / 100.0 if v > 3.0 else v


def _nullable_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def _row_updated_at(row: object, as_of: str) -> str:
    import pandas as pd

    if not hasattr(row, "get"):
        return as_of
    raw = row.get("date")
    if raw is None or (isinstance(raw, float) and raw != raw):
        return as_of
    if isinstance(raw, dt.datetime):
        ts = raw if raw.tzinfo else raw.replace(tzinfo=dt.timezone.utc)
        return ts.isoformat().replace("+00:00", "Z")
    if isinstance(raw, dt.date):
        return dt.datetime.combine(raw, dt.time.min, tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(raw, pd.Timestamp):
        return raw.tz_convert("UTC").isoformat().replace("+00:00", "Z")
    return as_of


def _pending_critic(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "decision": "PENDING",
        "confidence": 0,
        "regimeSummary": "",
        "thesis": "Screener metrics only — critic has not evaluated this setup.",
        "riskFactors": [],
        "suggestedSizeMultiplier": 1.0,
    }


def map_candidates(df: object, *, as_of: str) -> list[dict[str, Any]]:
    """Map screen.candidates() DataFrame rows into frontend Candidate objects."""
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    out: list[dict[str, Any]] = []
    for ticker, row in df.iterrows():
        sym = str(ticker).upper()
        out.append({
            "ticker": sym,
            "company": "",
            "sector": "",
            "iv": _vol_decimal(row["iv"]),
            "hv": _vol_decimal(row["hv"]),
            "ivRv": float(row["iv_rv"]),
            "ivRank": float(row["iv_rank"]),
            "price": _nullable_float(row.get("price")),
            "avgDollarVolume": _nullable_float(row.get("avg_dollar_volume")),
            "critic": _pending_critic(sym),
            "risk": "UNAVAILABLE",
            "headlines": [],
            "analystConsensus": None,
            "insiderMspr": None,
            "updatedAt": _row_updated_at(row, as_of),
        })
    return out


def _screen_cache_key(candidates_fn: Callable[[], object]) -> str | None:
    """Only cache the live screener entry point — injected callables skip cache."""
    from synthetix_alpha.live.screen import candidates as screen_candidates

    if candidates_fn is screen_candidates:
        return "screen:live"
    return None


def load_candidates(
    *,
    as_of: str,
    candidates_fn: Callable[[], object] | None = None,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], object, list[str]]:
    """Run the live screener and map results, returning warnings on failure or empty scan."""
    import pandas as pd

    if candidates_fn is None:
        from synthetix_alpha.live.screen import candidates as screen_candidates

        candidates_fn = screen_candidates

    cache_key = _screen_cache_key(candidates_fn)

    def _load() -> tuple[list[dict[str, Any]], object, list[str]]:
        warnings: list[str] = []
        try:
            df = candidates_fn()
        except Exception as exc:
            return [], pd.DataFrame(), [f"Opportunity screener unavailable: {exc}"]

        mapped = map_candidates(df, as_of=as_of)
        if not mapped:
            warnings.append("Opportunity screener returned no candidates in regime today.")
        return mapped, df, warnings

    if use_cache and cache_key is not None:
        cached = screen_cache.get(cache_key, SCREEN_TTL)
        if cached is not None:
            mapped, df, warnings = cached
            return mapped, df, [*warnings, "Opportunity screener result served from in-process cache (45s TTL)."]
        result = _load()
        screen_cache.set(cache_key, result)
        return result
    return _load()


def _gather_cache_key(screen_df: object) -> str:
    import pandas as pd

    if screen_df is None or not isinstance(screen_df, pd.DataFrame) or screen_df.empty:
        return "gather:empty"
    tickers = ",".join(sorted(str(t).upper() for t in screen_df.index))
    return f"gather:{tickers}"


def _critique_cache_key(inputs: list[Any]) -> str:
    if not inputs:
        return "critique:empty"
    tickers = ",".join(sorted(str(getattr(inp, "ticker", "")).upper() for inp in inputs))
    return f"critique:{tickers}"


def _fetch_account_exposure(
    account_fn: Callable[[], dict],
    exposure_fn: Callable[[], dict],
) -> tuple[dict, dict]:
    """Fetch Alpaca account and exposure concurrently (independent read-only calls)."""
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="overview-alpaca") as pool:
        account_future = pool.submit(account_fn)
        exposure_future = pool.submit(exposure_fn)
        return account_future.result(), exposure_future.result()


def enrich_candidates_with_gather(
    candidates: list[dict[str, Any]],
    inputs: list[Any],
) -> list[dict[str, Any]]:
    """Merge pipeline GATHER output into screener-mapped candidate rows."""
    from synthetix_alpha.api.gather import critic_input_to_candidate_fields

    by_ticker = {str(inp.ticker).upper(): inp for inp in inputs}
    enriched: list[dict[str, Any]] = []
    for cand in candidates:
        merged = dict(cand)
        inp = by_ticker.get(str(cand["ticker"]).upper())
        if inp is not None:
            merged.update(critic_input_to_candidate_fields(inp))
            merged["critic"] = {
                **cand["critic"],
                "thesis": "Gathered company context — critic has not evaluated this setup.",
            }
        enriched.append(merged)
    return enriched


def apply_gather(
    candidates: list[dict[str, Any]],
    screen_df: object,
    *,
    gather_fn: Callable[[object], tuple[list[Any], list[str]]] | None = None,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[Any]]:
    """Run GATHER for screened candidates; return enriched rows, errors, warnings, and inputs."""
    if not candidates:
        return candidates, [], [], []

    using_default_gather = gather_fn is None
    if gather_fn is None:
        from synthetix_alpha.api.gather import run_gather

        gather_fn = run_gather

    cache_key = _gather_cache_key(screen_df)
    should_cache = use_cache and using_default_gather

    def _run() -> tuple[list[Any], list[str], list[str]]:
        try:
            inputs, errors = gather_fn(screen_df)
            return inputs, errors, []
        except Exception as exc:
            return [], [], [f"Gather unavailable: {exc}"]

    if should_cache:
        cached = gather_cache.get(cache_key, GATHER_TTL)
        if cached is not None:
            inputs, errors, cached_warnings = cached
        else:
            inputs, errors, cached_warnings = _run()
            gather_cache.set(cache_key, (inputs, errors, cached_warnings))
    else:
        inputs, errors, cached_warnings = _run()

    if inputs is None:
        inputs = []

    enriched = enrich_candidates_with_gather(candidates, inputs)
    warnings: list[str] = list(cached_warnings)
    if not inputs and errors:
        warnings.append("Gather returned no enriched candidates.")
    return enriched, errors, warnings, inputs


def enrich_candidates_with_critique(
    candidates: list[dict[str, Any]],
    decisions: list[Any],
) -> list[dict[str, Any]]:
    """Merge CriticDecision rows into candidates that were critiqued."""
    from synthetix_alpha.api.critique import critic_decision_to_frontend

    by_ticker = {str(decision.ticker).upper(): decision for decision in decisions}
    enriched: list[dict[str, Any]] = []
    for cand in candidates:
        merged = dict(cand)
        decision = by_ticker.get(str(cand["ticker"]).upper())
        if decision is not None:
            merged["critic"] = critic_decision_to_frontend(decision)
        enriched.append(merged)
    return enriched


def count_critique_buckets(
    decisions: list[Any],
    *,
    confidence_threshold: int = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[int, int]:
    """Match orchestrator approval semantics for pipeline summary counts."""
    approved = sum(
        1
        for decision in decisions
        if decision.decision == "APPROVED" and decision.confidence >= confidence_threshold
    )
    return approved, len(decisions) - approved


def apply_critique(
    candidates: list[dict[str, Any]],
    inputs: list[Any],
    *,
    critique_fn: Callable[[list[Any]], tuple[list[Any], str]] | None = None,
    confidence_threshold: int = _DEFAULT_CONFIDENCE_THRESHOLD,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[Any], str]:
    """Run CRITIQUE for gathered inputs; return enriched rows, errors, warnings, decisions, and mode."""
    if not inputs:
        return candidates, [], [], [], "none"

    using_default_critique = critique_fn is None
    if critique_fn is None:
        from synthetix_alpha.api.critique import run_critique

        critique_fn = lambda gathered: run_critique(gathered, consistency=False)

    cache_key = _critique_cache_key(inputs)
    should_cache = use_cache and using_default_critique

    def _run() -> tuple[list[Any], str]:
        return critique_fn(inputs)

    try:
        if should_cache:
            cached = critique_cache.get(cache_key, CRITIQUE_TTL)
            if cached is not None:
                decisions, mode = cached
            else:
                decisions, mode = _run()
                critique_cache.set(cache_key, (decisions, mode))
        else:
            decisions, mode = _run()
    except Exception as exc:
        return candidates, [f"CRITIQUE: {exc}"], [f"Critic unavailable: {exc}"], [], "none"

    warnings: list[str] = []
    if mode == "mock":
        from synthetix_alpha.api.critique import enrich_candidates_with_mock_critique

        enriched = enrich_candidates_with_mock_critique(candidates, inputs)
        warnings.append(
            "Critic decisions use mock LLM output (OPENAI_API_KEY not set or mock mode enabled)."
        )
        return enriched, [], warnings, [], "mock"

    enriched = enrich_candidates_with_critique(candidates, decisions)
    if not decisions:
        warnings.append("Critic returned no decisions for gathered candidates.")
    return enriched, [], warnings, decisions, "live"


def apply_form(
    screen_df: object,
    critique_decisions: list[Any],
    *,
    critique_mode: str,
    form_fn: Callable[[list[Any], object], list[dict]] | None = None,
    confidence_threshold: int = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[list[dict], list[str], list[str]]:
    """Run FORM for live critic approvals; skip mock/pending critique paths."""
    if critique_mode != "live" or not critique_decisions:
        return [], [], []

    from synthetix_alpha.api.form import filter_approved_decisions, run_form

    approved = filter_approved_decisions(
        critique_decisions,
        confidence_threshold=confidence_threshold,
    )
    if not approved:
        return [], [], []

    if form_fn is None:
        form_fn = run_form

    try:
        formed_orders = form_fn(approved, screen_df)
    except Exception as exc:
        return [], [f"FORM: {exc}"], [f"Order formation unavailable: {exc}"]

    return formed_orders, [], []


def apply_risk(
    formed_orders: list[dict],
    *,
    risk_fn: Callable[[list[dict]], Any] | None = None,
) -> tuple[Any, list[str], list[str], list[str]]:
    """Run RISK on formed orders; return decision, halts, warnings, and errors."""
    if not formed_orders:
        return None, [], [], []

    if risk_fn is None:
        from synthetix_alpha.api.risk_gate import run_risk

        risk_fn = run_risk

    try:
        decision = risk_fn(formed_orders)
    except Exception as exc:
        return None, [], [f"Risk gate unavailable: {exc}"], [f"RISK: {exc}"]

    halts = list(getattr(decision, "halts", []) or [])
    warnings: list[str] = []
    if halts:
        warnings.append(f"Risk gate halted {len(halts)} formed order(s).")
    return decision, halts, warnings, []


def _event_timestamp(as_of: str) -> str:
    if "T" in as_of:
        return as_of.split("T", 1)[1].replace("Z", "")[:8]
    return as_of


def build_pipeline_summary(
    *,
    as_of: str,
    screen_count: int,
    gathered_count: int,
    gather_errors: list[str],
    gathered_tickers: list[str],
    critique_decisions: list[Any] | None = None,
    critique_errors: list[str] | None = None,
    critique_mode: str = "none",
    formed_count: int = 0,
    form_errors: list[str] | None = None,
    risk_approved_count: int = 0,
    risk_halt_count: int = 0,
    risk_halts: list[str] | None = None,
    risk_errors: list[str] | None = None,
    confidence_threshold: int = _DEFAULT_CONFIDENCE_THRESHOLD,
    executable_count: int = 0,
    execution_status: str | None = None,
) -> dict[str, Any]:
    """Build a minimal live pipeline summary through CRITIQUE, FORM, and RISK."""
    pipeline_id = f"overview-{as_of[:19].replace(':', '').replace('-', '')}"
    screen_result = f"{screen_count} candidates" if screen_count else "no candidates"
    gather_result = f"{gathered_count} enriched" if gathered_count else "0 enriched"
    gather_status = "complete" if gathered_count else ("blocked" if screen_count else "pending")

    decisions = critique_decisions or []
    if critique_mode == "mock" and gathered_count:
        critique_result = f"{gathered_count} pending (mock critic)"
        critique_status = "pending"
    elif decisions:
        approved_count, rejected_count = count_critique_buckets(
            decisions,
            confidence_threshold=confidence_threshold,
        )
        critique_result = f"{approved_count} approved · {rejected_count} rejected (conf >= {confidence_threshold})"
        critique_status = "complete"
    elif gathered_count:
        critique_result = "0 critiqued"
        critique_status = "blocked" if critique_errors else "pending"
    else:
        critique_result = "Not available in adapter v1"
        critique_status = "pending"

    form_errors = form_errors or []
    risk_halts = risk_halts or []
    risk_errors = risk_errors or []
    if critique_mode == "mock" and gathered_count:
        form_result = "Not available (mock critic)"
        form_status = "pending"
        risk_result = "Not available (mock critic)"
        risk_status = "pending"
    elif critique_mode != "live":
        form_result = "Not available in adapter v1"
        form_status = "pending"
        risk_result = "Not available in adapter v1"
        risk_status = "pending"
    elif form_errors:
        form_result = "blocked"
        form_status = "blocked"
        risk_result = "Not available in adapter v1"
        risk_status = "pending"
    elif formed_count:
        form_result = f"{formed_count} orders formed"
        form_status = "complete"
        if risk_errors:
            risk_result = "blocked"
            risk_status = "blocked"
        elif risk_approved_count or risk_halt_count:
            risk_result = f"{risk_approved_count} approved · {risk_halt_count} halted"
            risk_status = "complete"
        else:
            risk_result = "Not available in adapter v1"
            risk_status = "pending"
    else:
        form_result = "0 orders formed"
        form_status = "complete" if screen_count else "pending"
        risk_result = "Not available in adapter v1"
        risk_status = "pending"

    stages: list[dict[str, Any]] = []
    for stage, label in _PIPELINE_STAGES:
        if stage == "SCREEN":
            stages.append({
                "stage": stage,
                "label": label,
                "result": screen_result,
                "status": "complete" if screen_count else "pending",
            })
        elif stage == "GATHER":
            stages.append({
                "stage": stage,
                "label": label,
                "result": gather_result,
                "status": gather_status if screen_count else "pending",
            })
        elif stage == "CRITIQUE":
            stages.append({
                "stage": stage,
                "label": label,
                "result": critique_result,
                "status": critique_status if screen_count else "pending",
            })
        elif stage == "FORM":
            stages.append({
                "stage": stage,
                "label": label,
                "result": form_result,
                "status": form_status if screen_count else "pending",
            })
        elif stage == "RISK":
            stages.append({
                "stage": stage,
                "label": label,
                "result": risk_result,
                "status": risk_status if screen_count else "pending",
            })
        else:
            if stage == "EXECUTE":
                ready = risk_approved_count > 0 and executable_count > 0
                if execution_status == "submitted":
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Submitted to Alpaca paper — awaiting broker confirmation",
                        "status": "complete",
                    })
                elif execution_status == "pending":
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Pending broker confirmation",
                        "status": "active",
                    })
                elif execution_status == "filled":
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Filled (Alpaca confirmed)",
                        "status": "complete",
                    })
                elif execution_status == "rejected":
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Rejected by broker",
                        "status": "blocked",
                    })
                elif execution_status == "error":
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Execution error",
                        "status": "blocked",
                    })
                elif ready:
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Ready for review — awaiting operator approval",
                        "status": "active",
                    })
                elif risk_approved_count > 0:
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Blocked — risk-approved but option legs unresolved",
                        "status": "blocked",
                    })
                elif formed_count > 0:
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "Blocked — order formed; risk gate did not approve",
                        "status": "blocked",
                    })
                else:
                    stages.append({
                        "stage": stage,
                        "label": label,
                        "result": "No order reached execution",
                        "status": "pending" if screen_count else "pending",
                    })
            else:
                stages.append({
                    "stage": stage,
                    "label": label,
                    "result": "Not available in adapter v1",
                    "status": "pending",
                })

    events = [
        {
            "id": f"gather-{index}",
            "timestamp": _event_timestamp(as_of),
            "stage": "GATHER",
            "ticker": ticker,
            "status": "complete",
            "detail": "Macro, company context, analyst and news inputs collected.",
        }
        for index, ticker in enumerate(gathered_tickers, start=1)
    ]
    if critique_mode == "mock" and gathered_tickers:
        events.extend(
            {
                "id": f"critique-{index}",
                "timestamp": _event_timestamp(as_of),
                "stage": "CRITIQUE",
                "ticker": ticker,
                "status": "pending",
                "detail": "Mock LLM output — no live critic evaluation.",
            }
            for index, ticker in enumerate(gathered_tickers, start=1)
        )
    else:
        events.extend(
            {
                "id": f"critique-{index}",
                "timestamp": _event_timestamp(as_of),
                "stage": "CRITIQUE",
                "ticker": decision.ticker,
                "status": "complete" if decision.decision == "APPROVED" else "blocked",
                "detail": decision.thesis or f"Critic decision: {decision.decision}.",
            }
            for index, decision in enumerate(decisions, start=1)
        )

    errors = list(gather_errors)
    if critique_errors:
        errors.extend(critique_errors)
    errors.extend(form_errors)
    errors.extend(risk_errors)
    errors.extend(risk_halts)
    if screen_count and not gathered_count and not errors:
        errors.append("GATHER: no candidates had enough data")

    return {
        "id": pipeline_id,
        "asOf": as_of,
        "mode": "paper",
        "finalState": "partial",
        "stages": stages,
        "events": events,
        "errors": errors,
    }


def empty_pipeline(as_of: str) -> dict[str, Any]:
    return {
        "id": "unavailable",
        "asOf": as_of,
        "mode": "paper",
        "finalState": "partial",
        "stages": [
            {
                "stage": stage,
                "label": label,
                "result": "Not available in adapter v1",
                "status": "pending",
            }
            for stage, label in _PIPELINE_STAGES
        ],
        "events": [],
        "errors": ["Pipeline history is not available in adapter v1."],
    }


def build_governance(rules: Any) -> list[dict[str, str]]:
    """Map runtime Rules (+ known config-only keys) into GovernanceControl rows."""
    max_positions = getattr(rules, "max_open_positions", None)
    premium_pct = getattr(rules, "max_premium_at_risk_pct", None)
    daily_dd = getattr(rules, "max_daily_drawdown_pct", None)
    total_dd = getattr(rules, "max_total_drawdown_pct", None)
    single_pct = getattr(rules, "max_single_position_pct", None)
    leverage = getattr(rules, "max_leverage", None)
    defined_risk = getattr(rules, "defined_risk_only", None)

    rows: list[dict[str, str]] = [
        {
            "name": "Max position slots",
            "value": str(max_positions) if max_positions is not None else "Unavailable",
            "state": "enforced",
            "detail": "Hard limit on concurrent option structures.",
        },
        {
            "name": "Premium at risk",
            "value": f"{premium_pct:.0%} of NAV" if isinstance(premium_pct, (int, float)) else "Unavailable",
            "state": "enforced",
            "detail": "Per-trade max loss versus account equity.",
        },
        {
            "name": "Daily drawdown halt",
            "value": f"{daily_dd:.0%}" if isinstance(daily_dd, (int, float)) else "Unavailable",
            "state": "enforced",
            "detail": "Blocks new risk when daily mark-to-market drawdown trips.",
        },
        {
            "name": "Total drawdown halt",
            "value": f"{total_dd:.0%}" if isinstance(total_dd, (int, float)) else "Unavailable",
            "state": "enforced",
            "detail": "Blocks new risk when peak-to-trough drawdown trips.",
        },
        {
            "name": "Single-position cap",
            "value": f"{single_pct:.0%} of NAV" if isinstance(single_pct, (int, float)) else "Unavailable",
            "state": "enforced",
            "detail": "Combined risk for one underlying versus NAV.",
        },
        {
            "name": "Max leverage",
            "value": f"{leverage:.2f}×" if isinstance(leverage, (int, float)) else "Unavailable",
            "state": "enforced",
            "detail": "Total notional versus account equity.",
        },
        {
            "name": "Defined-risk only",
            "value": "Required" if defined_risk is True else "Off" if defined_risk is False else "Unavailable",
            "state": "enforced",
            "detail": "Undefined-risk option structures are rejected.",
        },
        {
            "name": "Sector concentration",
            "value": "Configured",
            "state": "configured_not_enforced",
            "detail": "Present in governance.yaml; runtime does not enforce.",
        },
        {
            "name": "Weekly drawdown",
            "value": "Configured",
            "state": "configured_not_enforced",
            "detail": "Present in governance.yaml; runtime does not enforce.",
        },
        {
            "name": "Stop-loss / take-profit",
            "value": "Strategy research only",
            "state": "configured_not_enforced",
            "detail": "Backtest exit rules exist on strategy specs; live paper runtime does not auto-exit on SL/TP.",
        },
        {
            "name": "Paper trading only",
            "value": "Required",
            "state": "enforced",
            "detail": "Dashboard adapter accepts operator-approved paper submissions only.",
        },
    ]
    return rows


def empty_system(as_of: str, rules: Any | None = None) -> dict[str, Any]:
    return {
        "api": {
            "source": "Dashboard adapter",
            "asOf": as_of,
            "status": "fresh",
            "detail": "Portfolio overview v1",
        },
        "sources": [
            {
                "source": "Alpaca paper account",
                "asOf": as_of,
                "status": "fresh",
                "detail": "Account and positions via Alpaca CLI",
            }
        ],
        "warnings": ["Full system health probes are not implemented in adapter v1."],
        "governance": build_governance(rules) if rules is not None else [],
    }


def map_formed_order_to_frontend(order: dict[str, Any]) -> dict[str, Any]:
    """Map a pipeline formed-order dict into frontend Order fields."""
    from synthetix_alpha.api.leg_resolution import legs_are_executable

    legs = list(order.get("legs") or [])
    executable = bool(order.get("executable")) or legs_are_executable(legs)
    resolved = executable
    return {
        "symbol": str(order.get("symbol", "")),
        "legs": [
            {
                "symbol": str(leg.get("symbol", "")),
                "side": leg.get("side", "short"),
                "ratio": int(leg.get("ratio", 1)),
                "type": leg.get("type", "put"),
                "strike": leg.get("strike"),
                "delta": leg.get("delta"),
                "dteOffset": leg.get("dte_offset"),
                "resolved": bool(leg.get("resolved")) or (
                    executable and "OCC_PLACEHOLDER" not in str(leg.get("symbol", ""))
                ),
            }
            for leg in legs
            if isinstance(leg, dict)
        ],
        "contracts": int(order.get("contracts", 1)),
        "limitPrice": order.get("limit_price"),
        "clientOrderId": str(order.get("client_order_id", "")),
        "maxLoss": float(order.get("max_loss") or 0),
        "definedRisk": bool(order.get("defined_risk", True)),
        "confidence": int(order.get("confidence") or 0),
        "thesis": str(order.get("thesis") or ""),
        "structure": str(order.get("structure") or "put_credit_spread"),
        "resolution": "resolved" if resolved else ("placeholder" if legs else "unavailable"),
        "executable": executable,
    }


def attach_pipeline_outcomes(
    candidates: list[dict[str, Any]],
    *,
    formed_orders: list[dict],
    risk_decision: Any,
    risk_halts: list[str],
) -> list[dict[str, Any]]:
    """Merge FORM/RISK outcomes into candidate rows for truthful UI display."""
    orders_by_symbol = {str(order.get("symbol", "")).upper(): order for order in formed_orders}
    approved_symbols = {
        str(order.get("symbol", order.get("underlying", ""))).upper()
        for order in (getattr(risk_decision, "approved", []) or [])
    }

    def risk_for(sym: str) -> str | None:
        upper = sym.upper()
        if upper in approved_symbols:
            return "APPROVED"
        if any(upper in halt for halt in risk_halts):
            return "HALTED"
        if upper in orders_by_symbol:
            return "PENDING"
        return None

    enriched: list[dict[str, Any]] = []
    for cand in candidates:
        merged = dict(cand)
        sym = str(cand["ticker"]).upper()
        order = orders_by_symbol.get(sym)
        if order is not None:
            merged["order"] = map_formed_order_to_frontend(order)
        risk_status = risk_for(sym)
        if risk_status is not None:
            merged["risk"] = risk_status
        enriched.append(merged)
    return enriched


def build_overview(
    *,
    account_fn: Callable[[], dict] | None = None,
    exposure_fn: Callable[[], dict] | None = None,
    rules_loader: Callable[[], Any] | None = None,
    candidates_fn: Callable[[], object] | None = None,
    gather_fn: Callable[[object], tuple[list[Any], list[str]]] | None = None,
    critique_fn: Callable[[list[Any]], tuple[list[Any], str]] | None = None,
    form_fn: Callable[[list[Any], object], list[dict]] | None = None,
    risk_fn: Callable[[list[dict]], Any] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Assemble DashboardSnapshot JSON with a real portfolio slice."""
    if account_fn is None or exposure_fn is None or rules_loader is None:
        from synthetix_alpha.live import cli, execution, risk

        account_fn = account_fn or cli.account
        exposure_fn = exposure_fn or execution.open_exposure
        rules_loader = rules_loader or risk.Rules.load

    fetched_at = dt.datetime.now(dt.timezone.utc)
    as_of = fetched_at.isoformat().replace("+00:00", "Z")

    # Screen before Alpaca CLI account/position reads. The CLI path runs candidates()
    # with no prior account calls; hitting the CLI first can starve the SDK liquidity
    # fetch inside candidates() and yield an empty scan in the adapter only.
    candidates, screen_df, candidate_warnings = load_candidates(
        as_of=as_of,
        candidates_fn=candidates_fn,
        use_cache=use_cache,
    )
    screened_count = len(candidates)

    account, exposure = _fetch_account_exposure(account_fn, exposure_fn)
    rules = rules_loader()

    portfolio, portfolio_warnings = map_portfolio(account, exposure, rules, as_of=as_of)
    candidates, gather_errors, gather_warnings, gather_inputs = apply_gather(
        candidates,
        screen_df,
        gather_fn=gather_fn,
        use_cache=use_cache,
    )
    candidates, critique_errors, critique_warnings, critique_decisions, critique_mode = apply_critique(
        candidates,
        gather_inputs,
        critique_fn=critique_fn,
        use_cache=use_cache,
    )
    formed_orders, form_errors, form_warnings = apply_form(
        screen_df,
        critique_decisions,
        critique_mode=critique_mode,
        form_fn=form_fn,
    )
    if risk_fn is None:
        from synthetix_alpha.api.risk_gate import run_risk

        cached_exposure = exposure

        risk_fn = lambda orders: run_risk(
            orders,
            exposure_fn=lambda: cached_exposure,
            rules_loader=rules_loader,
        )
    risk_decision, risk_halts, risk_warnings, risk_errors = apply_risk(
        formed_orders,
        risk_fn=risk_fn,
    )
    risk_approved_count = len(getattr(risk_decision, "approved", []) or [])
    risk_halt_count = len(risk_halts)
    from synthetix_alpha.api.leg_resolution import legs_are_executable
    from synthetix_alpha.api.trades import cache_overview_trades
    from synthetix_alpha.api import trade_store

    executable_count = sum(
        1
        for order in (getattr(risk_decision, "approved", []) or [])
        if legs_are_executable(order.get("legs"))
    )
    cache_overview_trades(
        formed_orders=formed_orders,
        risk_decision=risk_decision,
        critique_decisions=critique_decisions,
        candidates=candidates,
    )
    candidates = attach_pipeline_outcomes(
        candidates,
        formed_orders=formed_orders,
        risk_decision=risk_decision,
        risk_halts=risk_halts,
    )
    gathered_tickers = [
        cand["ticker"]
        for cand in candidates
        if cand.get("company") or cand.get("headlines")
    ]
    recent_executions = trade_store.list_executions()
    latest_status = recent_executions[0]["status"] if recent_executions else None
    pipeline = build_pipeline_summary(
        as_of=as_of,
        screen_count=screened_count,
        gathered_count=len(gathered_tickers),
        gather_errors=gather_errors,
        gathered_tickers=gathered_tickers,
        critique_decisions=critique_decisions,
        critique_errors=critique_errors,
        critique_mode=critique_mode,
        formed_count=len(formed_orders),
        form_errors=form_errors,
        risk_approved_count=risk_approved_count,
        risk_halt_count=risk_halt_count,
        risk_halts=risk_halts,
        risk_errors=risk_errors,
        executable_count=executable_count,
        execution_status=latest_status,
    )
    performance, performance_warnings = load_performance()
    warnings = [
        "Paper trading account connected via dashboard adapter.",
        *_UNAVAILABLE_WARNINGS,
        *performance_warnings,
        *portfolio_warnings,
        *candidate_warnings,
        *gather_warnings,
        *critique_warnings,
        *form_warnings,
        *risk_warnings,
    ]

    return {
        "mode": "paper",
        "asOf": as_of,
        "warnings": warnings,
        "pipeline": pipeline,
        "candidates": candidates,
        "portfolio": portfolio,
        "executions": recent_executions,
        "performance": performance,
        "system": empty_system(as_of, rules),
    }
