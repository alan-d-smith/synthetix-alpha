# Strategy progress log

Every candidate promoted out of a generation, in evaluation order. Appended by
`python -m synthetix_alpha.strategy.progress <spec.json> --gen N`; the table is rendered from
`progress.jsonl`, which is append-only, so history cannot be rewritten by a later run.

Score is the selection score used by the search: `0.5·mean_sharpe + 0.5·min_sharpe + 2·worst_year + 3·max(maxDD,−1) + (positive_years−1)`, with fewer than 40 trades scoring −9. Returns are the mean across the underlyings traded, each on its own $100k.

## Best score over time

| evaluated (UTC) | gen | strategy | score |
|---|---|---|---|
| 2026-08-28 23:38 | 0 | `spy_put_credit_spread_ivr` | **-1.180** |
| 2026-08-28 23:52 | 0 | `idx_put_spread_ivrv_rich_v2` | **+0.401** |
| 2026-08-28 23:57 | 0 | `short_dte_condor_uptrend` | **+0.607** |
| 2026-08-28 23:58 | 0 | `diagonal_put_credit_80` | **+0.749** |
| 2026-08-29 07:50 | 2 | `short_dte_condor_uptrend_g1m0_g2m0` | **+0.897** |
| 2026-08-29 07:52 | 2 | `idx_put_spread_ivrv_rich_v2_g1m0_g2m1` | **+0.975** |
| 2026-08-29 13:11 | 3 | `robust_diag_v1` | **+1.012** |
| 2026-08-29 13:12 | 3 | `vertical_ivrv_v0` | **+1.089** |

## All evaluations

| evaluated (UTC) | gen | strategy | underlyings | return | mean Sharpe | min Sharpe | max DD | worst year | trades | score | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-28 23:38 | 0 | `spy_put_credit_spread_ivr` | SPY+QQQ | -0.9% | -0.13 | -0.67 | -8.3% | -6.5% | 168 | -1.180 | hand-written baseline: 45 DTE put spread, IV rank gate |
| 2026-08-28 23:52 | 0 | `idx_put_spread_ivrv_rich_v2` | SPY+QQQ | +6.8% | 0.73 | 0.68 | -3.2% | -0.3% | 141 | +0.401 | gen 0 winner of the IV/RV line |
| 2026-08-28 23:57 | 0 | `short_dte_condor_uptrend` | SPY+QQQ | +3.4% | 0.70 | 0.62 | -2.3% | +0.6% | 125 | +0.607 | gen 0: uptrend-gated short-DTE condor |
| 2026-08-28 23:58 | 0 | `diagonal_put_credit_80` | SPY+QQQ | +3.5% | 0.85 | 0.80 | -2.7% | +0.3% | 49 | +0.749 | gen 0 overall winner; only 49 trades |
| 2026-08-29 00:00 | 0 | `paper_carlier_bull_put_spread_4dte` | SPY+AAPL+QQQ | +27.4% | 0.32 | -0.14 | -23.6% | -20.5% | 419 | -1.339 | from Carlier (2021), technical-signal 4 DTE spread |
| 2026-08-29 07:31 | 0 | `paper_multileg_stealth_put_spread` | SPY+AAPL+NVDA | -6.5% | -0.47 | -1.75 | -21.8% | -12.3% | 589 | -2.581 | from Dong (2025), ungated put spread |
| 2026-08-29 07:37 | 1 | `idx_put_spread_ivrv_rich_v2_g1m1` | SPY+QQQ | +3.3% | 0.78 | 0.76 | -1.8% | +0.2% | 105 | +0.724 | gen 1: cadence and gate tuning |
| 2026-08-29 07:50 | 2 | `short_dte_condor_uptrend_g1m0_g2m0` | SPY+QQQ | +4.5% | 0.99 | 0.93 | -2.2% | +0.1% | 124 | +0.897 | gen 2: condor line |
| 2026-08-29 07:52 | 2 | `idx_put_spread_ivrv_rich_v2_g1m0_g2m1` | SPY+QQQ | +2.5% | 1.01 | 0.99 | -1.1% | +0.2% | 59 | +0.975 | gen 2 winner; knife-edge DTE window (+/-10 -> 0.28/0.07) |
| 2026-08-29 13:11 | 3 | `robust_diag_v1` | SPY+QQQ+NVDA | +7.0% | 1.13 | 1.01 | -2.3% | +0.6% | 189 | +1.012 | gen 3: robustness-tuned diagonal, 189 trades |
| 2026-08-29 13:12 | 3 | `vertical_ivrv_v0` | SPY+QQQ | +6.7% | 1.14 | 1.11 | -1.4% | +0.3% | 104 | +1.089 | gen 3 winner: re-centred to the 55-70 DTE plateau; DEPLOYED |
| 2026-08-29 13:22 | 3 | `condor_robust_v0` | SPY+QQQ | +3.7% | 1.15 | 0.86 | -1.8% | +0.8% | 140 | +0.969 | gen 3: condor with max_hold_days; fails on single names |
