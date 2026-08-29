# Strategy research: how the deployed rule was found

Agent-designed, deterministically executed. LLM agents generate and mutate **strategy specs** (declarative JSON);
a frozen deterministic backtester scores them. No model sits in the live order path.

## Method

1. **Spec DSL** (`synthetix_alpha/strategy/spec.py`) — legs by delta/moneyness/width (+`dte_offset` for
   diagonals/calendars), DTE window, entry cadence, signal gates over nine trailing features, exits, sizing, costs.
2. **Engine** (`engine.py`) — daily loop over real EOD chains: fills at mid ± half-spread × slippage, $0.65/contract/leg
   each way, marks at mid, settles at intrinsic, positions sized by payoff-grid max loss. Costs are fixed across all
   candidates so results are comparable.
3. **Fitness** — `0.5·mean_sharpe + 0.5·min_sharpe + 2·worst_year + 3·max(maxDD,−1) + (positive_years−1)`,
   scored across underlyings; fewer than 40 trades scores −9. Robustness beats peak return by construction.
4. **Search** — 8 strategy angles × 2 candidates seeded generation 0; 3 generations of parameter/structural mutation
   and crossover on the top 5, agents run concurrently. 7 research papers were mined in parallel for seed ideas.
5. **Verification** (`verify.py`) — parameter fragility sweep, out-of-sample regimes, P&L concentration.

**140+ candidates** evaluated. Data: Kaggle EOD chains (SPY 2020–22, QQQ 2021–22, AAPL 2016–23, NVDA, TSLA) with real
bid/ask/IV/greeks, plus an independent vendor (DoltHub `post-no-preference/options`, 1,522 names, 2019–2026) used
strictly as out-of-sample.

## The central finding: the gate is the edge

Holding the structure fixed and sweeping only the entry gate (implied vol vs 20-day realised vol):

| IV/RV gate | score | mean Sharpe | min Sharpe | max DD | trades | fires (last 60d) |
|---|---|---|---|---|---|---|
| none | **−0.78** | −0.01 | −0.31 | −4.9% | 214 | 100% |
| ≥ 1.00 | −0.57 | 0.06 | −0.19 | −2.4% | 134 | 40% |
| ≥ 1.10 | 0.20 | 0.37 | 0.14 | −2.0% | 96 | 32% |
| ≥ 1.15 | 0.14 | 0.65 | 0.15 | −2.0% | 86 | 25% |
| ≥ 1.20 | 0.77 | 0.89 | 0.70 | −1.2% | 76 | 20% |
| ≥ 1.25 | **0.96** | 1.04 | 0.94 | −1.1% | 63 | 18% |

Selling put spreads **unconditionally loses money** (Sharpe ≈ 0 before costs bite). Selling them only when implied
volatility is rich relative to realised earns Sharpe ≈ 1.0. The monotonicity across seven thresholds is the evidence
this is the variance risk premium being harvested conditionally, not a fitted artifact — an independent review of seven
options papers ranked the same conditional-VRP family first.

## Deployed rule — `strategies/put_diagonal_ivrv.json`

Put credit **diagonal** on SPY and QQQ:

- **Entry** every 5 days, max 5 concurrent, only when `IV/RV ≥ 1.25` and `term_slope ≤ 0.03`
  (90-day ATM IV minus 30-day; skip when the curve is steeply in contango).
- **Structure** — sell the 30-delta put at ~45 DTE (30–60 window); buy the 15-delta put ~28 days further out.
  The long leg is longer-dated, so it retains time value exactly when the short leg is in trouble.
- **Exits** — take profit at 50% of premium, stop at 2× premium, close at 21 DTE.
- **Sizing** — 3% of equity at risk per position against payoff-grid max loss; skip entries whose credit is under
  5% of max loss.

In-sample: mean Sharpe 1.01 (SPY 1.02, QQQ 0.99), max drawdown 1.1%, positive every year including 2022, 59 trades.

## What verification found

**Survives:**
- **Independent vendor, unseen years** — Dolt SPY 2019–2026 (the fitting data ends in 2022): Sharpe **0.84**,
  42 trades, positive in 5 of 8 years, max DD 0.4%.
- **Unseen underlying** — AAPL 2016–2023, never used to fit this candidate: Sharpe **0.52**, 124 trades, positive in
  7 of 8 years, max DD 5.6%.
- **Costs** — doubling slippage to the full half-spread barely moves the score (0.98 → 0.91).
- **P&L is not concentrated** — top 5 of ~30 trades account for 33% (SPY) / 43% (QQQ) of P&L; median trade positive.
- Signal thresholds ±10%, cadence ±2 days, profit target and stop ±25% all hold (scores 0.49–1.08).

**Weaknesses — stated plainly:**
- **DTE window is fitted.** Shifting it ±10 days collapses the score (0.98 → 0.07 / 0.28). The 30–60 DTE window is the
  most fragile parameter in the spec.
- **Thin sample.** 59 in-sample trades. Perturbing the short leg to 35-delta or the long leg to 10-delta drops entries
  below the 40-trade floor — the candidate sits near a cliff where entries dry up.
- **Single names unvalidated.** NVDA and TSLA produced only 11–14 trades at this gate; nothing can be concluded there.

## Deployment risk the search did not optimise for

The fitness function rewarded risk-adjusted return over three years. It never asked **"will this trade this week?"**

The gate fires on ~18% of days. SPY's IV/RV is currently ~1.15 by the engine's definition — **below the threshold**.
Deployed on SPY alone over a handful of trading days, the most likely outcome is **zero trades and zero P&L**.

The fix is **breadth, not a weaker gate** — loosening the gate is exactly where the edge disappears. A cross-sectional
scan of the 1,522-name Dolt universe found **222 names (15%) above IV/RV ≥ 1.25** on the same date SPY was below it.
Caveat: extreme single-name IV/RV usually prices a scheduled event (earnings, M&A, FDA), and selling that premium is
the classic trap — so any breadth basket must be liquidity- and event-filtered, and single-name performance is the
least validated part of this work.

## Recommended live risk gates

- Defined-risk structures only (every position has a bought wing); no naked short options.
- 3% of equity at risk per position, max 5 concurrent → ≤15% of the account at risk.
- Skip any underlying with a scheduled earnings date inside the position's life.
- Require the quoted credit to be ≥5% of max loss, and both legs to have a real bid (≥ $0.05).
- Halt new entries after a 5% account drawdown.

## Evolutionary path

- **Helped:** adding the IV/RV gate (the whole edge); the `dte_offset` long leg (diagonal beat the vertical:
  0.73 → 0.96); adding a `term_slope` ceiling; a 50% profit target over holding to expiry.
- **Hurt / discarded:** unconditional premium selling (loses to costs); long-vol structures (straddles, strangles,
  calendars — negative carry); 60-day condors; 4-DTE technical-signal spreads from the Carlier paper
  (best variant: AAPL Sharpe 0.80, but QQQ −0.14 and the unconditional control lost 49% on QQQ).
- **Regime complement:** bear call spreads gated below the 200-day SMA made all their money in 2022 — a natural
  second sleeve for a down-trending regime, not yet integrated.

## Engine limitations to keep in mind

- Daily decisions only; no intraday management or dynamic delta hedging.
- Single-underlying accounting — each backtest gets its own $100k; there is no shared-cash portfolio loop.
- Kaggle single-name chains are **not split-adjusted** (AAPL 4:1 Aug 2020, TSLA 5:1/3:1, NVDA 4:1 Jul 2021).
- The Dolt surface is coarse (~3 expirations × ~20 strikes, every other day), so short-DTE candidates cannot be
  fairly verified on it — a 7–21 DTE condor scored −0.87 there largely for that reason.
