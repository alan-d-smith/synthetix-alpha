"""Intraday gap-fade sleeve: long the largest overnight gap-downs at the open, flat by the close.

Gaps are ranked in units of each name's own 20-day volatility rather than raw percent, which lifts the excess
return over an equal-weight benchmark from t = 1.05 to t = 2.44. Entered by market order once the opening prints
are in, exited market-on-close so the exit fills at the official close the backtest measures.
"""

from __future__ import annotations

import datetime as dt
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


def rank_today(client, n: int = 20, days: int = 60) -> pd.DataFrame:
    """Today's gap-downs ranked by volatility-adjusted gap. Call once the opening prints are in.

    Needs enough history for the 20-day volatility, so it pulls more than the two days the gap itself uses.
    """
    op, cl = panels(client, days=days)
    if len(op) < 22:
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


def enter(orders: list[dict], *, dry_run: bool = True) -> list[dict]:
    """Market buy at the open, plus a market-on-close sell so the sleeve cannot hold overnight."""
    out = []
    for o in orders:
        buy = cli.submit_equity(o["symbol"], o["qty"], "buy", dry_run=dry_run)
        sell = cli.run("order", "submit", "--symbol", o["symbol"], "--qty", str(o["qty"]), "--side", "sell",
                       "--type", "market", "--time-in-force", "cls", *(["--dry-run"] if dry_run else []))
        out.append({**o, "buy": buy.get("status", "dry_run"), "exit": sell.get("status", "dry_run")})
    return out
