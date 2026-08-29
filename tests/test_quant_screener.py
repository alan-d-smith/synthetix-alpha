"""
test_quant_screener.py — Unit tests for the deterministic quant screener.

Tests VWAP deviation, RVOL, RSI, Bollinger position, MACD signal,
and composite score computation using synthetic OHLCV fixtures.
"""
from __future__ import annotations

import pytest

from engine.quant_screener import (
    _bars_to_pandas,
    _compute_bollinger_position,
    _compute_composite_score,
    _compute_macd_signal,
    _compute_rsi,
    _compute_rvol,
    _compute_vwap_deviation,
    screen_bars,
    screen_universe,
)


# ============================================================
# VWAP deviation tests
# ============================================================

class TestVwapDeviation:
    def test_flat_price_zero_deviation(self, flat_price_bars: list[dict]) -> None:
        """Close == VWAP → deviation = 0."""
        df = _bars_to_pandas(flat_price_bars)
        assert _compute_vwap_deviation(df) == 0.0

    def test_vwap_above_close_negative(self, vwap_above_close_bars: list[dict]) -> None:
        """Close ($100) < VWAP ($101) → negative deviation ~ -0.0099."""
        df = _bars_to_pandas(vwap_above_close_bars)
        dev = _compute_vwap_deviation(df)
        assert dev == pytest.approx(-0.009900, abs=0.0001)


# ============================================================
# RVOL tests
# ============================================================

class TestRvol:
    def test_flat_volume_rvol_one(self, flat_price_bars: list[dict]) -> None:
        df = _bars_to_pandas(flat_price_bars)
        assert _compute_rvol(df, window=20) == 1.0

    def test_volume_spike_rvol_elevated(self, volume_spike_bars: list[dict]) -> None:
        df = _bars_to_pandas(volume_spike_bars)
        # Last bar = 100k, prior 20 avg = (16×10k + 4×50k)/20 = 18k
        # RVOL = 100k / 18k = 5.5556
        assert _compute_rvol(df, window=20) == pytest.approx(5.5556, abs=0.01)

    def test_rvol_insufficient_bars(self) -> None:
        import pandas as pd
        df = pd.DataFrame({"volume": [10000] * 10})
        assert _compute_rvol(df, window=20) == 1.0
# ============================================================
# RSI tests
# ============================================================

class TestRsi:
    def test_uptrend_rsi_100(self, uptrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(uptrend_bars)
        assert _compute_rsi(df["close"].astype(float), window=14) == 100.0

    def test_downtrend_rsi_0(self, downtrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(downtrend_bars)
        assert _compute_rsi(df["close"].astype(float), window=14) == 0.0

    def test_uptrend_rsi_gt_downtrend(
        self, uptrend_bars: list[dict], downtrend_bars: list[dict]
    ) -> None:
        df_up = _bars_to_pandas(uptrend_bars)
        df_down = _bars_to_pandas(downtrend_bars)
        assert _compute_rsi(df_up["close"].astype(float)) > _compute_rsi(
            df_down["close"].astype(float)
        )


# ============================================================
# Bollinger position tests
# ============================================================

class TestBollingerPosition:
    def test_flat_price_position_mid(self, flat_price_bars: list[dict]) -> None:
        df = _bars_to_pandas(flat_price_bars)
        pos = _compute_bollinger_position(df["close"].astype(float), window=20)
        assert pos == 0.5

    def test_downtrend_near_lower_band(self, downtrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(downtrend_bars)
        pos = _compute_bollinger_position(df["close"].astype(float), window=20)
        assert pos is not None and pos < 0.2

    def test_uptrend_near_upper_band(self, uptrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(uptrend_bars)
        pos = _compute_bollinger_position(df["close"].astype(float), window=20)
        assert pos is not None and pos > 0.8


# ============================================================
# MACD signal tests
# ============================================================

class TestMacdSignal:
    def test_flat_price_macd_neutral(self, flat_price_bars: list[dict]) -> None:
        df = _bars_to_pandas(flat_price_bars)
        assert _compute_macd_signal(df["close"].astype(float)) == "neutral"

    def test_uptrend_macd_bullish(self, uptrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(uptrend_bars)
        assert _compute_macd_signal(df["close"].astype(float)) == "bullish"

    def test_downtrend_macd_bearish(self, downtrend_bars: list[dict]) -> None:
        df = _bars_to_pandas(downtrend_bars)
        assert _compute_macd_signal(df["close"].astype(float)) == "bearish"


# ============================================================
# Composite score tests
# ============================================================

class TestCompositeScore:
    def test_score_in_bounds(self) -> None:
        for vwap, rvol, rsi, boll, macd in [
            (0.0, 1.0, 50.0, 0.5, "neutral"),
            (0.04, 10.0, 0.0, 0.0, "bullish"),
            (-0.04, 0.5, 100.0, 1.0, "bearish"),
        ]:
            s = _compute_composite_score(vwap, rvol, rsi, boll, macd)
            assert 0.0 <= s <= 1.0

    def test_downtrend_oversold_bullish(self) -> None:
        """RSI=0 (0.30), Boll position=0 (0.20), MACD bearish (0.0),
        VWAP=0 (0.10), RVOL=1 (0.0) → expected 0.60."""
        s = _compute_composite_score(0.0, 1.0, 0.0, 0.0, "bearish")
        assert s == pytest.approx(0.60, abs=0.01)

    def test_uptrend_overbought_bearish(self) -> None:
        """RSI=100 (0.0), Boll position=1 (0.0), MACD bullish (0.15),
        VWAP=0 (0.10), RVOL=1 (0.0) → expected 0.25."""
        s = _compute_composite_score(0.0, 1.0, 100.0, 1.0, "bullish")
        assert s == pytest.approx(0.25, abs=0.01)


# ============================================================
# screen_bars / screen_universe tests
# ============================================================

class TestScreenBars:
    def test_insufficient_bars_returns_none(self, short_bars: list[dict]) -> None:
        assert screen_bars(short_bars, "TEST") is None

    def test_returns_signal_dict(self, flat_price_bars: list[dict]) -> None:
        signal = screen_bars(flat_price_bars, "TEST")
        assert signal is not None
        assert signal["ticker"] == "TEST"
        for key in ("vwap_deviation", "rvol", "rsi", "bollinger_position",
                     "macd_signal", "composite_score"):
            assert key in signal


class TestScreenUniverse:
    def test_empty_input(self) -> None:
        assert screen_universe({}) == []

    def test_sorts_by_composite_score(self, flat_price_bars: list[dict]) -> None:
        signals = screen_universe({"A": flat_price_bars, "B": flat_price_bars})
        assert len(signals) == 2
        assert signals[0]["composite_score"] >= signals[1]["composite_score"]

    def test_skips_insufficient_bars(
        self, short_bars: list[dict], flat_price_bars: list[dict]
    ) -> None:
        signals = screen_universe({"GOOD": flat_price_bars, "BAD": short_bars})
        assert len(signals) == 1
        assert signals[0]["ticker"] == "GOOD"


# ============================================================
# Safety guard
# ============================================================

class TestSafetyGuard:
    def test_no_gs_quant_session_import(self) -> None:
        import engine.quant_screener as qs
        source = qs.__file__ or ""
        with open(source, "r") as f:
            code = f.read()
        assert "gs_quant.session" not in code
        assert "GsSession" not in code
        assert "gs_quant.markets" not in code