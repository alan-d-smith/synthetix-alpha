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

## Generation 3: robustness became the objective

Verification of the generation-2 leader exposed a knife-edge: shifting its DTE window ±10 days collapsed the score
from 0.98 to 0.28 / 0.07. Generation 3 therefore optimised a **robust score** = `0.6·base + 0.4·fragility_median`,
with each agent running the verification harness on its own candidate and reporting its own gate firing rate.

**The key insight — DTE fragility was a *location* problem, not a *width* problem.** Sweeping `dte_target` from 30 to
70 reveals a hole at 35–45 (scores −1.7 to 0.4) and a broad plateau at 55–70. The old champion sat at 45, on the edge
of the hole, so widening its window did not help. Re-centring at **65 DTE** puts the entire ±10 neighbourhood on the
plateau. That single change, not parameter tuning, is what fixed the fragility.

A second reusable finding, from the condor line: capping the holding period with `max_hold_days` decouples P&L from
the DTE window, turning its DTE−10 score from unscoreable to +0.86.

| candidate | robust | base | fragility median | DTE −10 / +10 | trades | fires |
|---|---|---|---|---|---|---|
| **`put_vertical_ivrv`** | **1.03** | 1.09 | 0.94 | 0.85 / 1.01 | 104 | 25% |
| `put_diagonal_ivrv_robust` | 0.93 | 1.01 | 0.81 | 0.41 / 0.40 | 189 | 25% |
| `index_condor_trend` | 0.87 | 0.97 | 0.72 | 0.86 / 0.68 | 140 | 26% |
| gen-2 champion (diagonal) | 0.88 | 0.98 | 0.75 | 0.07 / 0.28 | 59 | 18% |

## Deployed rule — `strategies/put_vertical_ivrv.json`

Put credit **vertical** on SPY and QQQ — single expiry, so one standard 2-leg `mleg` order:

- **Entry** every 3 days, max 5 concurrent, only when `IV/RV ≥ 1.27`.
- **Structure** — sell the 20-delta put, buy the 10-delta put, same expiry, ~65 DTE (40–90 window).
- **Exits** — take profit at 65% of the credit, stop at 2× credit, close at 21 DTE.
- **Sizing** — 3% of equity at risk per position against payoff-grid max loss; skip entries whose credit is under
  5% of max loss.

In-sample: mean Sharpe 1.13 (SPY 1.16, QQQ 1.11), max drawdown 1.4%, positive every year including 2022, 104 trades.

Alternates kept for regime coverage: `put_diagonal_ivrv_robust.json` (189 trades, adds NVDA) and
`index_condor_trend.json` (two-sided, index-only — it fails on single names).


![Performance of the deployed strategy](img/put_vertical_ivrv_performance.png)

## What verification found

![Gate sweep and parameter fragility](img/put_vertical_ivrv_research.png)


**Survives** (numbers are for the deployed `put_vertical_ivrv`):
- **Independent vendor, unseen years** — Dolt SPY 2019–2026 (the fitting data ends in 2022): Sharpe **0.65** over
  148 trades, positive in 5 of 8 years.
- **Unseen underlying** — AAPL 2016–2023, never used to fit it: Sharpe **0.49**, 184 trades, positive in 6 of 8 years.
- **Fragility** — median perturbed score **0.94** against a base of 1.09; 82% of perturbations stay above half the base.
  The ±10-day DTE shift, which broke the previous champion, now scores 0.85 / 1.01.
- **Costs** — doubling slippage to the full half-spread leaves the score above 0.9.
- **P&L is not concentrated** — the top 5 of 65 SPY trades are 15% of profit (20% on QQQ); median trade positive.

**Weaknesses — stated plainly:**
- **The gate cannot be loosened.** Dropping it 10% (to ~1.14) turns the score negative (−0.08). The edge lives at
  IV/RV ≥ ~1.2; below that the variance risk premium does not cover costs.
- **Long-leg delta is a cliff.** Moving the long leg from 10-delta to 5-delta drops entries below the 40-trade floor —
  those strikes have no reliable bid.
- **Out-of-sample is materially weaker than in-sample** (Sharpe 0.49–0.65 vs 1.13). Expect the lower number live.
- **Single names are the least validated part.** The condor line fails outright on AAPL (score −2.05) and the robust
  diagonal scores −0.75 there; only the vertical holds up out-of-sample on a single name.

## Deployment risk the search did not optimise for

The fitness function rewarded risk-adjusted return over three years. It never asked **"will this trade this week?"**

The gate fires on ~25% of days. SPY's IV/RV is currently ~1.15 by the engine's definition — **below the threshold**.
Deployed on SPY alone over a handful of trading days, the most likely outcome is **zero trades and zero P&L**.

The fix is **breadth, not a weaker gate** — loosening the gate is exactly where the edge disappears. A cross-sectional
scan of the 1,522-name Dolt universe found **222 names (15%) above IV/RV ≥ 1.25** on the same date SPY was below it.

**The edge does generalise across names.** Running the same rule over ten large caps on the independent Dolt data
(2019–2026) gives a median Sharpe of **0.61 with 8 of 10 positive**:

| | COST | AMZN | JPM | META | MSFT | AAPL | GOOGL | UNH | WMT | XOM |
|---|---|---|---|---|---|---|---|---|---|---|
| Sharpe | 1.12 | 0.85 | 0.69 | 0.63 | 0.62 | 0.60 | 0.59 | 0.33 | −0.17 | −0.31 |

So the conditional variance risk premium is not an SPY artifact, and a breadth basket is a legitimate way to keep the
gate strict while still trading. `synthetix_alpha/live/screen.py` implements the daily scan against the liquidity
floors in `config/universe.yaml`.

**But the screener is not yet safe to trade unattended.** Running it today returns NTAP, ADSK, ASO, PVH, CASY and AEO
— every one of them reporting earnings within days. That is exactly the trap: high IV/RV usually prices a scheduled
event, and the premium is compensation for real jump risk. The `iv_rv_max` cap (default 2.0) removes only the most
extreme cases. **An earnings-calendar filter is a required prerequisite before any single-name deployment**, and it
does not exist yet. Until it does, the index pair (SPY/QQQ) is the only validated way to run this.

## Recommended live risk gates

- Defined-risk structures only (every position has a bought wing); no naked short options.
- 3% of equity at risk per position, max 5 concurrent → ≤15% of the account at risk.
- Skip any underlying with a scheduled earnings date inside the position's life (**not yet implemented** — this is
  why single-name trading is gated off; see the screener caveat above).
- Require the quoted credit to be ≥5% of max loss, and both legs to have a real bid (≥ $0.05).
- Halt new entries after a 5% account drawdown.

## Evolutionary path

- **Helped:** adding the IV/RV gate (the whole edge); re-centring the DTE window onto the 55–70 plateau
  (0.98 → 1.09 with far better stability); wider 20/10-delta wings over 30/15; a 65% profit target; capping the
  holding period with `max_hold_days` to decouple P&L from DTE.
- **Helped, then superseded:** the `dte_offset` long leg (the diagonal beat the vertical at 45 DTE, 0.73 → 0.96) —
  but once the vertical was moved to 65 DTE it overtook the diagonal on every axis, and it is simpler to execute.
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

## Progress log

[`progress.md`](progress.md) records every candidate promoted out of a generation with a UTC timestamp, so the
improvement is auditable rather than asserted. The headline: the hand-written baseline scored **−1.18**; three
generations later the deployed rule scores **+1.09**.

| | baseline | gen 0 | gen 2 | gen 3 |
|---|---|---|---|---|
| score | −1.18 | +0.75 | +0.98 | **+1.09** |
| mean Sharpe | −0.13 | 0.85 | 1.01 | **1.13** |
| max drawdown | −8.3% | −2.7% | −1.1% | **−1.4%** |
| trades | 168 | 49 | 59 | **104** |

Log a new candidate with `python -m synthetix_alpha.strategy.progress <spec.json> --gen N --note "..."`. The JSONL
behind it is append-only, so a later run cannot rewrite earlier history.

## Regenerating the figures

Both figures are produced from the backtest itself, so they cannot drift from the numbers in this document:

```sh
python -m synthetix_alpha.strategy.verify strategies/put_vertical_ivrv.json --oos AAPL --dolt SPY
python -m synthetix_alpha.strategy.plots  strategies/put_vertical_ivrv.json     --verify datasets/research/verify/put_vertical_ivrv_verify.json
```

The plot script writes `docs/img/<spec name>_performance.png` and `<spec name>_research.png`. If you change a spec or
the engine on a branch, rerun both commands and commit the regenerated PNGs alongside the updated tables here. The gate
sweep re-runs one backtest per threshold, so it takes a few minutes; pass `--no-sweep` to skip it.
