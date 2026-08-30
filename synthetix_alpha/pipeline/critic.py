"""Critic Agent — Senior Quantitative Risk Officer that evaluates trade setups.

Inputs: volatility metrics, technicals, company context (Finnhub), macro regime (FRED).
Output: strict ``CriticDecision`` (APPROVED / REJECTED) with thesis and risk factors.
"""

from __future__ import annotations

import logging
from typing import Optional

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
    decision: str = Field(default="APPROVED")
    confidence: int = Field(default=50, ge=1, le=100)
    regime_summary: str = ""
    thesis: str = ""
    risk_factors: list[str] = []
    suggested_size_multiplier: float = Field(default=1.0, ge=0.5, le=1.0)


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
3. REDUCE size (suggested_size_multiplier < 0.75) if high-yield credit spreads
   (HY OAS) > 400 bps (4.0) — credit stress.
4. REDUCE size if IV rank is below 0.30 — premium is not rich enough.
5. REJECT if analyst consensus is strongly negative (consensus < -0.5) AND
   insider sentiment is bearish (MSPR < -50).
6. REJECT if recent headlines flag a major regulatory, legal, or accounting
   event (words like "investigation", "lawsuit", "SEC", "restatement").
7. APPROVE when IV is in the top quartile (IV rank > 0.75), the yield curve
   is not in crisis territory, credit spreads are contained, and there are
   no red-flag headlines.

Output a JSON object with these fields:
- ticker: string
- decision: "APPROVED" or "REJECTED"
- confidence: 1-100
- regime_summary: 1-2 sentences summarising the macro regime
- thesis: 1-3 sentences on why this trade was approved or rejected
- risk_factors: list of specific risk items (empty if none)
- suggested_size_multiplier: 0.5-1.0, only reduce if risks are flagged
"""


class CriticAgent:
    """Evaluates trade setups against macro, fundamental, and technical signals.

    Parameters
    ----------
    llm : LLMClient or None
        LLM backend.  Creates a default ``LLMClient`` when omitted.
    """

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self._llm = llm or LLMClient()

    def evaluate(self, input_: CriticInput) -> CriticDecision:
        """Evaluate a single trade setup and return a structured decision."""
        user_prompt = self._build_prompt(input_)
        return self._llm.complete_structured(
            SYSTEM_PROMPT, user_prompt, CriticDecision, temperature=0.2
        )

    def evaluate_batch(self, inputs: list[CriticInput]) -> list[CriticDecision]:
        """Evaluate multiple setups sequentially."""
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