# Strategy + Risk-Gate Write-Up

> Required for hackathon judging — keep this document updated with the
> current strategy rationale and risk-gate design.

## Strategy Overview

TODO: Describe the five-agent architecture and how each strategic lens
contributes to the final signal. Explain momentum vs. mean-reversion logic
and why isolating agents prevents signal dilution.

### Universe Selection

TODO: Explain the liquidity-based universe filter (avg $ volume + market
cap floor) and why a narrow, high-quality universe is preferred.

### Quant Engine (Stage 2)

TODO: Detail the 15m VWAP deviation, RVOL > 2, and RSI mean-reversion
signals. Explain why these indicators were chosen and how composite scoring
works.

### Research Agent (Stage 3)

TODO: Describe the LLM-driven research pipeline: FinBERT sentiment scoring
as a numeric feature, Finnhub news ingestion, and the fixed schema output.
Explain model selection (DeepSeek-V4-Pro or Qwen3.5-397B-A17B) rationale.

### Position Sizing (Stage 5)

TODO: Explain confidence-scaled sizing with hard caps and why uncapped
linear scaling was explicitly rejected.

## Risk-Gate Design

### Critic Layer (Stage 4)

TODO: List all deterministic validation rules and describe the rejection
logging mechanism.

### Risk Guard (Stage 6)

TODO: Detail the independent hard-cap enforcement layer: max single
position %, sector concentration, leverage limits, drawdown halts,
and options premium-at-risk constraints.

### Safety Guarantees

TODO: Enumerate all non-negotiable safety rules from .clinerules and
confirm they are enforced at every layer.

## Backtest Results

TODO: Summarize backtest results from the DoltHub options dataset
(post-no-preference/options, 2019-present) including key metrics
(Sharpe, max drawdown, win rate), known limitations, and survivorship
bias caveats.

## Options Component

TODO: Describe the end-to-end options workflow: IV rank computation
from DoltHub volatility_history, defined-risk vertical construction,
premium-at-risk enforcement, and paper-trading execution via Alpaca.