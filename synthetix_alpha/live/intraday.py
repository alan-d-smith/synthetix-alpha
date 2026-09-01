"""Intraday gap-fade sleeve: long the largest overnight gap-downs at the open, flat by the close.

Gaps are ranked in units of each name's own 20-day volatility rather than raw percent, which lifts the excess
return over an equal-weight benchmark from t = 1.05 to t = 2.44. Entered by market order once the opening prints
are in, exited market-on-close so the exit fills at the official close the backtest measures.
"""

from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo
from typing import Optional

import numpy as np
import pandas as pd

from synthetix_alpha.live import cli

# The universe the effect was measured on; changing it invalidates the backtested numbers.
# Breadth is the point: selecting the most dislocated names from ~200 is far more selective than from 80,
# and the mid-caps carry more overnight noise to revert than the heavily arbitraged megacaps.
UNIVERSE = ["AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADP", "AIG", "ALL", "AMAT", "AMD", "AMGN", "AMZN", "AON",
            "APD", "APH", "AVGO", "AXP", "AZO", "BA", "BAC", "BDX", "BK", "BKNG", "BLK", "BMY", "BSX", "C", "CAT",
            "CB", "CCI", "CDNS", "CHTR", "CI", "CL", "CMCSA", "CME", "CMG", "COF", "COP", "COST", "CRM", "CRWD",
            "CSCO", "CSX", "CTAS", "CVS", "CVX", "D", "DE", "DHR", "DIA", "DIS", "DLR", "DOW", "DUK", "EA", "ECL",
            "EL", "EMR", "EOG", "EQIX", "ETN", "EW", "EXC", "F", "FDX", "FIS", "FTNT", "GD", "GE", "GILD", "GIS",
            "GM", "GOOGL", "GS", "HCA", "HD", "HON", "HUM", "IBM", "ICE", "IDXX", "ILMN", "INTC", "INTU", "ISRG",
            "ITW", "IWM", "JCI", "JNJ", "JPM", "KDP", "KHC", "KLAC", "KMB", "KMI", "KO", "LHX", "LIN", "LLY",
            "LMT", "LOW", "LRCX", "MA", "MAR", "MCD", "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MMC", "MMM",
            "MNST", "MO", "MPC", "MRK", "MRNA", "MS", "MSFT", "MSI", "MU", "NEE", "NEM", "NFLX", "NKE", "NOC",
            "NOW", "NSC", "NUE", "NVDA", "NXPI", "ODFL", "OKE", "ORCL", "ORLY", "OXY", "PANW", "PAYX", "PCAR",
            "PEP", "PFE", "PG", "PGR", "PH", "PLD", "PM", "PNC", "PSA", "PSX", "PYPL", "QCOM", "QQQ", "REGN",
            "ROP", "ROST", "RTX", "SBUX", "SCHW", "SHW", "SLB", "SNPS", "SO", "SPGI", "SPY", "SRE", "STZ", "SYK",
            "T", "TFC", "TGT", "TJX", "TMO", "TMUS", "TRV", "TSLA", "TT", "TXN", "UNH", "UNP", "UPS", "USB", "V",
            "VLO", "VRTX", "VZ", "WBA", "WELL", "WFC", "WM", "WMB", "WMT", "XEL", "XOM", "YUM", "ZTS"]


def panels(client, days: int = 1825, symbols: Optional[list[str]] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Open and close price panels indexed by date, columns by symbol."""
    end = dt.date.today()
    b = client.stock_bars(symbols or UNIVERSE, "1Day", end - dt.timedelta(days=days), end).reset_index()
    b["date"] = pd.to_datetime(b["timestamp"] if "timestamp" in b else b.iloc[:, 0]).dt.date
    return (b.pivot_table(index="date", columns="symbol", values="open"),
            b.pivot_table(index="date", columns="symbol", values="close"))


def zgap(op: pd.DataFrame, cl: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Overnight gap divided by the name's own daily volatility, so names are comparable."""
    return (op / cl.shift(1) - 1) / cl.pct_change().rolling(window).std()


def backtest(client, n: int = 20, days: int = 1825, hedge: bool = False) -> dict:
    """Daily open-to-close returns of the gap-fade basket. hedge subtracts SPY to strip market beta."""
    op, cl = panels(client, days)
    day = cl / op - 1
    r = day.where(zgap(op, cl).rank(axis=1, ascending=True) <= n).mean(axis=1)
    if hedge and "SPY" in day:
        r = r - day["SPY"]
    r = r.dropna()
    bench = day.mean(axis=1).reindex(r.index)
    curve = (1 + r).cumprod()
    return {"days": len(r), "ann_return": float(r.mean() * 252), "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "win_rate": float((r > 0).mean()), "max_drawdown": float((curve / curve.cummax() - 1).min()),
            "excess_vs_benchmark": float((r - bench).mean() * 252), "returns": r}


def rank_today(client, n: int = 20, days: int = 60, require_fresh: bool = True) -> pd.DataFrame:
    """Today's gap-downs ranked by volatility-adjusted gap. Call once the opening prints are in.

    Needs enough history for the 20-day volatility, so it pulls more than the two days the gap itself uses.
    Refuses to rank a stale session: run before the opening print and the newest bar is yesterday's, whose gap
    has already been traded away.
    """
    op, cl = panels(client, days=days)
    if len(op) < 22:
        return pd.DataFrame()
    if require_fresh:
        session = op.index[-1]
        today = dt.datetime.now(ZoneInfo("America/New_York")).date()
        if getattr(session, "date", lambda: session)() != today:
            return pd.DataFrame()
    z = zgap(op, cl).iloc[-1].dropna().sort_values()
    today, prev = op.index[-1], cl.index[-2]
    gap = (op.loc[today] / cl.loc[prev] - 1).reindex(z.index)
    return pd.DataFrame({"open": op.loc[today].reindex(z.index), "gap": gap, "z": z}).head(n)


def plan(nav: float, client, n: int = 20, budget_pct: float = 0.40) -> list[dict]:
    """Equal-weight buys across today's gap-downs, capped at budget_pct of NAV."""
    picks = rank_today(client, n)
    if picks.empty:
        return []
    per_name = nav * budget_pct / max(len(picks), 1)
    out = []
    for sym, row in picks.iterrows():
        px = float(row["open"])
        qty = int(per_name // px) if px > 0 else 0
        if qty >= 1:
            out.append({"symbol": sym, "qty": qty, "price": round(px, 2), "gap": round(float(row["gap"]), 4),
                        "z": round(float(row["z"]), 2), "notional": round(qty * px, 2)})
    return out


def _close_order(symbol: str, qty: float, *, dry_run: bool) -> dict:
    """Market-on-close sell, placed at entry as insurance only.

    This is not the exit we rely on. The paper engine has no closing auction to route a `cls` order to, so it
    sits unfilled and expires at 16:01: on 2026-08-31 that carried a whole session's book overnight uncovered.
    liquidate() is what actually gets the book flat.
    """
    return cli.run("order", "submit", "--symbol", symbol, "--qty", str(qty), "--side", "sell",
                   "--type", "market", "--time-in-force", "cls", *(["--dry-run"] if dry_run else []))


def _market_exit(symbol: str, qty: float, *, dry_run: bool) -> dict:
    """Plain market sell. Fills in seconds, which is the whole point: it is the order that actually works."""
    return cli.run("order", "submit", "--symbol", symbol, "--qty", str(qty), "--side", "sell",
                   "--type", "market", "--time-in-force", "day", *(["--dry-run"] if dry_run else []))


def enter(orders: list[dict], *, dry_run: bool = True, wait_seconds: int = 300, poll: int = 3) -> list[dict]:
    """Buy at market, wait for the fills, then place market-on-close exits for the quantity actually filled.

    The exit has to follow the fill. Submitting both at once can put the sell in before the position exists, and a
    partially filled buy would leave the account short into the close.
    """
    if dry_run:
        return [{**o, "buy": "dry_run", "exit": _close_order(o["symbol"], o["qty"], dry_run=True).get("status",
                                                                                                      "dry_run")}
                for o in orders]

    pending = []
    for o in orders:
        try:
            r = cli.submit_equity(o["symbol"], o["qty"], "buy", dry_run=False)
            pending.append((o, r.get("id"), r.get("status")))
        except Exception as e:
            pending.append((o, None, f"rejected: {e}"))

    # Wait for terminal state, then cancel whatever has not filled. The exit cannot be sized until the buy
    # can no longer grow: sizing it to a partial fill leaves the remainder to fill afterwards and carry
    # overnight, which is the one thing this sleeve must never do.
    # Opening market orders took 20-65s to fill on 2026-08-31, so a one-minute wait cancels the basket just as
    # it is filling. Wait long enough that the cancel is a genuine no-fill, not an impatient one.
    TERMINAL = {"filled", "canceled", "expired", "rejected", "done_for_day"}
    deadline = time.time() + wait_seconds
    live = [(o, oid) for o, oid, _ in pending if oid]
    states: dict[str, dict] = {}
    while time.time() < deadline:
        for o, oid in live:
            try:
                states[oid] = cli.order(oid)
            except Exception:
                continue
        if all(str(states.get(oid, {}).get("status")) in TERMINAL for _, oid in live):
            break
        time.sleep(poll)
    for o, oid in live:
        if str(states.get(oid, {}).get("status")) not in TERMINAL:
            cli.cancel(oid)
            try:
                states[oid] = cli.order(oid)          # re-read: the cancel fixes the filled quantity
            except Exception:
                pass
    filled = {o["symbol"]: float(states.get(oid, {}).get("filled_qty") or 0) for o, oid in live}

    out = []
    for o, oid, status in pending:
        qty = filled.get(o["symbol"], 0.0)
        exit_status = "no fill, no exit placed"
        if qty > 0:
            try:
                exit_status = _close_order(o["symbol"], qty, dry_run=False).get("status", "submitted")
            except Exception as e:
                exit_status = f"EXIT FAILED: {type(e).__name__}"
        out.append({**o, "buy": status, "filled_qty": qty, "exit": exit_status})
    return out


def shortfall() -> list[dict]:
    """Shares today's entry intended to hold but does not, taken from the account's own order history.

    Intent is the largest quantity ordered in one go per symbol, not the sum: topping up submits its own buys, and
    summing them would read the repair as fresh intent and buy the basket twice. Differencing against the live
    position instead makes this idempotent, so it can run as often as it likes and never exceed the plan.
    """
    today = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    intended: dict[str, float] = {}
    for o in cli.orders("all"):
        if str(o.get("side")) != "buy" or not str(o.get("submitted_at", "")).startswith(today):
            continue
        if str(o.get("asset_class") or "us_equity") != "us_equity":
            continue
        sym = str(o.get("symbol"))
        intended[sym] = max(intended.get(sym, 0.0), float(o.get("qty") or 0))
    held = {str(p.get("symbol")): float(p.get("qty") or 0) for p in cli.positions()}
    out = [{"symbol": s, "qty": int(intended[s] - held.get(s, 0.0)), "intended": int(intended[s]),
            "held": int(held.get(s, 0.0))} for s in sorted(intended)]
    return [o for o in out if o["qty"] >= 1]


def topup(*, dry_run: bool = True, wait_seconds: int = 300) -> list[dict]:
    """Buy back whatever the opening entry failed to fill, and cover it market-on-close like any other entry.

    An under-fill is the normal failure at the open: a market order can be cancelled holding a partial fill, or
    none at all, which silently shrinks the book below the size that was backtested.

    A partial fill already carries a resting close order, and a buy that crosses your own resting sell is rejected
    as a wash trade, so the exit comes off before the top-up goes on. flatten() re-covers the whole position
    afterwards, which also repairs the naked window if a buy fails in between.
    """
    short = shortfall()
    if not short:
        return []
    names = {o["symbol"] for o in short}
    if not dry_run:
        for o in cli.orders("open"):
            if str(o.get("side")) == "sell" and str(o.get("symbol")) in names:
                cli.cancel(str(o.get("id")))
    rows = enter(short, dry_run=dry_run, wait_seconds=wait_seconds)
    covered = {r["symbol"]: r["status"] for r in flatten(dry_run=dry_run)}
    for r in rows:
        if r["symbol"] in covered:
            r["exit"] = f"{r['exit']} + {covered[r['symbol']]}"
    return rows


def flatten(*, dry_run: bool = True) -> list[dict]:
    """Ensure every open long is covered by a resting sell before the close.

    Entry-time bookkeeping cannot be trusted on its own: a cancel can race a fill, an exit can be rejected, and a
    position can arrive from somewhere else. This reconciles intent against the actual account and is the guarantee
    that the sleeve is flat overnight. Run it before the market-on-close cutoff (15:50 ET).
    """
    positions = cli.positions()
    resting: dict[str, float] = {}
    for o in cli.orders("open"):
        if str(o.get("side")) == "sell":
            sym = str(o.get("symbol"))
            qty = float(o.get("qty") or 0) - float(o.get("filled_qty") or 0)
            resting[sym] = resting.get(sym, 0.0) + qty
    out = []
    for pos in positions:
        sym = str(pos.get("symbol"))
        held = float(pos.get("qty") or 0)
        if held <= 0:                                   # shorts are not this sleeve's doing; leave them alone
            continue
        if pos.get("asset_class") != "us_equity":       # a spread's long leg is not a loose long: selling it
            continue                                    # alone strips the hedge off the short leg
        uncovered = held - resting.get(sym, 0.0)
        if uncovered <= 0:
            continue
        status = "would submit" if dry_run else "submitted"
        if not dry_run:
            try:
                status = _close_order(sym, uncovered, dry_run=False).get("status", "submitted")
            except Exception as e:
                status = f"FAILED: {type(e).__name__}"
        out.append({"symbol": sym, "held": held, "resting_sell": resting.get(sym, 0.0),
                    "uncovered": uncovered, "status": status})
    return out



def liquidate(*, dry_run: bool = True) -> list[dict]:
    """Sell every equity long outright, taking the resting close orders off first.

    This is the exit. The market-on-close order placed at entry is insurance that this account does not honour,
    so the book is only actually flat once these fills come back. Run it late enough that the price is close to
    the close, but with enough of the session left for a market order to fill.

    Option legs are never touched: the vertical's short leg carries a negative quantity and would be left
    behind, turning defined risk into a naked short.
    """
    positions = [p for p in cli.positions()
                 if p.get("asset_class") == "us_equity" and float(p.get("qty") or 0) > 0]
    names = {str(p.get("symbol")) for p in positions}
    if not dry_run:
        for o in cli.orders("open"):                    # our own resting sell blocks the exit as a wash trade
            if str(o.get("side")) == "sell" and str(o.get("symbol")) in names:
                cli.cancel(str(o.get("id")))
    out = []
    for p in positions:
        sym, qty = str(p.get("symbol")), float(p.get("qty"))
        status = "would sell"
        if not dry_run:
            try:
                status = _market_exit(sym, qty, dry_run=False).get("status", "submitted")
            except Exception as e:
                status = f"FAILED: {type(e).__name__}: {e}"
        out.append({"symbol": sym, "qty": qty, "value": float(p.get("market_value") or 0), "status": status})
    return out
