"""Read-only research performance loader for the dashboard adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from synthetix_alpha import config
from synthetix_alpha.strategy.progress import load as load_progress_rows

DEFAULT_SNAPSHOT = config.ROOT / "docs" / "dashboard" / "put_vertical_ivrv_snapshot.json"
DEPLOYED_STRATEGY = "put_vertical_ivrv"

_PERFORMANCE_KEYS = (
    "name",
    "source",
    "period",
    "sharpe",
    "maxDrawdown",
    "winRate",
    "trades",
    "profitFactor",
    "oosSharpe",
    "fragilityMedian",
    "equity",
    "annualReturns",
    "gateSweep",
    "fragility",
    "comparisons",
    "tradePnL",
    "generationHistory",
    "sampleComparisons",
)


def empty_performance() -> dict[str, Any]:
    return {
        "name": "unavailable",
        "source": "historical",
        "period": "Not loaded in adapter v1",
        "sharpe": 0,
        "maxDrawdown": 0,
        "winRate": 0,
        "trades": 0,
        "profitFactor": 0,
        "oosSharpe": None,
        "fragilityMedian": None,
        "equity": [],
        "annualReturns": [],
        "gateSweep": [],
        "fragility": [],
        "comparisons": [],
        "tradePnL": [],
        "generationHistory": [],
        "sampleComparisons": [],
    }


def _evaluated_at(value: str) -> str:
    text = value.strip()
    if "T" in text:
        return text if text.endswith("Z") else f"{text}Z"
    return f"{text.replace(' ', 'T')}:00Z"


def _map_generation_row(row: dict[str, Any]) -> dict[str, Any]:
    record = {
        "evaluatedAt": _evaluated_at(str(row["evaluated_utc"])),
        "generation": int(row["gen"]),
        "strategy": str(row["strategy"]),
        "underlyings": str(row["underlyings"]),
        "meanReturn": float(row["total_return"]),
        "meanSharpe": float(row["mean_sharpe"]),
        "maxDrawdown": float(row["worst_drawdown"]),
        "trades": int(row["trades"]),
        "score": float(row["score"]),
        "note": str(row.get("note", "")),
    }
    if row.get("correction"):
        record["correction"] = True
    if record["strategy"] == DEPLOYED_STRATEGY:
        record["deployed"] = True
    return record


def load_generation_history(*, progress_log: Path | None = None) -> list[dict[str, Any]]:
    """Map docs/progress.jsonl rows to the frontend GenerationRecord shape."""
    rows = load_progress_rows(progress_log or config.ROOT / "docs" / "progress.jsonl")
    return [_map_generation_row(row) for row in rows]


def _map_snapshot(raw: dict[str, Any], generation_history: list[dict[str, Any]]) -> dict[str, Any]:
    performance = empty_performance()
    performance.update({key: raw[key] for key in _PERFORMANCE_KEYS if key in raw})
    performance["generationHistory"] = generation_history
    return performance


def load_performance(
    *,
    snapshot_path: Path | None = None,
    progress_log: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Load precomputed research performance; never runs backtests."""
    path = snapshot_path or DEFAULT_SNAPSHOT
    if not path.is_file():
        return empty_performance(), [
            f"Historical research snapshot is not available ({path.name}).",
        ]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return empty_performance(), [
            f"Historical research snapshot could not be read ({path.name}): {exc}.",
        ]

    if not isinstance(raw, dict):
        return empty_performance(), [
            f"Historical research snapshot is invalid ({path.name}): expected a JSON object.",
        ]

    generation_history = load_generation_history(progress_log=progress_log)
    return _map_snapshot(raw, generation_history), []
