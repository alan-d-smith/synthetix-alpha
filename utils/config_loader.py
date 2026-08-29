"""
config_loader.py — Centralized YAML configuration loading.

Loads universe, governance, and settings from config/ directory.
No network calls, no credentials — pure file I/O.
"""
from __future__ import annotations

import os
from typing import Any

import yaml
from loguru import logger

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_yaml(path: str) -> dict[str, Any]:
    """Load a YAML file, returning {} if missing or unparseable."""
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        logger.warning(f"Config file not found: {path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse {path}: {e}")
        return {}


def load_governance_rules() -> dict[str, Any]:
    """Load governance rules from config/governance.yaml.

    Returns a flat dict with keys: max_leverage, max_single_position_pct,
    max_open_positions, max_daily_drawdown_pct, etc.
    """
    path = os.path.join(PROJECT_ROOT, "config", "governance.yaml")
    raw = _load_yaml(path)
    rules = raw.get("governance", {})
    logger.info(f"Governance rules loaded: {len(rules)} keys")
    return rules


def load_settings() -> dict[str, Any]:
    """Load operational settings from config/settings.yaml."""
    path = os.path.join(PROJECT_ROOT, "config", "settings.yaml")
    raw = _load_yaml(path)
    settings = raw.get("settings", {})
    logger.info(f"Settings loaded: {len(settings)} keys")
    return settings


def load_universe_tickers() -> list[str]:
    """Load ticker universe from config/universe.yaml.

    If ticker_allowlist is populated, use it. Otherwise, fall back to a
    default high-liquidity universe of ~20 US large-cap stocks.
    """
    # Default high-liquidity universe (top ~20 stocks by avg $ volume)
    DEFAULT_UNIVERSE = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
        "COST", "NFLX", "AMD", "PEP", "LIN", "ADBE", "QCOM", "TXN",
        "INTU", "AMAT", "ISRG", "CMCSA",
    ]

    path = os.path.join(PROJECT_ROOT, "config", "universe.yaml")
    raw = _load_yaml(path)
    universe = raw.get("universe", {})

    allowlist: list[str] = universe.get("ticker_allowlist", [])
    denylist: set[str] = {t.upper() for t in universe.get("ticker_denylist", [])}

    if allowlist:
        tickers = [t.strip().upper() for t in allowlist if t.strip().upper() not in denylist]
        logger.info(f"Universe: {len(tickers)} tickers from allowlist")
        return tickers

    logger.info(f"Universe: {len(DEFAULT_UNIVERSE)} tickers (default)")
    return DEFAULT_UNIVERSE