"""Tests for the dashboard adapter overview endpoint."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from synthetix_alpha.api.app import app
from synthetix_alpha.api.overview import build_overview, load_candidates, map_candidates, map_portfolio

client = TestClient(app)


def test_overview_response_shape() -> None:
    account = {
        "equity": "100000.00",
        "cash": "50000.00",
        "buying_power": "200000.00",
    }
    exposure = {
        "nav": 100_000.0,
        "cash": 50_000.0,
        "positions": [
            {
                "symbol": "SPY260919P00620000",
                "qty": -1.0,
                "avg_entry_price": 7.2,
                "unrealized_pl": 120.0,
                "asset_class": "us_option",
            },
            {
                "symbol": "SPY260919P00600000",
                "qty": 1.0,
                "avg_entry_price": 3.4,
                "unrealized_pl": -40.0,
                "asset_class": "us_option",
            },
        ],
        "unprotected": [{"symbol": "SPY260919P00620000", "qty": -1.0}],
    }
    rules = type("Rules", (), {"max_open_positions": 12, "max_premium_at_risk_pct": 0.03, "max_leverage": 1.0})()

    snapshot = build_overview(
        account_fn=lambda: account,
        exposure_fn=lambda: exposure,
        rules_loader=lambda: rules,
        candidates_fn=lambda: pd.DataFrame(),
    )

    for key in ("mode", "asOf", "warnings", "pipeline", "candidates", "portfolio", "executions", "performance", "system"):
        assert key in snapshot

    assert snapshot["mode"] == "paper"
    assert snapshot["pipeline"]["mode"] == "paper"
    assert snapshot["candidates"] == []
    assert snapshot["executions"] == []
    assert snapshot["performance"]["name"] == "put_vertical_ivrv"
    assert len(snapshot["performance"]["equity"]) > 0

    portfolio = snapshot["portfolio"]
    assert portfolio["nav"] == 100_000.0
    assert portfolio["cash"] == 50_000.0
    assert portfolio["aggregateUnrealizedPnl"] == 80.0
    assert portfolio["maxPositions"] == 12
    assert portfolio["premiumAtRiskCap"] == 3_000.0
    assert portfolio["dailyDrawdown"] is None
    assert portfolio["totalDrawdown"] is None
    assert len(portfolio["positions"]) == 2

    short_leg = next(p for p in portfolio["positions"] if p["quantity"] == -1)
    long_leg = next(p for p in portfolio["positions"] if p["quantity"] == 1)
    assert short_leg["protected"] is False
    assert long_leg["protected"] is True
    assert short_leg["underlying"] == "SPY"
    assert long_leg["underlying"] == "SPY"

    assert any("Buying power" in warning for warning in snapshot["warnings"])
    assert any("drawdown" in warning.lower() for warning in snapshot["warnings"])
    assert any("screener returned no candidates" in warning for warning in snapshot["warnings"])
    screen = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "SCREEN")
    assert screen["status"] == "pending"
    governance = snapshot["system"]["governance"]
    assert governance
    assert any(row["name"] == "Max position slots" and row["state"] == "enforced" for row in governance)
    assert any(row["name"] == "Sector concentration" and row["state"] == "configured_not_enforced" for row in governance)
    assert any(row["name"] == "Stop-loss / take-profit" and row["state"] == "configured_not_enforced" for row in governance)


def test_map_portfolio_without_buying_power_warning() -> None:
    portfolio, warnings = map_portfolio(
        {"equity": "1000", "cash": "500"},
        {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []},
        type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        as_of="2026-09-03T00:00:00Z",
    )
    assert portfolio["nav"] == 1000.0
    assert portfolio["positions"] == []
    assert portfolio["premiumAtRisk"] == 0.0
    assert portfolio["dailyDrawdown"] is None
    assert "Buying power" not in " ".join(warnings)


def test_overview_endpoint_uses_builder(monkeypatch) -> None:
    called = {"value": False}

    def fake_build() -> dict:
        called["value"] = True
        return {
            "mode": "paper",
            "asOf": "2026-09-03T00:00:00Z",
            "warnings": [],
            "pipeline": {"id": "x", "asOf": "2026-09-03T00:00:00Z", "mode": "paper", "finalState": "partial", "stages": [], "events": [], "errors": []},
            "candidates": [],
            "portfolio": {
                "nav": 1,
                "cash": 1,
                "aggregateUnrealizedPnl": 0,
                "positions": [],
                "maxPositions": 10,
                "premiumAtRisk": 0,
                "premiumAtRiskCap": 0,
                "remainingLeverage": 0,
                "dailyDrawdown": None,
                "totalDrawdown": None,
                "hardHalt": None,
            },
            "executions": [],
            "performance": {"name": "unavailable", "source": "historical", "period": "", "sharpe": 0, "maxDrawdown": 0, "winRate": 0, "trades": 0, "profitFactor": 0, "oosSharpe": None, "fragilityMedian": None, "equity": [], "annualReturns": [], "gateSweep": [], "fragility": [], "comparisons": [], "tradePnL": [], "generationHistory": [], "sampleComparisons": []},
            "system": {"api": {"source": "Dashboard adapter", "asOf": "2026-09-03T00:00:00Z", "status": "fresh"}, "sources": [], "warnings": [], "governance": []},
        }

    monkeypatch.setattr("synthetix_alpha.api.app.build_overview", fake_build)
    response = client.get("/v1/overview")
    assert response.status_code == 200
    assert called["value"] is True
    assert response.json()["mode"] == "paper"


def test_map_candidates_from_screener_dataframe() -> None:
    df = pd.DataFrame(
        {
            "iv": [23.6, 40.0],
            "hv": [16.6, 30.0],
            "iv_rv": [1.42, 1.33],
            "iv_rank": [0.81, 0.5],
            "price": [641.82, 572.1],
            "avg_dollar_volume": [12_800_000_000.0, 8_600_000_000.0],
            "date": [dt.date(2026, 8, 31), dt.date(2026, 8, 31)],
        },
        index=["SPY", "QQQ"],
    )

    mapped = map_candidates(df, as_of="2026-09-03T00:00:00Z")
    assert len(mapped) == 2
    assert mapped[0]["ticker"] == "SPY"
    assert mapped[0]["iv"] == pytest.approx(0.236)
    assert mapped[0]["hv"] == pytest.approx(0.166)
    assert mapped[0]["ivRv"] == 1.42
    assert mapped[0]["ivRank"] == 0.81
    assert mapped[0]["price"] == 641.82
    assert mapped[0]["avgDollarVolume"] == 12_800_000_000.0
    assert mapped[0]["critic"]["decision"] == "PENDING"
    assert mapped[0]["risk"] == "UNAVAILABLE"
    assert mapped[0]["updatedAt"].startswith("2026-08-31")
    assert mapped[1]["ticker"] == "QQQ"
    assert mapped[1]["iv"] == 0.4


def test_load_candidates_failure_returns_warning() -> None:
    def boom() -> pd.DataFrame:
        raise RuntimeError("dolt unavailable")

    candidates, _df, warnings = load_candidates(
        as_of="2026-09-03T00:00:00Z",
        candidates_fn=boom,
    )
    assert candidates == []
    assert any("Opportunity screener unavailable" in w for w in warnings)
    assert "dolt unavailable" in warnings[0]


def test_load_candidates_empty_scan_warns() -> None:
    candidates, _df, warnings = load_candidates(
        as_of="2026-09-03T00:00:00Z",
        candidates_fn=lambda: pd.DataFrame(),
    )
    assert candidates == []
    assert any("no candidates in regime today" in w for w in warnings)


def test_load_candidates_maps_nonempty_screener_dataframe() -> None:
    """Regression: adapter must map a real screener-shaped MPC/PSX frame into candidates."""
    screen_df = pd.DataFrame(
        {
            "date": [dt.date(2026, 9, 1), dt.date(2026, 9, 1)],
            "iv": [0.466, 0.385],
            "hv": [0.372, 0.296],
            "iv_rv": [1.253, 1.301],
            "iv_rank": [1.0, 0.815],
            "price": [387.0, 256.09],
            "avg_dollar_volume": [8.337976e8, 6.236698e8],
            "days_to_earnings": [61.0, 56.0],
        },
        index=["MPC", "PSX"],
    )

    candidates, returned_df, warnings = load_candidates(
        as_of="2026-09-03T00:00:00Z",
        candidates_fn=lambda: screen_df,
    )

    assert warnings == []
    assert list(returned_df.index) == ["MPC", "PSX"]
    assert [c["ticker"] for c in candidates] == ["MPC", "PSX"]
    assert candidates[0]["iv"] == pytest.approx(0.466)
    assert candidates[0]["ivRv"] == pytest.approx(1.253)
    assert candidates[1]["price"] == pytest.approx(256.09)


def test_build_overview_screens_before_account_calls() -> None:
    """Regression: screener runs before Alpaca CLI account reads (matches CLI invocation order)."""
    call_order: list[str] = []
    screen_df = pd.DataFrame(
        {"iv": [0.4], "hv": [0.3], "iv_rv": [1.3], "iv_rank": [0.8], "price": [100.0], "avg_dollar_volume": [1e8]},
        index=["MPC"],
    )

    snapshot = build_overview(
        account_fn=lambda: (call_order.append("account") or {"equity": "1000", "cash": "500"}),
        exposure_fn=lambda: (call_order.append("exposure") or {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []}),
        rules_loader=lambda: type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        candidates_fn=lambda: (call_order.append("screen") or screen_df),
        gather_fn=lambda _df: ([], []),
    )

    assert call_order.index("screen") < call_order.index("account")
    assert call_order.index("screen") < call_order.index("exposure")
    assert snapshot["candidates"][0]["ticker"] == "MPC"
    assert not any("screener returned no candidates" in w for w in snapshot["warnings"])
    screen_stage = next(stage for stage in snapshot["pipeline"]["stages"] if stage["stage"] == "SCREEN")
    assert screen_stage["status"] == "complete"
    assert screen_stage["result"] == "1 candidates"


def test_build_overview_includes_mapped_candidates() -> None:
    screen_df = pd.DataFrame(
        {"iv": [25.0], "hv": [20.0], "iv_rv": [1.25], "iv_rank": [0.7], "price": [100.0], "avg_dollar_volume": [1e8]},
        index=["AAPL"],
    )
    snapshot = build_overview(
        account_fn=lambda: {"equity": "1000", "cash": "500"},
        exposure_fn=lambda: {"nav": 1000.0, "cash": 500.0, "positions": [], "unprotected": []},
        rules_loader=lambda: type("Rules", (), {"max_open_positions": 10, "max_premium_at_risk_pct": 0.02, "max_leverage": 1.0})(),
        candidates_fn=lambda: screen_df,
        gather_fn=lambda _df: ([], []),
    )
    assert len(snapshot["candidates"]) == 1
    assert snapshot["candidates"][0]["ticker"] == "AAPL"
    assert snapshot["candidates"][0]["iv"] == 0.25
