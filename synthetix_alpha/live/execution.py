"""Alpaca order submission for option spreads. Paper only, idempotent, dry-run by default.

Orders go out through the Alpaca CLI (`live.cli`), not the SDK.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from synthetix_alpha import config
from synthetix_alpha.live import cli

STORE = config.ROOT / "datasets" / "orders.json"


def assert_paper() -> None:
    """Paper is a literal here, never read from env."""
    if os.environ.get("ALPACA_LIVE_TRADE", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError("ALPACA_LIVE_TRADE is set — this module is paper-only. Unset it to proceed.")


def client_order_id(legs: list[dict], date: Optional[dt.date] = None, tag: str = "sx") -> str:
    """Same spread + same day -> same id, so a retry cannot double-fill."""
    key = "|".join(sorted(f"{l['side']}{l['ratio']}{l['symbol']}" for l in legs))
    digest = hashlib.sha1(f"{key}@{date or dt.date.today()}".encode()).hexdigest()[:16]
    return f"{tag}-{digest}"


def _load(store: Path) -> dict:
    return json.loads(store.read_text()) if store.exists() else {}


def track_order(coid: str, payload: dict, store: Path = STORE) -> None:
    """Record a submission so the same spread is refused today."""
    store.parent.mkdir(parents=True, exist_ok=True)
    orders = _load(store)
    orders[coid] = {"submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(), **payload}
    store.write_text(json.dumps(orders, indent=1, default=str))


def already_submitted(coid: str, store: Path = STORE) -> bool:
    return coid in _load(store)


def build_order(legs: list[dict], contracts: int, limit_price: float, coid: Optional[str] = None) -> dict:
    """legs = [{"symbol": OCC, "side": "long"|"short", "ratio": int}]; limit_price = net debit (+) or credit (-)."""
    if not 1 <= len(legs) <= 4:
        raise ValueError("Alpaca supports 1-4 option legs per order")
    if contracts < 1:
        raise ValueError("contracts must be >= 1")
    ratios = [int(l.get("ratio", 1)) for l in legs]
    if len(legs) > 1 and max(ratios) > 1:
        from functools import reduce
        from math import gcd
        if reduce(gcd, ratios) != 1:
            raise ValueError("leg ratios must be in simplest form (gcd == 1)")
    return {"order_class": "mleg" if len(legs) > 1 else "simple", "qty": contracts,
            "limit_price": round(abs(limit_price), 2), "time_in_force": "day", "type": "limit",
            "client_order_id": coid or client_order_id(legs),
            "legs": [{"symbol": l["symbol"], "side": cli.SIDE[l["side"]], "ratio_qty": str(int(l.get("ratio", 1))),
                      "position_intent": cli.INTENT[l["side"]]} for l in legs]}


def submit(legs: list[dict], contracts: int, limit_price: float, *, dry_run: bool = True,
           store: Path = STORE) -> dict:
    """Returns a preview when dry_run (the default)."""
    assert_paper()
    coid = client_order_id(legs)
    preview = {"client_order_id": coid, "legs": legs, "contracts": contracts,
               "limit_price": round(limit_price, 2), "net": "credit" if limit_price < 0 else "debit"}
    if already_submitted(coid, store):
        return {**preview, "status": "duplicate", "detail": "already submitted today"}
    build_order(legs, contracts, limit_price, coid)  # validate before touching the wire
    if dry_run:
        return {**preview, "status": "dry_run"}
    order = cli.submit(legs, contracts, limit_price, coid, dry_run=False)
    track_order(coid, {**preview, "order_id": order.get("id"), "status": order.get("status")}, store)
    return {**preview, "status": order.get("status"), "order_id": order.get("id")}


def find_missing_brackets(positions: list[dict], orders: list[dict]) -> list[dict]:
    """Open option positions with no resting closing order."""
    resting = {str(l.get("symbol", "")) for o in orders for l in (o.get("legs") or [o])}
    out = []
    for p in positions:
        sym = str(p.get("symbol", ""))
        if p.get("asset_class") and "option" not in str(p["asset_class"]).lower():
            continue
        if sym and sym not in resting:
            out.append({"symbol": sym, "qty": p.get("qty"), "unrealized_pl": p.get("unrealized_pl")})
    return out


def open_exposure() -> dict:
    """Account snapshot in the shape `live.risk.apply` expects."""
    acct, pos = cli.account(), cli.positions()
    positions = [{"symbol": p["symbol"], "qty": float(p["qty"]), "avg_entry_price": float(p["avg_entry_price"]),
                  "unrealized_pl": float(p.get("unrealized_pl") or 0),
                  "asset_class": p.get("asset_class", "us_equity")} for p in pos]
    return {"nav": float(acct["equity"]), "cash": float(acct["cash"]), "positions": positions,
            "unprotected": find_missing_brackets(pos, cli.orders("open"))}
