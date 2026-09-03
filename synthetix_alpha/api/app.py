"""FastAPI dashboard adapter — read-only portfolio overview for the Next.js frontend."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from synthetix_alpha.api.overview import build_overview
from synthetix_alpha.api.overview_service import start_prewarm
from synthetix_alpha.api.pipeline_runs import run_dry_pipeline

# Local Next.js + production Vercel frontend. Override with comma-separated CORS_ORIGINS.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "https://synthetix-alpha.vercel.app",
)


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_prewarm()
    yield


app = FastAPI(title="Synthetix Alpha Dashboard Adapter", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
)


@app.get("/v1/overview")
def overview() -> dict:
    return build_overview()


@app.post("/v1/pipeline/runs")
def create_pipeline_run(payload: dict = Body(default_factory=dict)) -> dict:
    """Accept dry-run pipeline requests only. Never submits live brokerage orders."""
    dry_run = payload.get("dryRun", True)
    if dry_run is not True:
        raise HTTPException(
            status_code=400,
            detail="Only dryRun=true is supported by the dashboard adapter. Live submission is disabled.",
        )
    try:
        return run_dry_pipeline(
            iv_rv_min=float(payload.get("ivRvMin", 1.25)),
            limit=int(payload.get("limit", 15)),
        )
    except Exception as exc:  # noqa: BLE001 — surface adapter failure honestly
        raise HTTPException(status_code=502, detail=f"Dry pipeline failed: {exc}") from exc
