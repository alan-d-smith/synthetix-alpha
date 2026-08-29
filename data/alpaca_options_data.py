"""
alpaca_options_data.py — Alpaca Options Data API client.

Fetches options chains, Greeks, and implied volatility data.
Uses the Alpaca Options Data API via alpaca-py SDK (OptionHistoricalDataClient).

Reads credentials from env vars: ALPACA_API_KEY, ALPACA_API_SECRET.
"""
from __future__ import annotations

import re
import os
from typing import Any

from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionSnapshotRequest
from dotenv import load_dotenv

load_dotenv()

_client: OptionHistoricalDataClient | None = None


def _get_client() -> OptionHistoricalDataClient:
    """Lazy-initialize and return the shared OptionHistoricalDataClient."""
    global _client
    if _client is None:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_API_SECRET")
        if not api_key or not secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set in .env"
            )
        _client = OptionHistoricalDataClient(api_key=api_key, secret_key=secret_key)
    return _client


def _parse_occ_symbol(occ: str) -> dict[str, Any]:
    """Parse an OCC option symbol into its components.

    OCC format: [root][YY][MM][DD][C/P][strike * 1000]
    Example: AAPL260909P00365000 → AAPL, 2026-09-09, put, 365.00
    """
    match = re.match(
        r"^(?P<root>[A-Z]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
        r"(?P<type>[CP])(?P<strike>\d{8})$",
        occ,
    )
    if not match:
        return {"strike_price": None, "expiration_date": None, "type": None}

    return {
        "strike_price": int(match.group("strike")) / 1000.0,
        "expiration_date": (
            f"20{match.group('yy')}-{match.group('mm')}-{match.group('dd')}"
        ),
        "type": "call" if match.group("type") == "C" else "put",
    }


def get_option_chain(
    ticker: str,
    expiration_date: str | None = None,
    strike_count: int = 10,
) -> list[dict[str, Any]]:
    """Fetch the options chain (snapshots) for a given underlying.

    Each contract in the chain includes latest trade, quote, implied
    volatility, and Greeks.

    Args:
        ticker: Underlying symbol (e.g., 'AAPL').
        expiration_date: Specific expiration (YYYY-MM-DD), or None for
            nearest expiration.
        strike_count: Number of strikes around ATM to return (limited
            client-side since the API returns the full chain).

    Returns:
        List of option contract dicts with keys:
            symbol, strike_price, expiration_date, type (call/put),
            latest_trade, latest_quote, implied_volatility, greeks.
            Sorted by strike price; capped at strike_count per side.
    """
    client = _get_client()

    request_params = OptionChainRequest(underlying_symbol=ticker)
    if expiration_date:
        request_params.expiration_date = expiration_date

    chain = client.get_option_chain(request_params)

    results: list[dict[str, Any]] = []
    for symbol, snap in chain.items():
        occ = _parse_occ_symbol(symbol)
        results.append({
            "symbol": symbol,
            "strike_price": occ["strike_price"],
            "expiration_date": occ["expiration_date"],
            "type": occ["type"],
            "latest_trade": {
                "price": float(snap.latest_trade.price) if snap.latest_trade else None,
                "size": int(snap.latest_trade.size) if snap.latest_trade else None,
            },
            "latest_quote": {
                "ask_price": float(snap.latest_quote.ask_price) if snap.latest_quote else None,
                "ask_size": int(snap.latest_quote.ask_size) if snap.latest_quote else None,
                "bid_price": float(snap.latest_quote.bid_price) if snap.latest_quote else None,
                "bid_size": int(snap.latest_quote.bid_size) if snap.latest_quote else None,
            },
            "implied_volatility": float(snap.implied_volatility) if snap.implied_volatility else None,
            "greeks": {
                "delta": float(snap.greeks.delta) if snap.greeks and snap.greeks.delta is not None else None,
                "gamma": float(snap.greeks.gamma) if snap.greeks and snap.greeks.gamma is not None else None,
                "theta": float(snap.greeks.theta) if snap.greeks and snap.greeks.theta is not None else None,
                "vega": float(snap.greeks.vega) if snap.greeks and snap.greeks.vega is not None else None,
                "rho": float(snap.greeks.rho) if snap.greeks and snap.greeks.rho is not None else None,
            },
        })

    # Sort by strike price, cap to strike_count calls + strike_count puts
    results.sort(key=lambda c: c["strike_price"] or 0)
    calls = [c for c in results if c.get("type") == "call"]
    puts = [c for c in results if c.get("type") == "put"]
    return calls[:strike_count] + puts[:strike_count]
def get_option_snapshot(option_symbols: list[str]) -> dict[str, Any]:
    """Fetch snapshots for specific option contracts.

    Each snapshot includes latest trade, latest quote, implied
    volatility, and Greeks.

    Args:
        option_symbols: List of option contract symbols (OCC format).

    Returns:
        Dict mapping option symbol -> snapshot dict with keys:
            strike_price, expiration_date, type, latest_trade,
            latest_quote, implied_volatility, greeks.
    """
    client = _get_client()
    request_params = OptionSnapshotRequest(symbol_or_symbols=option_symbols)
    snapshots = client.get_option_snapshot(request_params)

    result: dict[str, Any] = {}
    for symbol, snap in snapshots.items():
        occ = _parse_occ_symbol(symbol)
        result[symbol] = {
            "strike_price": occ["strike_price"],
            "expiration_date": occ["expiration_date"],
            "type": occ["type"],
            "latest_trade": {
                "price": float(snap.latest_trade.price) if snap.latest_trade else None,
                "size": int(snap.latest_trade.size) if snap.latest_trade else None,
            },
            "latest_quote": {
                "ask_price": float(snap.latest_quote.ask_price) if snap.latest_quote else None,
                "ask_size": int(snap.latest_quote.ask_size) if snap.latest_quote else None,
                "bid_price": float(snap.latest_quote.bid_price) if snap.latest_quote else None,
                "bid_size": int(snap.latest_quote.bid_size) if snap.latest_quote else None,
            },
            "implied_volatility": float(snap.implied_volatility) if snap.implied_volatility else None,
            "greeks": {
                "delta": float(snap.greeks.delta) if snap.greeks and snap.greeks.delta is not None else None,
                "gamma": float(snap.greeks.gamma) if snap.greeks and snap.greeks.gamma is not None else None,
                "theta": float(snap.greeks.theta) if snap.greeks and snap.greeks.theta is not None else None,
                "vega": float(snap.greeks.vega) if snap.greeks and snap.greeks.vega is not None else None,
                "rho": float(snap.greeks.rho) if snap.greeks and snap.greeks.rho is not None else None,
            },
        }
    return result