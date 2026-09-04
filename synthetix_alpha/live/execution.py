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


def normalize_broker_status(raw: Optional[str]) -> str:
    """Map Alpaca order status strings to dashboard execution statuses."""
    status = str(raw or "").strip().lower()
    if status in {"filled"}:
        return "filled"
    if status in {"partially_filled"}:
        return "pending"
    if status in {"canceled", "cancelled", "expired", "replaced"}:
        return "cancelled"
    if status in {"rejected", "stopped", "suspended"}:
        return "rejected"
    if status in {"new", "accepted", "pending_new", "accepted_for_bidding", "pending_replace",
                  "pending_cancel", "calculated", "held", "done_for_day"}:
        return "pending"
    if status in {"dry_run", "duplicate", "error", "submitted", "unavailable", "skipped_no_legs"}:
        return status
    return "pending" if status else "unavailable"


def find_broker_order_by_coid(coid: str) -> Optional[dict]:
    """Look up an existing Alpaca order by client_order_id (authoritative idempotency)."""
    if not coid:
        return None
    for status in ("open", "closed", "all"):
        try:
            orders = cli.orders(status) or []
        except Exception:
            continue
        for order in orders:
            if str(order.get("client_order_id") or "") == coid:
                return order
    return None


def get_order_status(order_id: str) -> dict:
    """Fetch truthful broker state for one Alpaca order id."""
    assert_paper()
    raw = cli.order(order_id)
    status = normalize_broker_status(raw.get("status"))
    return {
        "order_id": raw.get("id") or order_id,
        "client_order_id": raw.get("client_order_id"),
        "status": status,
        "broker_status": raw.get("status"),
        "filled_qty": raw.get("filled_qty"),
        "filled_avg_price": raw.get("filled_avg_price"),
        "submitted_at": raw.get("submitted_at"),
        "filled_at": raw.get("filled_at"),
        "legs": raw.get("legs") or [],
        "raw": raw,
    }


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
    """Returns a preview when dry_run (the default). Paper only; idempotent by client order id."""
    assert_paper()
    coid = client_order_id(legs)
    preview = {"client_order_id": coid, "legs": legs, "contracts": contracts,
               "limit_price": round(limit_price, 2), "net": "credit" if limit_price < 0 else "debit"}
    if already_submitted(coid, store):
        prior = _load(store).get(coid) or {}
        return {
            **preview,
            "status": "duplicate",
            "detail": "already submitted today",
            "order_id": prior.get("order_id"),
        }
    existing = None if dry_run else find_broker_order_by_coid(coid)
    if existing:
        status = normalize_broker_status(existing.get("status"))
        return {
            **preview,
            "status": "duplicate",
            "detail": "matching Alpaca client_order_id already exists",
            "order_id": existing.get("id"),
            "broker_status": existing.get("status"),
            "normalized_status": status,
        }
    build_order(legs, contracts, limit_price, coid)  # validate before touching the wire
    if dry_run:
        return {**preview, "status": "dry_run"}
    order = cli.submit(legs, contracts, limit_price, coid, dry_run=False)
    broker_status = order.get("status")
    normalized = normalize_broker_status(broker_status)
    # Never claim filled unless Alpaca itself reported filled.
    status = "filled" if normalized == "filled" else (
        "submitted" if normalized in {"pending", "submitted"} else normalized
    )
    track_order(
        coid,
        {**preview, "order_id": order.get("id"), "status": status, "broker_status": broker_status},
        store,
    )
    return {
        **preview,
        "status": status,
        "broker_status": broker_status,
        "order_id": order.get("id"),
        "detail": f"Alpaca status: {broker_status}",
    }


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
