# synthetix-alpha
An autonomous, risk-gated quantitative trading agent powered by LLM reasoning and the Alpaca MCP server.

## Setup

```sh
git submodule update --init
py -3.13 -m venv .venv && .venv/Scripts/activate
pip install -e external/gs-quant -e .[dev]
cp .env.example .env   # fill in ALPACA_API_KEY / ALPACA_API_SECRET
pytest
```

## Strategy research

```sh
python -m synthetix_alpha.strategy.run spec.json --out results.json            # Kaggle chains (2016-2023)
python -m synthetix_alpha.strategy.run spec.json --source dolt --start 2023-01-01  # Dolt surfaces + Alpaca spot (OOS)
```

`synthetix_alpha/strategy`: a declarative `Spec` (legs by delta/moneyness/width, DTE window, signal gates, exits, sizing,
costs) interpreted by a deterministic daily backtester over EOD chains. Research agents mutate specs, never code;
`datasets/research/` holds generations, results and the report.

## Market data → gs-quant

```python
import datetime as dt
from synthetix_alpha.data import AlpacaClient, BarStore, OptionBarsDataSource, chain_bars, register
from synthetix_alpha.data import dolt, kaggle
from gs_quant.backtests.data_sources import DataManager

c = AlpacaClient()
chain = c.option_chain("SPY", expiration_date="2026-09-02")      # bid/ask/IV/greeks per contract
bars = c.option_bars(chain.index[:5], "15Min", start="2026-08-20")  # OHLCV history (Feb 2024+)

store = BarStore(c)
store.ensure("option", "1Day", chain.index, dt.date(2026, 8, 1), dt.date.today())  # one batched fetch for the whole chain
dm = DataManager()
option = register(dm, OptionBarsDataSource(symbol=chain.index[0], store=store))  # use `option` in gs-quant triggers/actions

# Historical EOD chains 2019-2023 (Kaggle), same layouts: chains.loc[date] is a chain snapshot
chains = kaggle.load_chains("QQQ")                 # also AAPL, NVDA, SPY, TSLA; (date, symbol) x CHAIN_COLUMNS, parquet-cached
store.add("option", "1Day", chain_bars(chains))
store.add("stock", "1Day", kaggle.underlying_bars(chains))

# DoltHub post-no-preference/options (`dolt clone post-no-preference/options datasets/options`): coarse EOD IV surfaces,
# ~1,500 names, 2019-02 → present, every ~2 days; plus daily HV/IV summaries. Cached per symbol-year under datasets/cache.
surface = dolt.load_chains(["SPY", "QQQ"], dt.date(2023, 1, 1), dt.date(2024, 12, 31))
vol = dolt.load_volatility(["SPY"], dt.date(2023, 1, 1), dt.date(2024, 12, 31))
```

## Live execution and risk gates

`synthetix_alpha/live/` — paper-only order submission and the deterministic gates that sit in front of it.
Limits live in [config/governance.yaml](config/governance.yaml), so they are auditable without touching code.

```python
from synthetix_alpha.live import Rules, apply, submit
decision = apply(orders, positions, nav, Rules.load())   # defined-risk only, per-position and NAV caps, drawdown halts
submit(legs, contracts, limit_price)                      # dry-run by default; deterministic client_order_id = no double-fills
```

`synthetix_alpha/live/screen.py` scans the ~1,500-name DoltHub vol history for underlyings whose implied vol is rich
versus realised, applying the liquidity floors in [config/universe.yaml](config/universe.yaml). Note the open caveat in
the research doc: it has no earnings filter yet, so its single-name output is not safe to trade unattended.

`.agents/skills/` holds Alpaca API reference skills (trading, market data, paper CLI/MCP, broker flows), with
provenance and hashes in `skills-lock.json`.

## Deployed strategy

`strategies/put_vertical_ivrv.json` — put credit vertical on SPY/QQQ (sell 20-delta, buy 10-delta, ~65 DTE), entered
entered only when both the option chain and the matching CBOE index (VIX/VXN) agree implied vol is rich versus
realised. In-sample mean Sharpe 1.15, max DD 1.4%, 102 trades; Sharpe 0.67 out-of-sample on independent 2019-2026
vendor data. See [docs/research.md](docs/research.md) for the search, the verification, and the
deployment caveats.

```sh
python -m synthetix_alpha.strategy.run strategies/put_vertical_ivrv.json        # backtest
python -m synthetix_alpha.strategy.verify strategies/put_vertical_ivrv.json --oos AAPL --dolt SPY
python -m synthetix_alpha.strategy.plots strategies/put_vertical_ivrv.json    # figures -> docs/img/
python -m synthetix_alpha.strategy.progress strategies/put_vertical_ivrv.json --gen 3   # append to docs/progress.md
```

Generation-by-generation results are logged with UTC timestamps in [docs/progress.md](docs/progress.md).

`strategies/put_vertical_singlename.json` applies the same rule to single names, gated on yfinance earnings dates so
no position is held through an announcement (AAPL: Sharpe 0.46 -> 0.90, max drawdown -7.7% -> -2.1%).

![Strategy performance](docs/img/put_vertical_ivrv_performance.png)
