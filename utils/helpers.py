"""
helpers.py — Shared utility functions.

    - Unique client_order_id generation
    - Timestamp formatting
    - Safe division (avoid ZeroDivisionError)
    - Ticker symbol validation / normalization
"""
from __future__ import annotations

import datetime
import uuid


def generate_client_order_id(prefix: str = "sx") -> str:
    """Generate a unique, idempotent client_order_id.

    Args:
        prefix: Short prefix (default 'sx' for synthetix).

    Returns:
        Unique ID string like 'sx-a1b2c3d4e5f6'.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utc_now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide safely, returning default if denominator is zero or None.

    Args:
        numerator: Dividend.
        denominator: Divisor.
        default: Value to return on division by zero.

    Returns:
        Quotient or default.
    """
    if denominator is None or denominator == 0:
        return default
    return numerator / denominator


def normalize_ticker(ticker: str) -> str:
    """Normalize a ticker symbol: uppercase, strip whitespace.

    Args:
        ticker: Raw ticker string.

    Returns:
        Cleaned uppercase ticker.
    """
    return ticker.strip().upper()