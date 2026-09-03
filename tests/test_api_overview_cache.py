"""Tests for dashboard overview TTL caches and prewarm."""

from __future__ import annotations

import pandas as pd

from synthetix_alpha.api.overview import build_overview, load_candidates
from synthetix_alpha.api.overview_service import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def test_load_candidates_cache_reuses_live_screener_within_ttl(monkeypatch) -> None:
    calls = {"n": 0}
    screen_df = pd.DataFrame(
        {"iv": [25.0], "hv": [20.0], "iv_rv": [1.25], "iv_rank": [0.7], "price": [100.0], "avg_dollar_volume": [1e8]},
        index=["AAPL"],
    )

    def fake_candidates(*_args, **_kwargs) -> pd.DataFrame:
        calls["n"] += 1
        return screen_df

    monkeypatch.setattr("synthetix_alpha.live.screen.candidates", fake_candidates)
    load_candidates(as_of="2026-09-03T00:00:00Z")
    _, _, w2 = load_candidates(as_of="2026-09-03T00:01:00Z")

    assert calls["n"] == 1
    assert any("in-process cache" in w for w in w2)


def test_build_overview_reuses_exposure_for_risk() -> None:
    exposure_calls = {"n": 0}
    screen_df = pd.DataFrame(
        {"iv": [25.0], "hv": [20.0], "iv_rv": [1.25], "iv_rank": [0.7], "price": [100.0], "avg_dollar_volume": [1e8]},
        index=["AAPL"],
    )

    def exposure_fn() -> dict:
        exposure_calls["n"] += 1
        return {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []}

    formed = [{"symbol": "AAPL", "defined_risk": True, "max_loss": 100.0}]

    snapshot = build_overview(
        account_fn=lambda: {"equity": "1000", "cash": "500"},
        exposure_fn=exposure_fn,
        rules_loader=lambda: type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        candidates_fn=lambda: screen_df,
        gather_fn=lambda _df: ([], []),
        critique_fn=lambda _inputs: ([], "live"),
        form_fn=lambda _approved, _df: formed,
        use_cache=False,
    )

    assert exposure_calls["n"] == 1
    assert snapshot["portfolio"]["nav"] == 1000.0
