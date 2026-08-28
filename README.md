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

## Alpaca data → gs-quant

```python
import datetime as dt
from synthetix_alpha.data.alpaca import AlpacaClient, AlpacaOptionBarsDataSource, BarStore, register
from gs_quant.backtests.data_sources import DataManager

c = AlpacaClient()
chain = c.option_chain("SPY", expiration_date="2026-09-02")      # bid/ask/IV/greeks per contract
bars = c.option_bars(chain.index[:5], "15Min", start="2026-08-20")  # OHLCV history (Feb 2024+)

store = BarStore(c)
store.ensure("option", "1Day", chain.index, dt.date(2026, 8, 1), dt.date.today())  # one batched fetch for the whole chain
dm = DataManager()
option = register(dm, AlpacaOptionBarsDataSource(symbol=chain.index[0], store=store))  # use `option` in gs-quant triggers/actions
```
