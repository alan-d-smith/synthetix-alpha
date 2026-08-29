# Architecture Diagram

> Data flow and component relationships for synthetix-alpha.

## Pipeline Stages (in order)

```
                        ┌──────────────────────┐
                        │  1. Universe Config   │
                        │  config/universe.yaml │
                        └──────────┬───────────┘
                                   │ ticker list
                                   ▼
                        ┌──────────────────────┐
                        │  2. Quant Screener    │
                        │  engine/quant         │
                        │  screener.py          │
                        │  (deterministic)      │
                        └──────────┬───────────┘
                                   │ screened tickers
                                   ▼
                        ┌──────────────────────┐
                        │  3. Research Agent    │
                        │  agents/research      │
                        │  agent.py             │
                        │  (LLM-driven)         │
                        └──────────┬───────────┘
                                   │ merged signals
                                   ▼
                        ┌──────────────────────┐
                        │  4. Critic / Validate │
                        │  engine/critic.py     │
                        │  (governance check)   │
                        └──────────┬───────────┘
                                   │ approved signals
                                   ▼
                        ┌──────────────────────┐
                        │  5. Position Sizing   │
                        │  engine/sizing.py     │
                        │  (confidence-scaled)  │
                        └──────────┬───────────┘
                                   │ sized orders
                                   ▼
                        ┌──────────────────────┐
                        │  6. Risk Guard        │
                        │  engine/risk_guard.py │
                        │  (hard cap enforce)   │
                        └──────────┬───────────┘
                                   │ final orders
                                   ▼
                        ┌──────────────────────┐
                        │  7. Execution         │
                        │  execution/           │
                        │  alpaca_client.py     │
                        │  (OCO bracket orders) │
                        └──────────────────────┘
```

## Data Sources

| Layer | Source | Purpose |
|---|---|---|
| Quant Engine (live) | Alpaca Market Data API | Bars, quotes, snapshots |
| Quant Engine (options) | Alpaca Options Data API | Chains, Greeks, IV |
| Quant Engine (macro) | FRED | VIX, yield curve, CPI, Fed funds |
| Quant Engine (backtest) | DoltHub `post-no-preference/options` | Historical options data 2019-present |
| Research Agent | Finnhub | News, insider sentiment, earnings |
| Sentiment Scoring | ProsusAI/finbert + finbert-tone | Local NLP classification |

## Module Separation

- `engine/` — All deterministic stages (2, 4, 5, 6). No LLM calls.
- `agents/` — Non-deterministic LLM-driven research (stage 3). Fully
  separate from quant_screener.py.
- `execution/` — Alpaca API interaction only (stage 7).
- `data/` — External API client wrappers. Data sources are abstracted
  behind their respective clients so the pipeline stages never call
  external APIs directly.
- `utils/` — Shared schemas (Pydantic), logging, and helpers.
- `config/` — Declarative YAML configuration. No code logic.

## Key Design Decisions

1. **Strict stage ordering**: No stage can skip its predecessor. This
   prevents an LLM from seeing the full universe (cost control) and
   guarantees governance gates run before any trade.
2. **Deterministic / non-deterministic separation**: `quant_screener.py`
   and `research_agent.py` are never merged. The LLM receives FinBERT
   scores as numeric features, not raw text alone.
3. **Two independent risk gates**: Stage 4 (critic) validates signal
   shape and governance compliance. Stage 6 (risk guard) enforces hard
   portfolio caps independently of sizing, creating defense-in-depth.
4. **Idempotent execution**: Every order submission uses a unique
   `client_order_id`. The position monitor rebuilds missing brackets,
   ensuring TP/SL protection is never absent.