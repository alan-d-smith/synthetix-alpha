"""
alpaca_market_data.py — Alpaca Market Data API client.

Provides bars, quotes, and snapshots for the live quant engine.
Uses the Alpaca Data API v2 via alpaca-py SDK (StockHistoricalDataClient).

Reads credentials from env vars: ALPACA_API_KEY, ALPACA_API_SECRET.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockSnapshotRequest,
    StockLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv

load_dotenv()

_client: StockHistoricalDataClient | None = None


def _get_client() -> StockHistoricalDataClient:
    """Lazy-initialize and return the shared StockHistoricalDataClient."""
    global _client
    if _client is None:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_API_SECRET")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set in .env"
            )
        _client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
    return _client


def get_bars(
    tickers: list[str],
    timeframe: str = "15Min",
    limit: int = 100,
) -> dict[str, Any]:
    """Fetch historical bars for a list of tickers.

    Args:
        tickers: List of symbols.
        timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day).
        limit: Number of bars to return.

    Returns:
        Dict mapping ticker -> list of bar dicts with keys:
            timestamp, open, high, low, close, volume, vwap, trade_count.
    """
    client = _get_client()

    tf_map = {
        "1Min": TimeFrame.Minute,
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
    }
    tf = tf_map.get(timeframe, TimeFrame(15, TimeFrameUnit.Minute))

    # Use a start date to ensure we get bars even when market is closed
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)

    request_params = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=tf,
        start=start,
        end=end,
        limit=limit,
        feed="iex",  # IEX feed is free for paper accounts
    )
    bars = client.get_stock_bars(request_params)

    result: dict[str, list[dict[str, Any]]] = {}
    for ticker in tickers:
        result[ticker] = []

    # bars is a BarSet model with .data dict
    bars_data = bars if isinstance(bars, dict) else bars.data  # type: ignore[attr-defined]
    for symbol, bar_list in bars_data.items():
        result[symbol] = [
            {
                "timestamp": b.timestamp.isoformat(),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
                "vwap": float(b.vwap) if b.vwap else 0.0,
                "trade_count": int(b.trade_count) if b.trade_count else 0,
            }
            for b in bar_list
        ]
    return result
def get_snapshots(tickers: list[str]) -> dict[str, Any]:
    """Fetch real-time snapshots for a list of tickers.

    Snapshots include latest trade, latest quote, latest minute bar,
    latest daily bar, and previous daily bar.

    Args:
        tickers: List of symbols.

    Returns:
        Dict mapping ticker -> snapshot dict with keys:
            latest_trade, latest_quote, latest_minute_bar,
            latest_daily_bar, previous_daily_bar.
    """
    client = _get_client()
    request_params = StockSnapshotRequest(symbol_or_symbols=tickers)
    snapshots = client.get_stock_snapshot(request_params)

    result: dict[str, Any] = {}
    for symbol, snap in snapshots.items():
        result[symbol] = {
            "latest_trade": {
                "price": float(snap.latest_trade.price) if snap.latest_trade else None,
                "size": int(snap.latest_trade.size) if snap.latest_trade else None,
                "timestamp": snap.latest_trade.timestamp.isoformat()
                if snap.latest_trade and snap.latest_trade.timestamp else None,
            },
            "latest_quote": {
                "ask_price": float(snap.latest_quote.ask_price) if snap.latest_quote else None,
                "ask_size": float(snap.latest_quote.ask_size) if snap.latest_quote else None,
                "bid_price": float(snap.latest_quote.bid_price) if snap.latest_quote else None,
                "bid_size": float(snap.latest_quote.bid_size) if snap.latest_quote else None,
            },
            "latest_minute_bar": {
                "open": float(snap.minute_bar.open) if snap.minute_bar else None,
                "high": float(snap.minute_bar.high) if snap.minute_bar else None,
                "low": float(snap.minute_bar.low) if snap.minute_bar else None,
                "close": float(snap.minute_bar.close) if snap.minute_bar else None,
                "volume": int(snap.minute_bar.volume) if snap.minute_bar else None,
                "timestamp": snap.minute_bar.timestamp.isoformat()
                if snap.minute_bar and snap.minute_bar.timestamp else None,
            },
            "latest_daily_bar": {
                "open": float(snap.daily_bar.open) if snap.daily_bar else None,
                "high": float(snap.daily_bar.high) if snap.daily_bar else None,
                "low": float(snap.daily_bar.low) if snap.daily_bar else None,
                "close": float(snap.daily_bar.close) if snap.daily_bar else None,
                "volume": int(snap.daily_bar.volume) if snap.daily_bar else None,
            },
            "previous_daily_bar": {
                "open": float(snap.previous_daily_bar.open) if snap.previous_daily_bar else None,
                "high": float(snap.previous_daily_bar.high) if snap.previous_daily_bar else None,
                "low": float(snap.previous_daily_bar.low) if snap.previous_daily_bar else None,
                "close": float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None,
                "volume": int(snap.previous_daily_bar.volume) if snap.previous_daily_bar else None,
            },
        }
    return result


def get_latest_quotes(tickers: list[str]) -> dict[str, Any]:
    """Fetch the latest quote for a list of tickers.

    Args:
        tickers: List of symbols.

    Returns:
        Dict mapping ticker -> quote dict with:
            ask_price, ask_size, bid_price, bid_size, timestamp.
    """
    client = _get_client()
    request_params = StockLatestQuoteRequest(symbol_or_symbols=tickers)
    quotes = client.get_stock_latest_quote(request_params)

    result: dict[str, Any] = {}
    for symbol, q in quotes.items():
        result[symbol] = {
            "ask_price": float(q.ask_price),
            "ask_size": int(q.ask_size),
            "bid_price": float(q.bid_price),
            "bid_size": int(q.bid_size),
            "timestamp": q.timestamp.isoformat() if q.timestamp else None,
        }
    return result