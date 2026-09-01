# synthetix-alpha — Institutional Benchmark Report

**Generated**: 2026-08-30T14:56:07.831926+00:00
**Source**: `live_demo`

---

## 1. Strategy Backtest Results (Kaggle EOD Chains)

| Strategy | Underlyings | Sharpe | Max DD | Trades | Pos. Years |
|---|---|---|---|---|---|
| put_diagonal_ivrv_robust | SPY, QQQ, NVDA | 1.119 | -2.3% | 204 | 88% |
| put_vertical_ivrv | SPY, QQQ | 0.918 | -2.0% | 102 | 80% |
| put_vertical_multi_singlename | AAPL, NVDA, TSLA | 0.549 | -5.1% | 112 | 87% |

## 1b. Strategy Backtest Results (Dolt 2019-2026 Coarse Surface)

_Note: dolt surface is coarse (~every other day, ~3 exp x ~20 strikes), so fill prices are approximate. Results differ from Kaggle full EOD chains._

| Strategy | Underlyings | Sharpe | Max DD | Trades | Pos. Years |
|---|---|---|---|---|---|
| put_vertical_ivrv | SPY, QQQ | 0.666 | -2.5% | 147 | 62% |


## 2. Per-Underlying Detail

### put_diagonal_ivrv_robust_put_diagonal_ivrv_robust

| Underlying | Sharpe | Trades | Max DD | CAGR | Win Rate | Profit Factor |
|---|---|---|---|---|---|---|
| NVDA | 1.217 | 54 | -2.28% | 3.23% | 92.6% | 3.59 |
| QQQ | 1.007 | 64 | -2.31% | 2.91% | 95.3% | 4.86 |
| SPY | 1.133 | 86 | -1.59% | 2.48% | 95.3% | 4.17 |

### put_vertical_ivrv_put_vertical_ivrv

| Underlying | Sharpe | Trades | Max DD | CAGR | Win Rate | Profit Factor |
|---|---|---|---|---|---|---|
| QQQ | 0.701 | 39 | -2.00% | 1.62% | 92.3% | 2.46 |
| SPY | 1.136 | 63 | -1.36% | 2.64% | 90.5% | 7.15 |

### put_vertical_ivrv_put_vertical_ivrv_dolt

| Underlying | Sharpe | Trades | Max DD | CAGR | Win Rate | Profit Factor |
|---|---|---|---|---|---|---|
| SPY | 0.666 | 147 | -2.45% | 1.07% | 34.7% | 1.84 |

### put_vertical_multi_singlename_put_vertical_multi_singlename

| Underlying | Sharpe | Trades | Max DD | CAGR | Win Rate | Profit Factor |
|---|---|---|---|---|---|---|
| AAPL | 0.900 | 78 | -2.12% | 1.88% | 92.3% | 5.12 |
| NVDA | 0.061 | 18 | -5.05% | 0.13% | 94.4% | 1.08 |
| TSLA | 0.686 | 16 | -1.67% | 0.69% | 75.0% | 9.12 |

## 3. Verification (Fragility + OOS)

## Industry KPI Comparison

| Strategy | Sharpe | Max DD | CAGR | Win Rate | Trades | Notes |
|---|---|---|---|---|---|---|
| **synthetix-alpha (deployed)** | _from results_ | _from results_ | _from results_ | _from results_ | _from results_ | SPY+QQQ, IV/RV gate |
| CBOE PUT Index | 0.4–0.6 | 30–40% | 3–5% | — | — | ATM SPX puts, systematic |
| CBOE BXM Index | 0.3–0.5 | 30–35% | 4–6% | — | — | Covered calls, passive |
| CBOE PUTW Index | 0.4–0.5 | 25–35% | 3–5% | — | — | Cash-secured puts |
| Hedge Fund Vol Arb (median) | 0.8–1.2 | 5–15% | 6–10% | 55–65% | 300+ | Active vol timing |
| Top-Quartile Vol Desk | 1.2–1.8 | 3–8% | 8–15% | 60–70% | 500+ | Multi-asset, institutional |
| S&P 500 Buy & Hold | ~0.8 | ~34% | ~10% | — | 1 | No hedge, full beta |

## 4. Institutional Readiness Checklist

| Check | Status | Notes |
|---|---|---|
| Dolt DB cloned | PASS | `datasets/options/` — 116M rows, 1,500+ names |
| Kaggle strategies | 3 | All specs backtested on EOD chains |
| Dolt strategies | 1 | OOS backtest on 2019-2026 coarse surface |
| OOS verification | PASS | Fragility sweep + dolt OOS (SPY) |
| Pipeline dry-run | PASS | LLM -> Critic -> Risk -> Execution |
| 20+ underlyings | PARTIAL | dolt has 1,500+ names; screen needs VIX/VXN for ETFs |
| Live paper trading | NEEDS KEYS | 0 days - needs Alpaca keys + pipeline |
| Tail event stress test | PASS | `put_vertical_ivrv_tail.json` |
