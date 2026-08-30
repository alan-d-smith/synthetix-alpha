"""Alpaca CLI transport. Every account read and order goes through the `alpaca` binary rather than the SDK,
which is what the Trading API integration requires; the SDK is used only for market data."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional

from synthetix_alpha import config

SIDE = {"long": "buy", "short": "sell"}
INTENT = {"long": "buy_to_open", "short": "sell_to_open"}


def _env() -> dict:
    key, secret = config.credentials()
    env = {**os.environ, "ALPACA_API_KEY": key, "ALPACA_SECRET_KEY": secret}
    env.pop("ALPACA_LIVE_TRADE", None)  # paper is the CLI default; never let the environment opt into live
    return env


def run(*args: str, jq: Optional[str] = None) -> Any:
    """Invoke the CLI and parse its JSON. Raises on the CLI's own error envelope."""
    cmd = [config.ALPACA_BIN, *args, "--quiet"] + (["--jq", jq] if jq else [])
    out = subprocess.run(cmd, capture_output=True, text=True, env=_env(), timeout=120)
    text = (out.stdout or "").strip()
    if not text:
        raise RuntimeError(f"alpaca {' '.join(args)} failed: {(out.stderr or '').strip()[:300]}")
    data = json.loads(text)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"alpaca {' '.join(args)}: {data['error']}")
    return data


def account() -> dict:
    return run("account", "get")


def positions() -> list[dict]:
    return run("position", "list") or []


def orders(status: str = "open") -> list[dict]:
    return run("order", "list", "--status", status) or []


def contracts(underlying: str, *, kind: str = "put", exp_gte: str = "", exp_lte: str = "",
              strike_gte: float = 0.0, strike_lte: float = 0.0, limit: int = 500) -> list[dict]:
    """Tradable contracts for an underlying, filtered server-side."""
    args = ["option", "contracts", "--underlying-symbols", underlying, "--type", kind, "--limit", str(limit)]
    for flag, value in (("--expiration-date-gte", exp_gte), ("--expiration-date-lte", exp_lte),
                        ("--strike-price-gte", strike_gte or ""), ("--strike-price-lte", strike_lte or "")):
        if value:
            args += [flag, str(value)]
    return run(*args).get("option_contracts", [])


def submit(legs: list[dict], contracts_qty: int, limit_price: float, coid: str, *, dry_run: bool = True) -> dict:
    """legs = [{"symbol": OCC, "side": "long"|"short", "ratio": int}]. Price is the absolute net limit."""
    payload = [{"symbol": l["symbol"], "side": SIDE[l["side"]], "ratio_qty": str(int(l.get("ratio", 1))),
                "position_intent": INTENT[l["side"]]} for l in legs]
    args = ["order", "submit", "--type", "limit", "--time-in-force", "day",
            "--qty", str(contracts_qty), "--limit-price", f"{abs(limit_price):.2f}", "--client-order-id", coid]
    if len(legs) > 1:
        args += ["--order-class", "mleg", "--legs", json.dumps(payload)]
    else:
        args += ["--symbol", legs[0]["symbol"], "--side", SIDE[legs[0]["side"]],
                 "--position-intent", INTENT[legs[0]["side"]]]
    return run(*args, *(["--dry-run"] if dry_run else []))
