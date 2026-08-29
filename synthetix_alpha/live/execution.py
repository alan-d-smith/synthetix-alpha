"""Alpaca order submission for option spreads. Paper only, idempotent, dry-run by default."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, OrderType, PositionIntent, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, OptionLegRequest

from synthetix_alpha import config

STORE = config.ROOT / "datasets" / "orders.json"
SIDE = {"long": OrderSide.BUY, "short": OrderSide.SELL}
INTENT = {"long": PositionIntent.BUY_TO_OPEN, "short": PositionIntent.SELL_TO_OPEN}


def assert_paper() -> None:
    """Paper is a literal here, never read from env."""
    if os.environ.get("ALPACA_LIVE_TRADE", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError("ALPACA_LIVE_TRADE is set — this module is paper-only. Unset it to proceed.")


def client() -> TradingClient:
    assert_paper()
    key, secret = config.credentials()
    return TradingClient(key, secret, paper=True)


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


def build_order(legs: list[dict], contracts: int, limit_price: float, coid: Optional[str] = None,
                tif: TimeInForce = TimeInForce.DAY) -> LimitOrderRequest:
    """legs = [{"symbol": OCC, "side": "long"|"short", "ratio": int}]; limit_price = net debit (+) or credit (-)."""
    if not 1 <= len(legs) <= 4:
        raise ValueError("Alpaca supports 1-4 option legs per order")
    if contracts < 1:
        raise ValueError("contracts must be >= 1")
    ratios = [int(l.get("ratio", 1)) for l in legs]
    if len(legs) > 1 and max(ratios) > 1:
        from math import gcd
        from functools import reduce
        if reduce(gcd, ratios) != 1:
            raise ValueError("leg ratios must be in simplest form (gcd == 1)")
    order_legs = [OptionLegRequest(symbol=l["symbol"], side=SIDE[l["side"]], ratio_qty=int(l.get("ratio", 1)),
                                   position_intent=INTENT[l["side"]]) for l in legs]
    return LimitOrderRequest(
        qty=contracts, limit_price=round(abs(limit_price), 2), type=OrderType.LIMIT, time_in_force=tif,
        order_class=OrderClass.MLEG if len(legs) > 1 else OrderClass.SIMPLE,
        legs=order_legs, client_order_id=coid or client_order_id(legs),
        **({} if len(legs) > 1 else {"symbol": legs[0]["symbol"], "side": SIDE[legs[0]["side"]],
                                     "position_intent": INTENT[legs[0]["side"]]}),
    )


def submit(legs: list[dict], contracts: int, limit_price: float, *, dry_run: bool = True,
           trading: Optional[TradingClient] = None, store: Path = STORE) -> dict:
    """Returns a preview when dry_run (the default)."""
    coid = client_order_id(legs)
    preview = {"client_order_id": coid, "legs": legs, "contracts": contracts,
               "limit_price": round(limit_price, 2), "net": "credit" if limit_price < 0 else "debit"}
    if already_submitted(coid, store):
        return {**preview, "status": "duplicate", "detail": "already submitted today"}
    req = build_order(legs, contracts, limit_price, coid)
    if dry_run:
        return {**preview, "status": "dry_run"}
    order = (trading or client()).submit_order(req)
    track_order(coid, {**preview, "order_id": str(order.id), "status": str(order.status)}, store)
    return {**preview, "status": str(order.status), "order_id": str(order.id)}


def find_missing_brackets(positions: list[Any], orders: list[Any]) -> list[dict]:
    """Open option positions with no resting closing order."""
    resting = {str(getattr(l, "symbol", "")) for o in orders for l in (getattr(o, "legs", None) or [o])}
    out = []
    for p in positions:
        sym = str(getattr(p, "symbol", ""))
        if getattr(p, "asset_class", None) and "option" not in str(p.asset_class).lower():
            continue
        if sym and sym not in resting:
            out.append({"symbol": sym, "qty": getattr(p, "qty", None),
                        "unrealized_pl": getattr(p, "unrealized_pl", None)})
    return out


def open_exposure(trading: Optional[TradingClient] = None) -> dict:
    """Account snapshot in the shape `live.risk.apply` expects."""
    t = trading or client()
    acct = t.get_account()
    positions = [{"symbol": p.symbol, "qty": float(p.qty), "avg_entry_price": float(p.avg_entry_price),
                  "unrealized_pl": float(p.unrealized_pl or 0)} for p in t.get_all_positions()]
    unprotected = find_missing_brackets(t.get_all_positions(), t.get_orders(GetOrdersRequest(status="open")))
    return {"nav": float(acct.equity), "cash": float(acct.cash), "positions": positions,
            "unprotected": unprotected}
