"""Intraday gap-fade sleeve: long the largest overnight gap-downs at the open, flat by the close.

Ranked on the opening print, entered by market order, exited market-on-close so the exit fills at the official
close the backtest measures. Trades every session, which the slower options sleeves do not.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd

from synthetix_alpha.live import cli

# The universe the effect was measured on; changing it invalidates the backtested numbers.
UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "JPM", "V",
            "MA", "UNH", "XOM", "CVX", "JNJ", "PG", "HD", "COST", "WMT", "BAC", "NFLX", "CRM", "ORCL", "ADBE",
            "INTC", "MU", "QCOM", "TXN", "CSCO", "PFE", "MRK", "ABBV", "T", "VZ", "DIS", "NKE", "BA", "CAT", "GE",
            "MCD", "LOW", "SBUX", "GS", "MS", "BLK", "C"]


def panels(client, days: int = 1825, symbols: Optional[list[str]] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Open and close price panels indexed by date, columns by symbol."""
    end = dt.date.today()
    b = client.stock_bars(symbols or UNIVERSE, "1Day", end - dt.timedelta(days=days), end).reset_index()
    b["date"] = pd.to_datetime(b["timestamp"] if "timestamp" in b else b.iloc[:, 0]).dt.date
    return (b.pivot_table(index="date", columns="symbol", values="open"),
            b.pivot_table(index="date", columns="symbol", values="close"))


def backtest(client, n: int = 10, days: int = 1825, hedge: bool = False) -> dict:
    """Daily open-to-close returns of the gap-fade basket. hedge subtracts SPY to strip market beta."""
    op, cl = panels(client, days)
    gap, day = op / cl.shift(1) - 1, cl / op - 1
    r = day.where(gap.rank(axis=1, ascending=True) <= n).mean(axis=1)
    if hedge and "SPY" in day:
        r = r - day["SPY"]
    r = r.dropna()
    bench = day.mean(axis=1).reindex(r.index)
    curve = (1 + r).cumprod()
    return {"days": len(r), "ann_return": float(r.mean() * 252), "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "win_rate": float((r > 0).mean()), "max_drawdown": float((curve / curve.cummax() - 1).min()),
            "excess_vs_benchmark": float((r - bench).mean() * 252), "returns": r}


def rank_today(client, n: int = 10) -> pd.DataFrame:
    """Today's gap-downs, ranked. Call once the opening prints are in."""
    op, cl = panels(client, days=10)
    if len(op) < 2:
        return pd.DataFrame()
    today, prev = op.index[-1], cl.index[-2]
    gap = (op.loc[today] / cl.loc[prev] - 1).dropna().sort_values()
    return pd.DataFrame({"open": op.loc[today].reindex(gap.index), "gap": gap}).head(n)


def plan(nav: float, client, n: int = 10, budget_pct: float = 0.40) -> list[dict]:
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
                        "notional": round(qty * px, 2)})
    return out


def enter(orders: list[dict], *, dry_run: bool = True) -> list[dict]:
    """Market buy at the open, plus a market-on-close sell so the sleeve cannot hold overnight."""
    out = []
    for o in orders:
        buy = cli.submit_equity(o["symbol"], o["qty"], "buy", dry_run=dry_run)
        sell = cli.run("order", "submit", "--symbol", o["symbol"], "--qty", str(o["qty"]), "--side", "sell",
                       "--type", "market", "--time-in-force", "cls", *(["--dry-run"] if dry_run else []))
        out.append({**o, "buy": buy.get("status", "dry_run"), "exit": sell.get("status", "dry_run")})
    return out
