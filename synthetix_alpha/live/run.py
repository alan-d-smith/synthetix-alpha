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

import os

from synthetix_alpha import config
from synthetix_alpha.data.alpaca import AlpacaClient
from synthetix_alpha.live import cli, crypto, equity, execution, intraday, risk, screen, window
from synthetix_alpha.strategy import engine
from synthetix_alpha.strategy.spec import Spec

SPEC = "strategies/put_vertical_singlename.json"
MULT = 100


def plan_one(symbol: str, spec: Spec, equity: float, client: AlpacaClient,
             risk_cap: Optional[float] = None, min_fill_ratio: float = 0.6) -> Optional[dict]:
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
    # A mid-price limit on an illiquid spread either sits unfilled or has to cross a bid-ask worth more than
    # the credit itself. Only take spreads that still pay after crossing.
    fill = 0.0
    for leg in legs:
        row = chain.loc[leg.symbol]
        fill += (-float(row["bid"]) if leg.side < 0 else float(row["ask"])) * leg.ratio
    if -fill < min_fill_ratio * -entry or -fill < spec.min_credit:
        return {"skip": f"credit {-entry:.2f} at mid but {-fill:.2f} after crossing"}
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


def plan(limit: int = 5, spec_path: str = SPEC, equity: Optional[float] = None,
         min_fill_ratio: float = 0.6) -> dict:
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
            o = plan_one(sym, spec, nav, client, rules.max_premium_at_risk_pct, min_fill_ratio)
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


def use_account(name: str) -> None:
    """Point this process at one account. Everything downstream reads the standard vars, so selecting here
    means no module can accidentally reach the other account."""
    key, secret = config.credentials(name)
    os.environ["ALPACA_API_KEY"], os.environ["ALPACA_API_SECRET"] = key, secret
    os.environ["ALPACA_SECRET_KEY"] = secret


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", choices=["research", "deployed"], default="research")
    ap.add_argument("--ignore-window", action="store_true",
                    help="dry runs only: skip the competition window check")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--execute", action="store_true", help="submit for real (default is a dry run)")
    ap.add_argument("--intraday-top", type=int, default=20, help="gap-fade names, flat by the close (0 disables)")
    ap.add_argument("--intraday-budget", type=float, default=0.60, help="fraction of NAV for the intraday sleeve")
    ap.add_argument("--crypto-budget", type=float, default=0.15,
                    help="fraction of NAV for the crypto dislocation sleeve (0 disables)")
    ap.add_argument("--topup", action="store_true",
                    help="buy back whatever the opening entry failed to fill, and cover it market-on-close")
    ap.add_argument("--flatten", action="store_true",
                    help="reconcile open longs against resting sells and cover the gap (run before 15:50 ET)")
    ap.add_argument("--equity-top", type=int, default=0, help="overnight momentum names (0 disables)")
    ap.add_argument("--equity-budget", type=float, default=0.20, help="fraction of NAV for the momentum sleeve")
    a = ap.parse_args()
    if a.ignore_window and a.execute:
        ap.error("--ignore-window cannot be combined with --execute: live orders must respect the window")
    use_account(a.account)
    acct = cli.account()
    print(f"account {acct['account_number']} ({a.account})  equity ${float(acct['equity']):,.2f}  "
          f"cash ${float(acct['cash']):,.2f}")
    print(window.describe())
    gate = window.can_flatten if a.flatten else window.can_enter
    allowed, why = gate()
    if not allowed and not a.ignore_window:
        print(f"REFUSING TO TRADE: {why}")
        return
    if a.topup:
        rows = intraday.topup(dry_run=not a.execute)
        for r in rows:
            print(f"{r['symbol']:<6} intended {r['intended']:>4}  held {r['held']:>4}  buying {r['qty']:>4}  "
                  f"filled {r.get('filled_qty', 0):>4,.0f}  buy {r['buy']}  exit {r['exit']}")
        print("entry filled as planned, nothing to top up" if not rows else f"{len(rows)} name(s) topped up")
        return
    if a.flatten:
        rows = intraday.flatten(dry_run=not a.execute)
        for r in rows:
            print(f"{r['symbol']:<6} held {r['held']:>8,.2f}  resting {r['resting_sell']:>8,.2f}  "
                  f"uncovered {r['uncovered']:>8,.2f}  {r['status']}")
        print("every long is covered by a resting sell" if not rows else f"{len(rows)} position(s) needed cover")
        return
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
            print(f"{o['symbol']:<6} {o['qty']:>5} sh  ${o['notional']:>9,.0f}  gap {o['gap']:+.2%} (z {o['z']:+.1f})  "
                  f"buy {o['buy']} / exit {o['exit']}")
        if not picks:
            print("no gap-down candidates")
    if a.crypto_budget:
        print(f"\ncrypto dislocations (z < -{crypto.THRESHOLD}, {a.crypto_budget:.0%} of NAV, {crypto.HOLD}h hold):")
        cr = crypto.plan(p["nav"], budget_pct=a.crypto_budget)
        for o in crypto.enter(cr, dry_run=not a.execute):
            print(f"{o['symbol']:<10} {o['qty']:>13,.6f}  ${o['notional']:>8,.0f}  z {o['z']:+.2f}  "
                  f"24h {o['move_24h']:+.1%}  {o['status']}")
        if not cr:
            print("  nothing dislocated enough, sleeve silent (expected ~16 signals/year)")
    if a.equity_top:
        print(f"\novernight momentum ({a.equity_budget:.0%} of NAV):")
        eq = equity.plan(p["nav"], AlpacaClient(), top_n=a.equity_top, budget_pct=a.equity_budget)
        for o in equity.submit_all(eq, dry_run=not a.execute):
            print(f"{o['symbol']:<6} {o['qty']:>4} sh  ${o['notional']:>9,.0f}  mom {o['momentum']:+.1%}  {o['status']}")
        if not eq:
            print("no equity candidates")


if __name__ == "__main__":
    main()
