"""
quant_screener.py — Stage 2: Deterministic Quant Engine.

Runs on the full universe using gs_quant.timeseries.technicals for RSI,
Bollinger Bands, and MACD. VWAP deviation, RVOL, and composite scoring
are computed directly. No LLM involvement. No Marquee credentials.

Signals:
    - 15m VWAP deviation: (close - bar_vwap) / bar_vwap
    - RVOL > 2       : relative volume vs 20-period average
    - RSI mean-reversion : oversold < 30 → bullish, overbought > 70 → bearish
    - Bollinger Bands    : normalized position within bands
    - MACD               : trend direction

Output: structured signal list with tickers + raw indicator values.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from gs_quant.timeseries.technicals import (
    bollinger_bands,
    macd,
    relative_strength_index,
)


def _bars_to_pandas(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of bar dicts to a pandas DataFrame indexed by timestamp."""
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df


def _compute_vwap_deviation(df: pd.DataFrame) -> float:
    """Compute VWAP deviation for the most recent bar: (close - vwap) / vwap."""
    if df.empty or "vwap" not in df.columns:
        return 0.0
    try:
        last = df.iloc[-1]
        vwap = float(last["vwap"])
        close = float(last["close"])
        if vwap == 0:
            return 0.0
        return (close - vwap) / vwap
    except Exception as e:
        logger.warning(f"VWAP deviation compute failed: {e}")
        return 0.0


def _compute_rvol(df: pd.DataFrame, window: int = 20) -> float:
    """Compute RVOL: latest volume / average of prior window volumes."""
    if df.empty or "volume" not in df.columns:
        return 1.0
    volumes = df["volume"].astype(float)
    if len(volumes) < window + 1:
        return 1.0
    latest = volumes.iloc[-1]
    avg_prior = volumes.iloc[-(window + 1):-1].mean()
    if avg_prior == 0:
        return 1.0
    return round(float(latest / avg_prior), 4)


def _compute_rsi(close: pd.Series, window: int = 14) -> float:
    """Compute latest RSI via gs_quant relative_strength_index."""
    try:
        rsi_series = relative_strength_index(close, w=window)
        if rsi_series.empty:
            return 50.0
        return round(float(rsi_series.iloc[-1]), 4)
    except Exception as e:
        logger.warning(f"RSI computation failed: {e}")
        return 50.0


def _compute_bollinger_position(
    close: pd.Series, window: int = 20, k: float = 2.0
) -> float | None:
    """Normalized position within Bollinger Bands: 0.0 = lower, 0.5 = mid, 1.0 = upper."""
    try:
        bands_df = bollinger_bands(close, w=window, k=k)
        if bands_df.empty or bands_df.shape[1] < 2:
            return None
        lower = bands_df.iloc[-1, 0]
        upper = bands_df.iloc[-1, 1]
        last_close = close.iloc[-1]
        band_range = upper - lower
        if band_range == 0:
            return 0.5
        position = (last_close - lower) / band_range
        return round(float(np.clip(position, 0.0, 1.0)), 4)
    except Exception as e:
        logger.warning(f"Bollinger position failed: {e}")
        return None


def _compute_macd_signal(
    close: pd.Series, m: int = 12, n: int = 26, s: int = 9
) -> str:
    """MACD trend: bullish if line > 0, bearish if < 0, else neutral."""
    try:
        macd_line = macd(close, m=m, n=n, s=s)
        if macd_line.empty:
            return "neutral"
        latest = float(macd_line.iloc[-1])
        if latest > 0:
            return "bullish"
        elif latest < 0:
            return "bearish"
        return "neutral"
    except Exception as e:
        logger.warning(f"MACD computation failed: {e}")
        return "neutral"


def _compute_composite_score(
    vwap_deviation: float,
    rvol: float,
    rsi: float,
    bollinger_position: float | None,
    macd_signal_str: str,
) -> float:
    """Weighted composite score 0.0–1.0. Higher = stronger bullish signal.

    Weights: VWAP 0.20, RVOL 0.15, RSI 0.30, Bollinger 0.20, MACD 0.15
    """
    score = 0.0

    # VWAP (0.20): positive deviation above VWAP is bullish.
    # Scale [-0.02, +0.02] → [0, 1], clamp to [0, 1].
    vwap_component = max(0.0, min(1.0, vwap_deviation / 0.02 * 0.5 + 0.5))
    score += 0.20 * vwap_component

    # RVOL (0.15): RVOL 1.0 → 0.0, RVOL 3.0+ → 1.0 (linear)
    rvol_component = min(1.0, max(0.0, (rvol - 1.0) / 2.0))
    score += 0.15 * rvol_component

    # RSI (0.30): oversold (< 30) = bullish, overbought (> 70) = bearish.
    # Linear: RSI 0 → 1.0, RSI 100 → 0.0
    rsi_component = 1.0 - rsi / 100.0
    score += 0.30 * rsi_component

    # Bollinger (0.20): near lower band (position 0.0) = bullish reversal
    bollinger_component = 1.0 - bollinger_position if bollinger_position is not None else 0.5
    score += 0.20 * bollinger_component

    # MACD (0.15)
    macd_map = {"bullish": 1.0, "neutral": 0.5, "bearish": 0.0}
    score += 0.15 * macd_map.get(macd_signal_str, 0.5)

    return round(max(0.0, min(1.0, score)), 4)
def screen_bars(bars: list[dict[str, Any]], ticker: str) -> dict[str, Any] | None:
    """Run the quant screen on a single ticker's bar data.

    Args:
        bars: List of bar dicts from alpaca_market_data.get_bars().
        ticker: Ticker symbol.

    Returns:
        Signal dict with indicators + composite_score, or None if insufficient data.
    """
    min_bars = 30
    if len(bars) < min_bars:
        logger.debug(f"{ticker}: insufficient bars ({len(bars)} < {min_bars})")
        return None

    df = _bars_to_pandas(bars)
    if df.empty:
        return None

    close = df["close"].astype(float)

    vwap_dev = round(_compute_vwap_deviation(df), 6)
    rvol = _compute_rvol(df, window=20)
    rsi = _compute_rsi(close, window=14)
    boll_pos = _compute_bollinger_position(close, window=20, k=2.0)
    macd_str = _compute_macd_signal(close, m=12, n=26, s=9)
    composite = _compute_composite_score(vwap_dev, rvol, rsi, boll_pos, macd_str)

    return {
        "ticker": ticker,
        "vwap_deviation": vwap_dev,
        "rvol": rvol,
        "rsi": rsi,
        "bollinger_position": boll_pos,
        "macd_signal": macd_str,
        "composite_score": composite,
    }


def screen_universe(
    ticker_bars: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Run the full quant screen on a universe of tickers.

    Args:
        ticker_bars: Dict mapping ticker -> list of bar dicts (from
            alpaca_market_data.get_bars()).

    Returns:
        List of signal dicts, sorted by composite_score descending.
    """
    signals: list[dict[str, Any]] = []
    for ticker, bars in ticker_bars.items():
        signal = screen_bars(bars, ticker)
        if signal is not None:
            signals.append(signal)

    signals.sort(key=lambda s: s["composite_score"], reverse=True)
    logger.info(
        f"Quant screener: {len(signals)} signals from {len(ticker_bars)} tickers"
    )
    return signals