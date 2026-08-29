"""Canonical frame layouts shared by every data provider."""

GREEKS = ("delta", "gamma", "theta", "vega", "rho")

# Bars: DatetimeIndex (UTC) named "timestamp", one row per (symbol, bar).
BAR_COLUMNS = ["symbol", "open", "high", "low", "close", "volume", "trade_count", "vwap"]

# Chain snapshot: index = OCC symbol. Historical chains add a leading "date" index level.
CHAIN_COLUMNS = ["underlying", "expiration", "type", "strike", "bid", "ask", "mid", "bid_size", "ask_size",
                 "quote_time", "last", "trade_time", "iv", *GREEKS, "volume"]
