"""CORS configuration for the dashboard adapter."""

from __future__ import annotations

from fastapi.testclient import TestClient

from synthetix_alpha.api.app import _DEFAULT_CORS_ORIGINS, app, cors_origins

client = TestClient(app)

PRODUCTION_ORIGIN = "https://synthetix-alpha.vercel.app"


def test_default_cors_origins_include_production_and_localhost() -> None:
    origins = cors_origins()
    assert PRODUCTION_ORIGIN in origins
    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins
    assert origins == list(_DEFAULT_CORS_ORIGINS)


def test_cors_allows_production_vercel_origin(monkeypatch) -> None:
    monkeypatch.setattr(
        "synthetix_alpha.api.app.build_overview",
        lambda: {"mode": "paper"},
    )
    response = client.get("/v1/overview", headers={"Origin": PRODUCTION_ORIGIN})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN


def test_cors_preflight_allows_production_vercel_origin() -> None:
    response = client.options(
        "/v1/overview",
        headers={
            "Origin": PRODUCTION_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "accept,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN
