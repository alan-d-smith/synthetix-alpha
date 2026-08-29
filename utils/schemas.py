"""
schemas.py — Pydantic data models for all pipeline contracts.

Defines the fixed schemas for signals, research output, bracket orders,
positions, and governance rules to ensure type safety across stages.
"""
from __future__ import annotations

from pydantic import BaseModel


class QuantSignal(BaseModel):
    """Stage 2 output: quant screener signal."""

    ticker: str
    vwap_deviation: float
    rvol: float
    rsi: float
    bollinger_position: float | None = None
    macd_signal: str | None = None
    composite_score: float = 0.0


class ResearchOutput(BaseModel):
    """Stage 3 output: fixed schema per ticker — never free-form text."""

    ticker: str
    sentiment: str  # bullish | bearish | neutral
    confidence_score: float  # 0.0 to 1.0
    thesis: str
    macro_alignment: str  # aligned | diverging | neutral


class BracketOrder(BaseModel):
    """Stage 5 output: bracket order parameters."""

    ticker: str
    side: str  # buy | sell
    qty: int
    entry_price: float | None = None
    take_profit_pct: float
    stop_loss_pct: float
    time_stop_min: int | None = None
    estimated_notional: float
    client_order_id: str
    confidence_score: float


class Position(BaseModel):
    """Current open position snapshot."""

    ticker: str
    qty: int
    avg_entry_price: float
    current_price: float
    unrealized_pl: float
    unrealized_pl_pct: float
    sector: str | None = None


class GovernanceRules(BaseModel):
    """Validated governance config from governance.yaml."""

    max_leverage: float = 1.0
    max_single_position_pct: float = 0.10
    max_sector_concentration_pct: float = 0.30
    max_open_positions: int = 10
    max_daily_drawdown_pct: float = 0.05
    max_weekly_drawdown_pct: float = 0.10
    max_total_drawdown_pct: float = 0.20
    defined_risk_only: bool = True
    max_premium_at_risk_pct: float = 0.02