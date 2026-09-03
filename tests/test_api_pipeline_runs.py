"""Tests for dry-run pipeline adapter endpoint."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from fastapi.testclient import TestClient

from synthetix_alpha.api.app import app
from synthetix_alpha.api.pipeline_runs import serialize_pipeline_result
from synthetix_alpha.pipeline.orchestrator import PipelineResult

client = TestClient(app)


class _FakeOrchestrator:
    def run_daily(self, iv_rv_min: float = 1.25, limit: int = 15, *, dry_run: bool = True):
        assert dry_run is True
        assert iv_rv_min == 1.25
        assert limit == 15
        result = PipelineResult(
            candidates=pd.DataFrame(index=["SPY"]),
            timestamp=dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc),
            errors=[],
        )
        return result


def test_serialize_pipeline_result_summary() -> None:
    result = PipelineResult(
        candidates=pd.DataFrame(index=["SPY", "QQQ"]),
        timestamp=dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc),
        errors=["FORM: unresolved legs"],
    )
    payload = serialize_pipeline_result(result)
    assert payload["dryRun"] is True
    assert payload["summary"]["screened"] == 2
    assert "Dry pipeline complete" in payload["detail"]
    assert payload["errors"] == ["FORM: unresolved legs"]


def test_pipeline_runs_rejects_live(monkeypatch) -> None:
    monkeypatch.setattr("synthetix_alpha.api.app.run_dry_pipeline", lambda **_: {"dryRun": True})
    response = client.post("/v1/pipeline/runs", json={"dryRun": False})
    assert response.status_code == 400
    assert "dryRun=true" in response.json()["detail"]


def test_pipeline_runs_dry_only(monkeypatch) -> None:
    def fake_run(**kwargs):
        assert kwargs.get("iv_rv_min") == 1.25
        return serialize_pipeline_result(_FakeOrchestrator().run_daily(dry_run=True))

    monkeypatch.setattr("synthetix_alpha.api.app.run_dry_pipeline", fake_run)
    response = client.post("/v1/pipeline/runs", json={"dryRun": True})
    assert response.status_code == 200
    body = response.json()
    assert body["dryRun"] is True
    assert body["summary"]["screened"] == 1
