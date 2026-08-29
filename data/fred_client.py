"""
fred_client.py — FRED (Federal Reserve Economic Data) API client.

Fetches macro data for the research agent's macro_alignment signal:
    - VIX (CBOE Volatility Index)
    - Yield curve (10Y-2Y spread)
    - CPI (Consumer Price Index)
    - Fed funds rate

Uses fredapi package. Falls back gracefully to None values if no
FRED_API_KEY is configured (FRED is optional).
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# FRED series IDs
FRED_SERIES = {
    "vix": "VIXCLS",
    "yield_10y": "DGS10",
    "yield_2y": "DGS2",
    "cpi": "CPIAUCSL",
    "fed_funds": "FEDFUNDS",
}

_fred: Any = None  # Fred instance or None if not configured


def _get_fred():
    """Lazy-initialize the Fred client, or return None if no key."""
    global _fred
    if _fred is None:
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            logger.warning(
                "FRED_API_KEY not set in .env — FRED data will be unavailable. "
                "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
            )
            _fred = False  # Sentinel to avoid repeated lookups
            return None
        try:
            from fredapi import Fred
            _fred = Fred(api_key=api_key)
        except ImportError:
            logger.error("fredapi package not installed — run: pip install fredapi")
            _fred = False
            return None
    return _fred if _fred is not False else None


def get_series(series_id: str, months: int = 12) -> list[dict[str, Any]]:
    """Fetch a FRED data series.

    Args:
        series_id: FRED series identifier (e.g., 'VIXCLS', 'DGS10').
        months: Number of months of history (approximate).

    Returns:
        List of {date, value} dicts, sorted by date ascending.
        Returns empty list if FRED is not configured.
    """
    fred = _get_fred()
    if fred is None:
        return []

    try:
        series: pd.Series = fred.get_series(series_id)
        if series.empty:
            return []

        # Filter to roughly the last N months
        cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)
        series = series[series.index >= cutoff]

        return [
            {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
            for d, v in series.dropna().items()
        ]
    except Exception as e:
        logger.error(f"FRED get_series({series_id}) failed: {e}")
        return []


def get_macro_snapshot() -> dict[str, Any]:
    """Fetch a snapshot of key macro indicators.

    VIX, yield spread (10Y - 2Y), CPI YoY, and Fed funds rate.

    Returns:
        Dict with:
            vix: float | None
            yield_spread: float | None
            yield_10y: float | None
            yield_2y: float | None
            cpi_yoy: float | None
            fed_funds_rate: float | None
            timestamp: str (ISO format)
        All values are None if FRED is not configured or calls fail.
    """
    from datetime import datetime, timezone

    snapshot: dict[str, Any] = {
        "vix": None,
        "yield_spread": None,
        "yield_10y": None,
        "yield_2y": None,
        "cpi_yoy": None,
        "fed_funds_rate": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    fred = _get_fred()
    if fred is None:
        return snapshot

    def _latest_value(series_id: str) -> float | None:
        """Get the most recent non-null value for a series."""
        try:
            s: pd.Series = fred.get_series(series_id)
            s = s.dropna()
            return round(float(s.iloc[-1]), 4) if not s.empty else None
        except Exception as e:
            logger.warning(f"FRED {series_id} lookup failed: {e}")
            return None

    # VIX
    vix = _latest_value(FRED_SERIES["vix"])

    # Yield curve
    y10 = _latest_value(FRED_SERIES["yield_10y"])
    y2 = _latest_value(FRED_SERIES["yield_2y"])

    # CPI YoY: compare latest to same month one year ago
    cpi_yoy = None
    try:
        cpi: pd.Series = fred.get_series(FRED_SERIES["cpi"])
        cpi = cpi.dropna()
        if len(cpi) >= 13:
            latest = float(cpi.iloc[-1])
            prior = float(cpi.iloc[-13])
            cpi_yoy = round(((latest - prior) / prior) * 100, 2)
    except Exception as e:
        logger.warning(f"FRED CPI YoY calculation failed: {e}")

    # Fed funds rate
    fed = _latest_value(FRED_SERIES["fed_funds"])

    snapshot.update({
        "vix": vix,
        "yield_10y": y10,
        "yield_2y": y2,
        "yield_spread": round(y10 - y2, 4) if (y10 is not None and y2 is not None) else None,
        "cpi_yoy": cpi_yoy,
        "fed_funds_rate": fed,
    })
    return snapshot