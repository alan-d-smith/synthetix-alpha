"""Critic Agent — Senior Quantitative Risk Officer that evaluates trade setups.

Inputs: volatility metrics, technicals, company context (Finnhub), macro regime (FRED).
Output: strict ``CriticDecision`` (APPROVED / REJECTED) with thesis and risk factors.
"""

from __future__ import annotations

import logging
import statistics
from typing import Literal, Optional

from pydantic import BaseModel, Field

from synthetix_alpha.pipeline.llm import LLMClient

logger = logging.getLogger(__name__)


class CriticInput(BaseModel):
    """All data the critic needs to evaluate a single trade setup."""

    ticker: str

    # Volatility metrics (from screen.py / dolt)
    iv: float
    hv: float
    iv_rv: float
    iv_rank: float

    # Technicals (from strategy/data.py:technicals via gs-quant)
    rsi: Optional[float] = None
    bollinger_pos: Optional[float] = None
    macd: Optional[float] = None

    # Company context (from FinnhubClient)
    company_name: str = ""
    sector: str = ""
    market_cap: Optional[float] = None
    analyst_consensus: Optional[float] = None  # -2 .. +2
    insider_mspr: Optional[float] = None       # latest month
    recent_headlines: list[str] = []

    # Macro regime (from FredClient)
    yield_curve: Optional[float] = None   # T10Y2Y latest
    hy_spread: Optional[float] = None     # BAMLH0A0HYM2 latest
    nfci: Optional[float] = None          # NFCI latest


class CriticDecision(BaseModel):
    """Structured decision from the Critic Agent."""

    ticker: str
    decision: Literal["APPROVED", "REJECTED"] = Field(default="APPROVED")
    confidence: int = Field(default=50, ge=1, le=100)
    regime_summary: str = ""
    thesis: str = ""
    risk_factors: list[str] = []
    suggested_size_multiplier: Literal[0.5, 0.75, 1.0] = Field(default=1.0)


ENSEMBLE_RUNS: int = 3


SYSTEM_PROMPT = """\
You are a Senior Quantitative Risk Officer at a proprietary options trading desk.
Your job is to evaluate whether a proposed options premium-selling setup should
be approved given the current volatility regime, technical backdrop, company
fundamentals, and macroeconomic environment.

Rules you MUST follow:
1. REJECT if the setup is an earnings play and earnings are within 5 days
   (headlines mentioning "earnings", "EPS", "quarterly results").
2. REJECT if the yield curve is deeply inverted (T10Y2Y < -0.80) AND the NFCI
   is tightening (NFCI < -0.50) — recession risk.
3. REDUCE size (suggested_size_multiplier = 0.5) if high-yield credit spreads
   (HY OAS) > 400 bps (4.0) — credit stress.
4. REDUCE size (suggested_size_multiplier = 0.75) if IV rank is below 0.30 —
   premium is not rich enough.
5. REJECT if analyst consensus is strongly negative (consensus < -0.5) AND
   insider sentiment is bearish (MSPR < -50).
6. REJECT if recent headlines flag a major regulatory, legal, or accounting
   event (words like "investigation", "lawsuit", "SEC", "restatement").
7. APPROVE when IV is in the top quartile (IV rank > 0.75), the yield curve
   is not in crisis territory, credit spreads are contained, and there are
   no red-flag headlines.

## Few-Shot Examples (follow this exact format)

### Example 1 — APPROVED (low-risk premium-selling setup)

Input:
- Ticker: SPY
- IV: 35.0%  |  HV: 23.0%  |  IV/RV: 1.52  |  IV Rank: 0.82
- 10Y-2Y: 0.12%  |  HY OAS: 3.20%  |  NFCI: -0.150
- Sector: ETF  |  Analyst Consensus: N/A
- Recent Headlines: ["SPY tracks S&P 500, broad market strength"]

Output:
{"ticker": "SPY",
 "decision": "APPROVED",
 "confidence": 85,
 "regime_summary": "Yield curve is mildly positive, credit spreads are contained, and financial conditions are neutral. No macro stress signals.",
 "thesis": "IV rank at 0.82 is firmly in the top quartile with IV/RV at 1.52, confirming rich premium. The yield curve is not inverted, credit spreads are well below 400 bps, and there are no red-flag headlines. This is a textbook premium-selling opportunity.",
 "risk_factors": [],
 "suggested_size_multiplier": 1.0}

### Example 2 — REJECTED (regulatory red flag)

Input:
- Ticker: AAPL
- IV: 40.0%  |  HV: 28.0%  |  IV/RV: 1.43  |  IV Rank: 0.91
- 10Y-2Y: -0.15%  |  HY OAS: 3.80%  |  NFCI: 0.200
- Sector: Technology  |  Analyst Consensus: +0.80
- Recent Headlines: ["SEC opens investigation into Apple's App Store practices", "Apple reports strong iPhone sales"]

Output:
{"ticker": "AAPL",
 "decision": "REJECTED",
 "confidence": 95,
 "regime_summary": "Yield curve is slightly inverted and credit spreads are elevated but not critical. Financial conditions are neutral.",
 "thesis": "Despite strong IV rank (0.91) and rich IV/RV (1.43), the presence of an SEC investigation headline is an automatic rejection per Rule 6. Regulatory risk overrides all other positive signals.",
 "risk_factors": ["SEC investigation flagged in recent headlines", "regulatory overhang could cause unpredictable vol expansion"],
 "suggested_size_multiplier": 0.5}

Output a JSON object with these fields:
- ticker: string
- decision: "APPROVED" or "REJECTED" (exactly one of these two values)
- confidence: integer 1-100
- regime_summary: 1-2 sentences summarising the macro regime
- thesis: 1-3 sentences on why this trade was approved or rejected
- risk_factors: list of specific risk items (empty list if none)
- suggested_size_multiplier: one of 0.5, 0.75, or 1.0 (discrete values only)
"""


class CriticAgent:
    """Evaluates trade setups against macro, fundamental, and technical signals.

    Parameters
    ----------
    llm : LLMClient or None
        LLM backend.  Creates a default ``LLMClient`` when omitted.
    """

    _VALID_MULTIPLIERS: tuple[float, ...] = (0.5, 0.75, 1.0)

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self._llm = llm or LLMClient()

    def evaluate(self, input_: CriticInput) -> CriticDecision:
        """Evaluate a single trade setup and return a structured decision."""
        user_prompt = self._build_prompt(input_)
        return self._llm.complete_structured(
            SYSTEM_PROMPT, user_prompt, CriticDecision, temperature=0.0
        )

    def evaluate_with_consistency(self, input_: CriticInput) -> CriticDecision:
        """Run the critic ``ENSEMBLE_RUNS`` times and return the majority-vote decision.

        The final ``decision`` is the majority (2-of-3) vote.  ``confidence`` is
        the integer average across runs.  ``suggested_size_multiplier`` is
        averaged and then snapped to the nearest valid discrete value
        (0.5, 0.75, 1.0).  ``thesis``, ``regime_summary``, and ``risk_factors``
        are taken from the highest-confidence run.

        Returns
        -------
        CriticDecision
            Ensemble-aggregated decision.
        """
        decisions: list[CriticDecision] = []
        for i in range(ENSEMBLE_RUNS):
            d = self.evaluate(input_)
            decisions.append(d)
            logger.debug(
                "Consistency run %d/%d for %s: %s (conf=%d, mult=%.2f)",
                i + 1, ENSEMBLE_RUNS, input_.ticker,
                d.decision, d.confidence, d.suggested_size_multiplier,
            )

        # Majority vote on APPROVED / REJECTED
        approved = sum(1 for d in decisions if d.decision == "APPROVED")
        rejected = ENSEMBLE_RUNS - approved
        majority_decision = "APPROVED" if approved >= 2 else "REJECTED"

        logger.info(
            "Consistency ensemble for %s: %d/%d APPROVED → %s",
            input_.ticker, approved, ENSEMBLE_RUNS, majority_decision,
        )

        # Average confidence (integer)
        avg_conf = int(round(statistics.mean(d.confidence for d in decisions)))

        # Average multiplier, snapped to nearest valid discrete value
        avg_mult = statistics.mean(d.suggested_size_multiplier for d in decisions)
        snapped_mult = min(
            self._VALID_MULTIPLIERS,
            key=lambda v: abs(v - avg_mult),
        )

        # Use the highest-confidence run's text fields
        best = max(decisions, key=lambda d: d.confidence)

        return CriticDecision(
            ticker=input_.ticker,
            decision=majority_decision,
            confidence=avg_conf,
            regime_summary=best.regime_summary,
            thesis=best.thesis,
            risk_factors=best.risk_factors,
            suggested_size_multiplier=snapped_mult,
        )

    def evaluate_batch(
        self,
        inputs: list[CriticInput],
        *,
        consistency: bool = False,
    ) -> list[CriticDecision]:
        """Evaluate multiple setups sequentially.

        Parameters
        ----------
        inputs : list[CriticInput]
            Trade setups to evaluate.
        consistency : bool
            If ``True``, use ensemble voting (``evaluate_with_consistency``)
            for each input instead of a single evaluation.
        """
        if consistency:
            return [self.evaluate_with_consistency(inp) for inp in inputs]
        return [self.evaluate(inp) for inp in inputs]

    @staticmethod
    def _build_prompt(inp: CriticInput) -> str:
        lines = [
            f"## Trade Setup Evaluation: {inp.ticker}",
            "",
            "### Volatility Regime",
            f"- IV: {inp.iv:.1%}  |  HV: {inp.hv:.1%}  |  IV/RV: {inp.iv_rv:.2f}  |  IV Rank: {inp.iv_rank:.2f}",
            "",
        ]
        techs = []
        if inp.rsi is not None:
            techs.append(f"RSI={inp.rsi:.1f}")
        if inp.bollinger_pos is not None:
            techs.append(f"Bollinger={inp.bollinger_pos:.2f}")
        if inp.macd is not None:
            techs.append(f"MACD/spot={inp.macd:.4f}")
        if techs:
            lines += ["### Technicals", "  ".join(techs), ""]

        lines += [
            "### Company Context",
            f"- Name: {inp.company_name or inp.ticker}",
            f"- Sector: {inp.sector or 'N/A'}",
        ]
        if inp.market_cap:
            lines.append(f"- Market Cap: ${inp.market_cap:,.0f}")
        if inp.analyst_consensus is not None:
            lines.append(f"- Analyst Consensus: {inp.analyst_consensus:+.2f} (-2..+2)")
        if inp.insider_mspr is not None:
            lines.append(f"- Insider MSPR: {inp.insider_mspr:.1f}")
        if inp.recent_headlines:
            lines.append("- Recent Headlines:")
            for h in inp.recent_headlines[:5]:
                lines.append(f"  - {h}")
        lines.append("")

        lines += [
            "### Macroeconomic Regime",
            f"- 10Y-2Y Spread: {inp.yield_curve:.2f}%" if inp.yield_curve is not None else "- 10Y-2Y Spread: N/A",
            f"- HY OAS: {inp.hy_spread:.2f}%" if inp.hy_spread is not None else "- HY OAS: N/A",
            f"- NFCI: {inp.nfci:.3f}" if inp.nfci is not None else "- NFCI: N/A",
            "",
        ]
        return "\n".join(lines)