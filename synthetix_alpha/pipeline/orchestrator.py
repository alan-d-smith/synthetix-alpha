"""End-to-end daily pipeline: screen -> gather -> critique -> form orders -> risk gate -> execute.

This is the single entry point that chains every component together while
enforcing the architectural firewall - LLM agents never touch the broker.

Usage::

    python -m synthetix_alpha.pipeline.orchestrator --dry-run
    python -m synthetix_alpha.pipeline.orchestrator --live --spec path/to/spec.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from synthetix_alpha.live import execution, risk, screen
from synthetix_alpha.pipeline.critic import CriticAgent, CriticInput, CriticDecision
from synthetix_alpha.pipeline.llm import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default strategy spec (put credit spread, 45 DTE, 0.30-delta short leg)
# ---------------------------------------------------------------------------

DEFAULT_SPEC = {
    "name": "default_put_credit_spread",
    "legs": [
        {"type": "put", "side": "short", "delta": 0.30, "ratio": 1},
        {"type": "put", "side": "long",  "delta": 0.15, "ratio": 1},
    ],
    "dte_target": 45,
    "dte_min": 30,
    "dte_max": 60,
    "risk_fraction": 0.02,
    "sizing": "max_loss",
    "min_credit": 0.15,
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Complete output of a daily pipeline run."""

    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)
    decisions: list[CriticDecision] = field(default_factory=list)
    approved_by_critic: list[CriticDecision] = field(default_factory=list)
    rejected_by_critic: list[CriticDecision] = field(default_factory=list)
    formed_orders: list[dict] = field(default_factory=list)
    risk_decision: Optional[risk.Decision] = None
    executions: list[dict] = field(default_factory=list)
    timestamp: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    errors: list[str] = field(default_factory=list)
class PipelineOrchestrator:
    """Runs the full daily trading pipeline from screen through execution.

    Parameters
    ----------
    finnhub : FinnhubClient or None
        Pre-configured Finnhub client; lazy-inits from env when absent.
    fred : FredClient or None
        Pre-configured FRED client; lazy-inits from env when absent.
    llm : LLMClient or None
        LLM backend; lazy-inits from env when absent.
    spec : Spec or dict or None
        Strategy spec.  Defaults to a put credit spread.
    mock_llm : bool
        Force mock mode for the LLM (useful for dry-run CI).
    confidence_threshold : int
        Minimum critic confidence (0-100) to pass a candidate through.
    """

    def __init__(
        self,
        finnhub: object = None,
        fred: object = None,
        llm: Optional[LLMClient] = None,
        spec: object = None,
        *,
        mock_llm: bool = False,
        confidence_threshold: int = 70,
    ) -> None:
        self._finnhub = finnhub
        self._fred = fred
        self._llm = llm or LLMClient(mock=mock_llm)
        self._critic = CriticAgent(llm=self._llm)
        self._spec = spec
        self._confidence_threshold = confidence_threshold

    def _get_finnhub(self) -> object:
        if self._finnhub is None:
            from synthetix_alpha.data.finnhub_client import FinnhubClient
            self._finnhub = FinnhubClient()
        return self._finnhub

    def _get_fred(self) -> object:
        if self._fred is None:
            from synthetix_alpha.data.fred_client import FredClient
            self._fred = FredClient()
        return self._fred

    def _get_spec(self) -> object:
        if self._spec is None:
            from synthetix_alpha.strategy.spec import Spec
            self._spec = Spec.from_dict(DEFAULT_SPEC)
        elif isinstance(self._spec, dict):
            from synthetix_alpha.strategy.spec import Spec
            self._spec = Spec.from_dict(self._spec)
        return self._spec
# ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run_daily(
        self,
        iv_rv_min: float = 1.25,
        limit: int = 15,
        *,
        dry_run: bool = True,
    ) -> PipelineResult:
        """Execute the full daily pipeline: screen -> gather -> critique -> form -> risk -> execute."""
        result = PipelineResult()

        # Phase 1 - SCREEN
        try:
            result.candidates = screen.candidates(iv_rv_min=iv_rv_min, limit=limit)
        except Exception as exc:
            result.errors.append(f"SCREEN: {exc}")
            logger.error("Screen phase failed: %s", exc)
            return result

        if result.candidates.empty:
            logger.info("No candidates in regime today - pipeline complete")
            return result

        tickers = list(result.candidates.index)
        logger.info("Phase 1 SCREEN: %d candidates", len(tickers))

        # Phase 2 - GATHER context
        macro = self._gather_macro(result)
        inputs = self._gather_per_ticker(result, tickers, macro)

        if not inputs:
            result.errors.append("GATHER: no candidates had enough data")
            return result

        # Phase 3 - CRITIQUE (with ensemble consistency + confidence threshold)
        try:
            raw_decisions = self._critic.evaluate_batch(inputs, consistency=True)
            result.approved_by_critic = [
                d for d in raw_decisions
                if d.decision == "APPROVED"
                and d.confidence >= self._confidence_threshold
            ]
            result.rejected_by_critic = [
                d for d in raw_decisions
                if d.decision != "APPROVED"
                or d.confidence < self._confidence_threshold
            ]
            result.decisions = raw_decisions
            logger.info(
                "Phase 3 CRITIQUE (ensemble): %d approved (conf >= %d), %d rejected",
                len(result.approved_by_critic),
                self._confidence_threshold,
                len(result.rejected_by_critic),
            )
        except Exception as exc:
            result.errors.append(f"CRITIQUE: {exc}")
            logger.error("Critique phase failed: %s", exc)
            return result

        if not result.approved_by_critic:
            logger.info("No critic-approved candidates - pipeline complete")
            return result

        # Phase 4 - FORM ORDERS
        try:
            result.formed_orders = self._form_orders(
                result.approved_by_critic, result.candidates
            )
        except Exception as exc:
            result.errors.append(f"FORM: {exc}")
            logger.error("Order formation failed: %s", exc)
            return result

        if not result.formed_orders:
            logger.info("No orders could be formed - pipeline complete")
            return result

        logger.info("Phase 4 FORM: %d orders constructed", len(result.formed_orders))

        # Phase 5 - RISK GATE
        try:
            result.risk_decision = self._apply_risk_gate(result.formed_orders)
        except Exception as exc:
            result.errors.append(f"RISK: {exc}")
            logger.error("Risk gate failed: %s", exc)
            return result

        # Phase 6 - EXECUTE
        if not dry_run and result.risk_decision and result.risk_decision.approved:
            try:
                result.executions = self._execute_orders(
                    result.risk_decision.approved, dry_run=False
                )
            except Exception as exc:
                result.errors.append(f"EXECUTE: {exc}")
# ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _gather_macro(self, result: PipelineResult) -> dict:
        """Fetch latest macro snapshot; returns a dict of {key: latest_value}."""
        try:
            fred = self._get_fred()
            df = fred.get_macro_snapshot()
            if df.empty:
                return {}
            latest = df.iloc[-1]

            def _safe_float(val: object) -> float:
                try:
                    f = float(val)
                    return f if f == f else float("nan")
                except (ValueError, TypeError):
                    return float("nan")

            return {
                "yield_curve": _safe_float(latest.get("t10y2y")),
                "hy_spread": _safe_float(latest.get("hy_oas")),
                "nfci": _safe_float(latest.get("nfci")),
            }
        except Exception as exc:
            result.errors.append(f"MACRO: {exc}")
            logger.warning("Macro data fetch failed - continuing without: %s", exc)
            return {}

    def _gather_per_ticker(
        self,
        result: PipelineResult,
        tickers: list[str],
        macro: dict,
    ) -> list[CriticInput]:
        """Build CriticInput objects for each candidate ticker."""
        finnhub = self._get_finnhub()
        inputs: list[CriticInput] = []

        for ticker in tickers:
            try:
                profile = finnhub.company_profile(ticker)
                news = finnhub.company_news(ticker)
                recommendations = finnhub.recommendation_trends(ticker)
                insider = finnhub.insider_sentiment(ticker)

                name = profile.iloc[0]["name"] if not profile.empty else ticker
                sector = profile.iloc[0].get("finnhub_industry", "") if not profile.empty else ""

                consensus = None
                if not recommendations.empty and "consensus_score" in recommendations.columns:
                    consensus = float(recommendations.iloc[-1]["consensus_score"])

                mspr = None
                if not insider.empty and "mspr" in insider.columns:
                    mspr = float(insider.iloc[-1]["mspr"])

                headlines = []
                if not news.empty:
                    headlines = list(news["headline"].head(5))

                iv = float(result.candidates.at[ticker, "iv"]) / 100.0 if "iv" in result.candidates.columns else 0.0
                hv = float(result.candidates.at[ticker, "hv"]) / 100.0 if "hv" in result.candidates.columns else 0.0
                iv_rv = float(result.candidates.at[ticker, "iv_rv"]) if "iv_rv" in result.candidates.columns else 0.0
                iv_rank = float(result.candidates.at[ticker, "iv_rank"]) if "iv_rank" in result.candidates.columns else 0.0

                inp = CriticInput(
                    ticker=ticker,
                    iv=iv if not (iv != iv) else 0.0,
                    hv=hv if not (hv != hv) else 0.0,
                    iv_rv=iv_rv if not (iv_rv != iv_rv) else 0.0,
                    iv_rank=iv_rank if not (iv_rank != iv_rank) else 0.0,
                    company_name=name,
                    sector=sector or "",
                    analyst_consensus=consensus,
                    insider_mspr=mspr,
                    recent_headlines=headlines,
                    **{k: (v if not (isinstance(v, float) and v != v) else None)
                       for k, v in macro.items()},
                )
                inputs.append(inp)
            except Exception as exc:
                result.errors.append(f"GATHER {ticker}: {exc}")
    def _form_orders(
        self,
        approved: list[CriticDecision],
        candidates: pd.DataFrame,
    ) -> list[dict]:
        """Convert critic decisions into option order dicts with leg structures.

        Resolves strategy legs (delta/moneyness/width) against the option chain.
        When chain data is unavailable, records the leg descriptions as abstract
        placeholders so the pipeline still validates through risk/execution.
        """
        spec = self._get_spec()
        orders: list[dict] = []

        for d in approved:
            ticker = d.ticker
            legs = self._resolve_legs(spec, ticker, candidates)
            coid = execution.client_order_id(legs) if legs else ""
            max_loss = 2000.0 * d.suggested_size_multiplier

            order = {
                "symbol": ticker,
                "legs": legs,
                "contracts": 1,
                "limit_price": 0.0,
                "client_order_id": coid,
                "defined_risk": True,
                "max_loss": max_loss,
                "confidence": d.confidence,
                "thesis": d.thesis,
            }
            orders.append(order)
            logger.info(
                "Formed order %s: %d legs, max_loss=%.0f, coid=%s",
                ticker, len(legs), max_loss, coid or "(pending)",
            )

        return orders

    @staticmethod
    def _resolve_legs(
        spec: object,
        ticker: str,
        candidates: pd.DataFrame,
    ) -> list[dict]:
        """Attempt to resolve abstract leg definitions to concrete OCC symbols.

        When the option chain is not available (no kaggle/dolt data loaded),
        returns abstract leg descriptions with OCC symbols set as placeholders.
        The execution gateway logs a clear warning and skips these orders,
        preserving the architectural firewall.
        """
        abstract_legs: list[dict] = []
        for leg in spec.legs:
            if leg.type == "stock":
                abstract_legs.append({
                    "symbol": ticker,
                    "side": leg.side,
                    "ratio": leg.ratio,
                    "type": "stock",
                })
            else:
                abstract_legs.append({
                    "symbol": f"{ticker}_OCC_PLACEHOLDER",
                    "side": leg.side,
                    "ratio": leg.ratio,
                    "type": leg.type,
                    "delta": leg.delta,
                    "moneyness": leg.moneyness,
                    "width": leg.width,
                    "dte_offset": leg.dte_offset,
                })

        # Try to resolve via strategy engine chain data if available
        try:
            from synthetix_alpha.strategy.data import build as build_chain

            chains, features = build_chain(ticker, source="dolt")
            if chains.empty:
                return abstract_legs

            # Find the nearest expiration matching the spec's DTE target
            chains_df = chains.reset_index()
            chains_df["dte"] = (
                pd.to_datetime(chains_df["expiration"])
                - pd.to_datetime(chains_df["date"])
            ).dt.days
            target_dte = getattr(spec, "dte_target", 45)
            near = chains_df[chains_df["dte"].between(target_dte - 10, target_dte + 10)]
            if near.empty:
                return abstract_legs

            latest_date = near["date"].max()
            latest = near[near["date"] == latest_date]
            spot = float(latest["underlying_price"].iloc[0])

            resolved: list[dict] = []
            for leg in spec.legs:
                if leg.type == "stock":
                    resolved.append({
                        "symbol": ticker,
                        "side": leg.side,
                        "ratio": leg.ratio,
                        "type": "stock",
                    })
                    continue

                # Determine strike
                strike = None
                if leg.delta is not None:
                    opts = latest[latest["type"] == leg.type].copy()
                    opts["dist"] = (opts["delta"].abs() - abs(leg.delta)).abs()
                    row = opts.nsmallest(1, "dist").iloc[0]
                    strike = float(row["strike"])
                elif leg.moneyness is not None:
                    strike = spot * (1 + leg.moneyness)
                elif leg.width is not None and resolved:
                    prev_strike = resolved[-1].get("strike", spot)
                    strike = prev_strike + leg.width

                if strike is None:
                    continue

                resolved.append({
                    "symbol": f"{ticker}_OCC_RESOLVED",
                    "side": leg.side,
                    "ratio": leg.ratio,
                    "type": leg.type,
                    "strike": strike,
                    "dte_offset": leg.dte_offset,
                })

            return resolved if resolved else abstract_legs

        except Exception:
            logger.debug(
                "Chain resolution unavailable for %s - using abstract legs", ticker
            )
            return abstract_legs

    def _apply_risk_gate(self, orders: list[dict]) -> object:
        """Run formed orders through the deterministic risk gate."""
        rules = risk.Rules.load()
        exp = execution.open_exposure()
        decision = risk.apply(
            orders,
            exp.get("positions", []),
            exp.get("nav", 100_000.0),
            rules,
        )
        approved_count = len(decision.approved)
        halt_count = len(decision.halts)
        logger.info(
            "Phase 5 RISK: %d approved, %d halted", approved_count, halt_count
        )
        for h in decision.halts:
            logger.warning("  %s", h)
        return decision

    def _execute_orders(self, orders: list[dict], *, dry_run: bool) -> list[dict]:
        """Submit risk-approved orders via execution.submit().

        Orders with abstract/placeholder legs are skipped with a clear warning.
        Orders with resolved OCC legs use the deterministic client_order_id
        from the formed order dict.
        """
        results: list[dict] = []
        for o in orders:
            legs = o.get("legs") or []
            contracts = o.get("contracts", 1)
            limit_price = o.get("limit_price", 0.0)
            coid = o.get("client_order_id", "")
            symbol = o.get("symbol", "?")

            # Check if any leg is a placeholder
            has_placeholder = any(
                "_OCC_PLACEHOLDER" in str(l.get("symbol", "")) for l in legs
            )
            if not legs or has_placeholder:
                logger.warning(
                    "Skipping execution for %s - no resolved option legs "
                    "(run through strategy engine with chain data first)",
                    symbol,
                )
                results.append({
                    "symbol": symbol,
                    "client_order_id": coid or "pending",
                    "status": "skipped_no_legs",
                    "detail": "resolve legs via strategy engine before live execution",
                })
# ---------------------------------------------------------------------------
# CLI entry point:  python -m synthetix_alpha.pipeline.orchestrator --dry-run
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    """Parse CLI args and run the daily pipeline."""
    p = argparse.ArgumentParser(
        prog="synthetix-alpha-pipeline",
        description="Run the full daily options trading pipeline.",
    )
    p.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Skip live order submission (default: True)",
    )
    p.add_argument(
        "--live", action="store_true",
        help="Allow live execution (overrides --dry-run)",
    )
    p.add_argument(
        "--mock-llm", action="store_true",
        help="Force mock LLM mode (no API key required)",
    )
    p.add_argument(
        "--iv-rv-min", type=float, default=1.25,
        help="Minimum IV/RV ratio for screening (default: 1.25)",
    )
    p.add_argument(
        "--limit", type=int, default=15,
        help="Max candidates (default: 15)",
    )
    p.add_argument(
        "--confidence", type=int, default=70,
        help="Minimum critic confidence 1-100 (default: 70)",
    )
    p.add_argument(
        "--spec", type=str, default=None,
        help="Path to strategy spec JSON (default: built-in put credit spread)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    args = p.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load spec if provided
    spec = None
    if args.spec:
        from synthetix_alpha.strategy.spec import Spec
        spec = Spec.load(args.spec)
        logger.info("Loaded spec: %s (%d legs)", spec.name, len(spec.legs))

    dry_run = not args.live  # --live overrides default --dry-run

    logger.info(
        "Starting pipeline: iv_rv_min=%.2f limit=%d confidence=%d dry_run=%s",
        args.iv_rv_min, args.limit, args.confidence, dry_run,
    )

    orch = PipelineOrchestrator(
        mock_llm=args.mock_llm,
        spec=spec,
        confidence_threshold=args.confidence,
    )

    result = orch.run_daily(
        iv_rv_min=args.iv_rv_min,
        limit=args.limit,
        dry_run=dry_run,
    )

    # Print summary
    print()
    print("=" * 60)
    print(f"Pipeline complete at {result.timestamp.isoformat()}")
    print(f"  Candidates screened:    {len(result.candidates)}")
    print(f"  Approved by critic:     {len(result.approved_by_critic)}")
    print(f"  Rejected by critic:     {len(result.rejected_by_critic)}")
    print(f"  Orders formed:          {len(result.formed_orders)}")
    risk_r = result.risk_decision
    print(f"  Approved by risk gate:  {len(risk_r.approved) if risk_r else 0}")
    print(f"  Halted by risk gate:    {len(risk_r.halts) if risk_r else 0}")
    print(f"  Executed (live):        {len(result.executions)}")
    print(f"  Errors:                 {len(result.errors)}")
    if result.errors:
        print("  Errors detail:")
        for e in result.errors:
            print(f"    - {e}")
    if risk_r and risk_r.halts:
        print("  Risk halts:")
        for h in risk_r.halts:
            print(f"    - {h}")
    print("=" * 60)


if __name__ == "__main__":
    main()
