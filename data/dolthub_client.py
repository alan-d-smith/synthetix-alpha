"""
dolthub_client.py — DoltHub HTTP/SQL client for backtest options data.

Queries post-no-preference/options (branch: master) via SQL over HTTP:
    https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master?q=<SQL>

Contains SPDR ETFs + SPY/MDY/SLY components, 2019-present, bids/asks/vols/
Greeks, plus volatility_history table for IV rank. No auth required.
"""
from __future__ import annotations

from typing import Any


def query_dolthub(sql: str) -> list[dict[str, Any]]:
    """Execute a SQL query against the DoltHub options database.

    Args:
        sql: Valid SQL query string.

    Returns:
        List of result rows as dicts.
    """
    # TODO: implement — this is a skeleton
    return []


def get_iv_rank(ticker: str, current_iv: float) -> float | None:
    """Compute IV rank for a ticker using volatility_history table.

    Args:
        ticker: Underlying symbol.
        current_iv: Current implied volatility value.

    Returns:
        IV rank (0.0 to 1.0), or None if data unavailable.
    """
    # TODO: implement — this is a skeleton
    return None