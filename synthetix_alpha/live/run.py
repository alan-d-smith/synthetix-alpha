"""Daily live run: screen for in-regime names, build the deployed spread on each, gate it, submit via the CLI.

Dry-run by default. The spec drives leg selection and sizing, so live and backtest share one code path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import replace

import pandas as pd
from typing import Optional

from synthetix_alpha.data.alpaca import AlpacaClient
from synthetix_alpha.live import cli, equity, execution, intraday, risk, screen
from synthetix_alpha.strategy import engine
from synthetix_alpha.strategy.spec import Spec

SPEC = "strategies/put_vertical_singlename.json"
MULT = 100


def plan_one(symbol: str, spec: Spec, equity: float, client: AlpacaClient,
             risk_cap: Optional[float] = None) -> Optional[dict]:
    """Select legs on the live chain and size them, or None when the chain cannot support the spread.

    Sizing takes the lower of the spec's risk_fraction and the live per-position cap, so the governance
    rules bind live sizing without ever exceeding what was backtested.
    """
    today = dt.date.today()
    chain = client.option_chain(symbol, type="put",
                                expiration_date_gte=(today + dt.timedelta(days=spec.dte_min)).isoformat(),
                                expiration_date_lte=(today + dt.timedelta(days=spec.dte_max)).isoformat())
    if chain.empty:
        return {"skip": "no chain"}
    chain = chain.copy()
    chain["dte"] = (pd.to_datetime(chain["expiration"]).dt.date - today).map(lambda d: d.days)
    bars = client.stock_bars([symbol], "1Day", today - dt.timedelta(days=10), today)
    if bars.empty:
        return {"skip": "no bars"}
    spot = float(bars["close"].iloc[-1])
    legs = engine.select(spec, chain, spot)
    if not legs:
        return {"skip": "no legs at target delta/dte"}
    entry = sum(l.side * l.ratio * l.mark for l in legs)  # negative = net credit
    if -entry < spec.min_credit:
        return {"skip": f"credit {-entry:.2f} < {spec.min_credit}"}
    loss = engine.max_loss(legs, entry, spot)
    if risk_cap is not None and risk_cap < spec.risk_fraction:
        spec = replace(spec, risk_fraction=risk_cap)
    contracts = engine.size(spec, legs, entry, spot, equity)
    if contracts < 1 or loss <= 0:
        return {"skip": f"size {contracts} at ${loss * MULT:.0f} risk/contract"}
    return {"symbol": symbol, "legs": [{"symbol": l.symbol, "side": "long" if l.side > 0 else "short",
                                        "ratio": l.ratio} for l in legs],
            "contracts": contracts, "limit_price": round(entry, 2), "credit": round(-entry * MULT * contracts, 2),
            "max_loss": round(loss * MULT * contracts, 2), "defined_risk": True}


def plan(limit: int = 5, spec_path: str = SPEC, equity: Optional[float] = None) -> dict:
    """Screen, build a spread per candidate, then run the risk gates over the batch."""
    spec = Spec.load(spec_path)
    client = AlpacaClient()
    rules = risk.Rules.load()
    exposure = execution.open_exposure()
    nav = equity if equity is not None else exposure["nav"]
    names = screen.candidates(iv_rv_min=spec.signal.get("iv_rv_ratio", [1.27])[0], limit=limit * 3)
    orders, skipped = [], {}
    for sym in list(names.index):
        if len(orders) >= limit:
            break
        try:
            o = plan_one(sym, spec, nav, client, rules.max_premium_at_risk_pct)
        except Exception as e:
            o = None
            print(f"  {sym}: {type(e).__name__}: {e}")
        if o and "skip" not in o:
            orders.append(o)
        elif o:
            skipped[sym] = o["skip"]
    decision = risk.apply(orders, exposure["positions"], nav)
    return {"nav": nav, "screened": list(names.index), "skipped": skipped, "orders": orders,
            "approved": decision.approved, "halts": decision.halts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--execute", action="store_true", help="submit for real (default is a dry run)")
    ap.add_argument("--intraday-top", type=int, default=10, help="gap-fade names, flat by the close (0 disables)")
    ap.add_argument("--intraday-budget", type=float, default=0.40, help="fraction of NAV for the intraday sleeve")
    ap.add_argument("--equity-top", type=int, default=0, help="overnight momentum names (0 disables)")
    ap.add_argument("--equity-budget", type=float, default=0.20, help="fraction of NAV for the momentum sleeve")
    a = ap.parse_args()
    p = plan(a.limit, a.spec)
    print(json.dumps({k: p[k] for k in ("nav", "skipped", "halts")}, indent=1, default=str))
    for o in p["approved"]:
        res = execution.submit(o["legs"], o["contracts"], o["limit_price"], dry_run=not a.execute)
        print(f"{o['symbol']:<6} {o['contracts']:>3}x  credit ${o['credit']:>8,.0f}  risk ${o['max_loss']:>9,.0f}  {res['status']}")
    if not p["approved"]:
        print("no approved option spreads today")
    if a.intraday_top:
        print(f"\nintraday gap-fade ({a.intraday_budget:.0%} of NAV, flat by the close):")
        client = AlpacaClient()
        picks = intraday.plan(p["nav"], client, n=a.intraday_top, budget_pct=a.intraday_budget)
        for o in intraday.enter(picks, dry_run=not a.execute):
            print(f"{o['symbol']:<6} {o['qty']:>5} sh  ${o['notional']:>9,.0f}  gap {o['gap']:+.2%}  "
                  f"buy {o['buy']} / exit {o['exit']}")
        if not picks:
            print("no gap-down candidates")
    if a.equity_top:
        print(f"\novernight momentum ({a.equity_budget:.0%} of NAV):")
        eq = equity.plan(p["nav"], AlpacaClient(), top_n=a.equity_top, budget_pct=a.equity_budget)
        for o in equity.submit_all(eq, dry_run=not a.execute):
            print(f"{o['symbol']:<6} {o['qty']:>4} sh  ${o['notional']:>9,.0f}  mom {o['momentum']:+.1%}  {o['status']}")
        if not eq:
            print("no equity candidates")


if __name__ == "__main__":
    main()
