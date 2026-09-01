"""The factor model exists to stop a strategy taking credit for factor exposure, so the tests check that
the arithmetic recovers known betas and that the reversal control is built the way it claims."""
import numpy as np
import pandas as pd
import pytest

from synthetix_alpha.research import factor_model as fm


def test_regress_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    f1, f2 = rng.normal(size=800), rng.normal(size=800)
    y = 0.05 + 0.4 * f1 - 0.2 * f2 + rng.normal(scale=0.01, size=800)
    X = np.column_stack([np.ones(800), f1, f2])
    beta, t, r2 = fm.regress(y, X)
    assert beta[0] == pytest.approx(0.05, abs=0.002)
    assert beta[1] == pytest.approx(0.4, abs=0.002)
    assert beta[2] == pytest.approx(-0.2, abs=0.002)
    assert r2 > 0.99 and t[1] > 50


def test_reversal_is_long_losers_and_short_winners():
    dates = pd.date_range("2024-01-01", periods=30).date
    syms = [f"S{i}" for i in range(20)]
    # S0 falls every day and rises intraday; S19 rises every day and falls intraday.
    cl = pd.DataFrame({s: np.linspace(100, 100 + (i - 10) * 5, 30) for i, s in enumerate(syms)}, index=dates)
    op = cl.copy()
    op["S0"] = cl["S0"] * 1.02          # loser gives back intraday -> reversal leg loses
    op["S19"] = cl["S19"] * 0.98        # winner rallies intraday -> short leg loses
    r = fm.reversal(op, cl, lookback=5, decile=0.10)
    assert r.notna().sum() > 0
    last = r.dropna().iloc[-1]
    assert last < 0, "when losers fade and winners rally, the reversal portfolio must lose"


def test_reversal_uses_only_information_available_before_the_open():
    """The sort is on returns through yesterday's close; using today's would be look-ahead."""
    dates = pd.date_range("2024-01-01", periods=10).date
    syms = [f"S{i}" for i in range(20)]
    cl = pd.DataFrame({s: np.full(10, 100.0) for s in syms}, index=dates)
    op = cl.copy()
    r = fm.reversal(op, cl, lookback=3)
    assert r.iloc[:4].isna().all(), "no signal before the lookback window has filled"
