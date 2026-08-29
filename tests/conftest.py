"""
conftest.py — Shared pytest fixtures.

Provides mock objects for Alpaca API, Finnhub, LLM, sample configs,
and sample signals so every test module has consistent test data.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_universe() -> list[str]:
    """A small sample universe of tickers for testing."""
    return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]


@pytest.fixture
def sample_governance_rules() -> dict:
    """Sample governance rules dict (mirrors config/governance.yaml)."""
    return {
        "max_leverage": 1.0,
        "max_single_position_pct": 0.10,
        "max_sector_concentration_pct": 0.30,
        "max_open_positions": 10,
        "max_daily_drawdown_pct": 0.05,
        "max_weekly_drawdown_pct": 0.10,
        "max_total_drawdown_pct": 0.20,
        "defined_risk_only": True,
        "max_premium_at_risk_pct": 0.02,
    }


@pytest.fixture
def sample_quant_signals() -> list[dict]:
    """Sample quant screener output signals."""
    return [
        {
            "ticker": "AAPL",
            "vwap_deviation": 0.025,
            "rvol": 2.5,
            "rsi": 32.0,
            "bollinger_position": -1.2,
            "macd_signal": "bullish",
            "composite_score": 0.78,
        },
        {
            "ticker": "MSFT",
            "vwap_deviation": -0.015,
            "rvol": 1.2,
            "rsi": 55.0,
            "bollinger_position": 0.3,
            "macd_signal": "neutral",
            "composite_score": 0.45,
        },
    ]


@pytest.fixture
def sample_research_output() -> list[dict]:
    """Sample research agent output signals."""
    return [
        {
            "ticker": "AAPL",
            "sentiment": "bullish",
            "confidence_score": 0.82,
            "thesis": "Strong iPhone upgrade cycle with services revenue growth accelerating.",
            "macro_alignment": "aligned",
        },
        {
            "ticker": "MSFT",
            "sentiment": "neutral",
            "confidence_score": 0.55,
            "thesis": "Azure growth steady, but enterprise spending uncertainty.",
            "macro_alignment": "neutral",
        },
    ]


@pytest.fixture
def sample_account_nav() -> float:
    """Sample account NAV for sizing tests."""
    return 100_000.0


# ============================================================
# Synthetic OHLCV fixtures for quant_screener tests
# ============================================================

def _make_bar(timestamp: str, o: float, h: float, l: float, c: float,
              v: int, vwap: float | None = None) -> dict:
    """Create a single bar dict matching the alpaca_market_data.get_bars() format."""
    return {
        "timestamp": timestamp,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "vwap": vwap if vwap is not None else c,
        "trade_count": 100,
    }


@pytest.fixture
def flat_price_bars() -> list[dict]:
    """30 bars with all prices = $100, volume = 10,000, vwap = $100."""
    bars = []
    for i in range(30):
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        bars.append(_make_bar(ts, 100.0, 100.0, 100.0, 100.0, 10000))
    return bars


@pytest.fixture
def uptrend_bars() -> list[dict]:
    """30 bars with price climbing linearly from $100 to $114.50."""
    bars = []
    for i in range(30):
        price = 100.0 + i * 0.5
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        bars.append(_make_bar(ts, price, price + 0.1, price - 0.1, price, 10000))
    return bars


@pytest.fixture
def downtrend_bars() -> list[dict]:
    """30 bars with price falling linearly from $100 to $85.50."""
    bars = []
    for i in range(30):
        price = 100.0 - i * 0.5
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        bars.append(_make_bar(ts, price, price + 0.1, price - 0.1, price, 10000))
    return bars


@pytest.fixture
def volume_spike_bars() -> list[dict]:
    """30 bars: first 25 vol=10k, last 5 vol=50k, last bar vol=100k."""
    bars = []
    for i in range(30):
        price = 100.0
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        if i < 25:
            vol = 10000
        elif i < 29:
            vol = 50000
        else:
            vol = 100000
        bars.append(_make_bar(ts, price, price, price, price, vol))
    return bars


@pytest.fixture
def vwap_above_close_bars() -> list[dict]:
    """30 bars: price = $100, but VWAP = $101 (close below VWAP)."""
    bars = []
    for i in range(30):
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        bars.append(_make_bar(ts, 100.0, 100.0, 100.0, 100.0, 10000, vwap=101.0))
    return bars


@pytest.fixture
def short_bars() -> list[dict]:
    """Only 10 bars — insufficient for screening."""
    bars = []
    for i in range(10):
        ts = f"2026-08-28T{(i // 60):02d}:{(i % 60):02d}:00Z"
        bars.append(_make_bar(ts, 100.0, 100.0, 100.0, 100.0, 10000))
    return bars