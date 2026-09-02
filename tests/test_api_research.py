"""Tests for the dashboard adapter research performance loader."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from synthetix_alpha.api.overview import build_overview
from synthetix_alpha.api.research import empty_performance, load_generation_history, load_performance


def _sample_snapshot() -> dict:
    return {
        "name": "put_vertical_ivrv",
        "source": "historical",
        "period": "Kaggle EOD chains · SPY + QQQ · 2020–2022",
        "sharpe": 0.92,
        "maxDrawdown": -0.02,
        "winRate": 0.68,
        "trades": 102,
        "profitFactor": 1.42,
        "oosSharpe": 0.67,
        "fragilityMedian": 0.94,
        "equity": [
            {"date": "2020-01-02", "equity": 100000, "drawdown": 0},
            {"date": "2020-06-01", "equity": 103820, "drawdown": -0.002},
        ],
        "annualReturns": [{"year": "2020", "value": 0.034}],
        "gateSweep": [{"gate": "1.27", "score": 1.11, "deployed": True}],
        "fragility": [{"parameter": "DTE −10", "score": 0.85}],
        "comparisons": [{"name": "put_vertical_ivrv", "sharpe": 0.92, "maxDrawdown": -0.02, "trades": 102}],
        "tradePnL": [{"bucket": "0–$0.5k", "count": 39}],
        "sampleComparisons": [
            {
                "sample": "in_sample",
                "label": "In sample · Kaggle SPY/QQQ 2020–2022",
                "sharpe": 0.92,
                "maxDrawdown": -0.02,
                "trades": 102,
                "detail": "Historical research after liquidity floor.",
            }
        ],
    }


def _progress_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "evaluated_utc": "2026-08-29 16:59",
                "gen": 4,
                "strategy": "put_vertical_ivrv",
                "underlyings": "SPY+QQQ",
                "total_return": 0.0569,
                "mean_sharpe": 0.918,
                "worst_drawdown": -0.02,
                "trades": 102,
                "score": 0.52,
                "note": "liquidity floor correction",
                "correction": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_performance_missing_snapshot_returns_unavailable(tmp_path: Path) -> None:
    performance, warnings = load_performance(snapshot_path=tmp_path / "missing.json")

    assert performance == empty_performance()
    assert len(warnings) == 1
    assert "not available" in warnings[0]


def test_load_performance_maps_snapshot(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "put_vertical_ivrv_snapshot.json"
    snapshot_path.write_text(json.dumps(_sample_snapshot()), encoding="utf-8")
    progress_log = tmp_path / "progress.jsonl"
    _progress_fixture(progress_log)

    performance, warnings = load_performance(snapshot_path=snapshot_path, progress_log=progress_log)

    assert warnings == []
    assert performance["name"] == "put_vertical_ivrv"
    assert performance["sharpe"] == 0.92
    assert performance["equity"][0]["date"] == "2020-01-02"
    assert performance["gateSweep"][0]["deployed"] is True
    assert performance["generationHistory"][0]["strategy"] == "put_vertical_ivrv"
    assert performance["generationHistory"][0]["deployed"] is True
    assert performance["generationHistory"][0]["correction"] is True
    assert performance["generationHistory"][0]["evaluatedAt"] == "2026-08-29T16:59:00Z"


def test_load_generation_history_from_progress_jsonl(tmp_path: Path) -> None:
    progress_log = tmp_path / "progress.jsonl"
    _progress_fixture(progress_log)

    history = load_generation_history(progress_log=progress_log)

    assert len(history) == 1
    row = history[0]
    assert row["generation"] == 4
    assert row["meanReturn"] == 0.0569
    assert row["meanSharpe"] == 0.918
    assert row["maxDrawdown"] == -0.02


def test_build_overview_includes_loaded_performance(tmp_path: Path, monkeypatch) -> None:
    snapshot_path = tmp_path / "docs" / "dashboard" / "put_vertical_ivrv_snapshot.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(_sample_snapshot()), encoding="utf-8")
    _progress_fixture(tmp_path / "docs" / "progress.jsonl")

    monkeypatch.setattr("synthetix_alpha.api.research.config.ROOT", tmp_path)
    monkeypatch.setattr("synthetix_alpha.api.research.DEFAULT_SNAPSHOT", snapshot_path)

    account = {"equity": "100000.00", "cash": "50000.00"}
    exposure = {"nav": 100_000.0, "cash": 50_000.0, "positions": [], "unprotected": []}
    rules = type("Rules", (), {"max_open_positions": 12, "max_premium_at_risk_pct": 0.03, "max_leverage": 1.0})()

    snapshot = build_overview(
        account_fn=lambda: account,
        exposure_fn=lambda: exposure,
        rules_loader=lambda: rules,
        candidates_fn=lambda: pd.DataFrame(),
    )

    assert snapshot["performance"]["name"] == "put_vertical_ivrv"
    assert len(snapshot["performance"]["equity"]) == 2
    assert len(snapshot["performance"]["generationHistory"]) == 1
    assert not any("research snapshot" in warning.lower() for warning in snapshot["warnings"])
