"""FastAPI dashboard adapter — read-only portfolio overview for the Next.js frontend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from synthetix_alpha.api.overview import build_overview

app = FastAPI(title="Synthetix Alpha Dashboard Adapter", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["Accept"],
)


@app.get("/v1/overview")
def overview() -> dict:
    return build_overview()
