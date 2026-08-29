# Strategy progress log

Each row beat every candidate evaluated before it, so this is the improvement path of the search rather than a list of
everything tried. Rows marked ⚠ are corrections: the same strategy restated after an engine change, kept even when the
score falls, because a number that is no longer believed should not remain the headline. Appended by `python -m synthetix_alpha.strategy.progress <spec.json> --gen N`; the full history,
including evaluations that did not improve, stays in the append-only `progress.jsonl` beside this file.

Score is the search's selection score:
`0.5*mean_sharpe + 0.5*min_sharpe + 2*worst_year + 3*max(maxDD, -1) + (positive_years - 1)`, with fewer than 40 trades
scoring -9. Return is the mean across the underlyings traded, each on its own $100k.

| evaluated (UTC) | gen | strategy | underlyings | return | mean Sharpe | min Sharpe | max DD | worst year | trades | score | what changed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-28 23:38 | 0 | `spy_put_credit_spread_ivr` | SPY+QQQ | -0.9% | -0.13 | -0.67 | -8.3% | -6.5% | 168 | **-1.180** | hand-written baseline: 45 DTE put spread, IV rank gate |
| 2026-08-28 23:52 | 0 | `idx_put_spread_ivrv_rich_v2` | SPY+QQQ | +6.8% | 0.73 | 0.68 | -3.2% | -0.3% | 141 | **+0.401** | gen 0 winner of the IV/RV line |
| 2026-08-28 23:57 | 0 | `short_dte_condor_uptrend` | SPY+QQQ | +3.4% | 0.70 | 0.62 | -2.3% | +0.6% | 125 | **+0.607** | gen 0: uptrend-gated short-DTE condor |
| 2026-08-28 23:58 | 0 | `diagonal_put_credit_80` | SPY+QQQ | +3.5% | 0.85 | 0.80 | -2.7% | +0.3% | 49 | **+0.749** | gen 0 overall winner; only 49 trades |
| 2026-08-29 07:50 | 2 | `short_dte_condor_uptrend_g1m0_g2m0` | SPY+QQQ | +4.5% | 0.99 | 0.93 | -2.2% | +0.1% | 124 | **+0.897** | gen 2: condor line |
| 2026-08-29 07:52 | 2 | `idx_put_spread_ivrv_rich_v2_g1m0_g2m1` | SPY+QQQ | +2.5% | 1.01 | 0.99 | -1.1% | +0.2% | 59 | **+0.975** | gen 2 winner; knife-edge DTE window (+/-10 -> 0.28/0.07) |
| 2026-08-29 13:11 | 3 | `robust_diag_v1` | SPY+QQQ+NVDA | +7.0% | 1.13 | 1.01 | -2.3% | +0.6% | 189 | **+1.012** | gen 3: robustness-tuned diagonal, 189 trades |
| 2026-08-29 13:12 | 3 | `vertical_ivrv_v0` | SPY+QQQ | +6.7% | 1.14 | 1.11 | -1.4% | +0.3% | 104 | **+1.089** | gen 3 winner: re-centred to the 55-70 DTE plateau; DEPLOYED |
| 2026-08-29 15:20 | 4 | `put_vertical_ivrv` | SPY+QQQ | +6.7% | 1.15 | 1.14 | -1.4% | +0.4% | 102 | **+1.112** | gen 4: require VIX/VXN to confirm the chain-derived vol gate (index-only) |
| 2026-08-29 16:59 | 4 | `put_vertical_ivrv` | SPY+QQQ | +5.7% | 0.92 | 0.70 | -2.0% | -1.5% | 102 | **+0.520** | !! liquidity floor: require 25 contracts traded that day. 9.8% of earlier fills were in contracts with ZERO volume; the in-sample/OOS gap narrowed 1.15/0.67 -> 0.92/0.67 |
| 2026-08-29 17:26 | 5 | `put_vertical_singlename` | AAPL | +14.4% | 0.90 | 0.90 | -2.1% | +0.1% | 78 | **+0.838** | single-name variant: yfinance earnings filter (no announcement within 30d). AAPL score -0.151 -> +0.838, Sharpe 0.46 -> 0.90, maxDD -7.7% -> -2.1% |
| 2026-08-29 19:42 | 7 | `portfolio_index_plus_singlename` | SPY+QQQ+AAPL | +7.1% | 1.15 | 1.15 | -1.1% | +0.1% | 180 | **+1.176** | combine the index and single-name sleeves (corr 0.335); primitive from arXiv Lillo et al., Kelly investing using options |

12 improvements across 16 logged evaluations; score -1.180 -> +1.176, mean Sharpe -0.13 -> 1.15.
