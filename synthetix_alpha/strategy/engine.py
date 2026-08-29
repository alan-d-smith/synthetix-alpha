"""Deterministic daily backtester for a Spec over EngineData. Marks at mid, fills at mid +/- slippage, settles at intrinsic."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from synthetix_alpha.strategy.data import EngineData
from synthetix_alpha.strategy.spec import Spec

MULT = 100


@dataclass
class OpenLeg:
    symbol: str
    type: str
    side: int  # +1 long, -1 short
    ratio: int
    strike: float
    expiration: Optional[dt.date]
    mark: float


@dataclass
class Position:
    legs: list[OpenLeg]
    contracts: int
    entry_date: dt.date
    entry_value: float  # net fill per share (+ debit paid, - credit received)
    expiration: dt.date
    costs: float = 0.0

    def value(self) -> float:
        return sum(l.side * l.ratio * l.mark for l in self.legs)


@dataclass
class Result:
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def _intrinsic(leg: OpenLeg, spot: float) -> float:
    if leg.type == "stock":
        return spot
    return max(spot - leg.strike, 0.0) if leg.type == "call" else max(leg.strike - spot, 0.0)


def _fill(leg: OpenLeg, chain: pd.DataFrame, spot: float, direction: int, slip: float) -> float:
    """Execution price for buying (direction=+1) or selling (-1) one unit of the leg."""
    if leg.type == "stock":
        return spot
    row = chain.loc[leg.symbol]
    price = float(row["mid"] + direction * slip * (row["ask"] - row["bid"]) / 2)
    return price if price == price else leg.mark


def _mark(pos: Position, chain: Optional[pd.DataFrame], spot: float, date: dt.date) -> None:
    for leg in pos.legs:
        if leg.type == "stock":
            leg.mark = spot
        elif leg.expiration and date >= leg.expiration:
            leg.mark = _intrinsic(leg, spot)
        elif chain is not None and leg.symbol in chain.index:
            mid = float(chain.at[leg.symbol, "mid"])
            if mid == mid:  # keep the last good mark if the contract is unquoted today
                leg.mark = mid


def _pick_expiration(chain: pd.DataFrame, spec: Spec, offset: int) -> Optional[object]:
    c = chain[chain["dte"].between(spec.dte_min + offset, spec.dte_max + offset)]
    if c.empty:
        return None
    return c.iloc[(c["dte"] - (spec.dte_target + offset)).abs().argmin()]["expiration"]


def select(spec: Spec, chain: pd.DataFrame, spot: float) -> Optional[list[OpenLeg]]:
    legs, prev_strike = [], None
    for leg in spec.legs:
        side = 1 if leg.side == "long" else -1
        if leg.type == "stock":
            legs.append(OpenLeg("STOCK", "stock", side, leg.ratio, 0.0, None, spot))
            continue
        exp = _pick_expiration(chain, spec, leg.dte_offset)
        if exp is None:
            return None
        e = chain[(chain["expiration"] == exp) & (chain["type"] == leg.type) & (chain["bid"] >= spec.min_bid)
                  & chain["mid"].notna() & chain["delta"].notna()]
        if spec.min_volume and "volume" in e.columns:
            liquid = e[e["volume"].fillna(spec.min_volume) >= spec.min_volume]
            e = liquid if not liquid.empty else e.iloc[0:0]
        if e.empty:
            return None
        if leg.delta is not None:
            row = e.iloc[(e["delta"].abs() - leg.delta).abs().argmin()]
        else:
            target = spot * (1 + leg.moneyness) if leg.moneyness is not None else prev_strike + leg.width
            row = e.iloc[(e["strike"] - target).abs().argmin()]
            if leg.width is not None and row["strike"] == prev_strike:
                return None
        prev_strike = float(row["strike"])
        legs.append(OpenLeg(row.name, leg.type, side, leg.ratio, prev_strike, exp, float(row["mid"])))
    return legs


def max_loss(legs: list[OpenLeg], entry_value: float, spot: float) -> float:
    """Worst P&L per share at expiry across a strike grid (finite for every structure; huge for naked calls)."""
    grid = [0.0, *(l.strike for l in legs if l.type != "stock"), spot * 5]
    pnl = [sum(l.side * l.ratio * _intrinsic(l, s) for l in legs) - entry_value for s in grid]
    return max(0.0, -min(pnl))


def size(spec: Spec, legs: list[OpenLeg], entry_value: float, spot: float, equity: float) -> int:
    if spec.sizing == "notional":
        risk = spot * MULT
    elif spec.sizing == "margin":
        risk = sum(0.2 * spot * MULT * l.ratio for l in legs if l.side < 0 and l.type != "stock") or spot * MULT
    else:
        risk = max_loss(legs, entry_value, spot) * MULT
    if risk <= 0:
        return 0
    return int(min(spec.max_contracts, math.floor(equity * spec.risk_fraction / risk)))


def _in_range(f: pd.Series, signal: dict) -> bool:
    for name, (lo, hi) in signal.items():
        v = f.get(name)
        if v is None or np.isnan(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
            return False
    return True


def run(spec: Spec, data: EngineData, equity0: float = 100_000.0) -> Result:
    cash, positions, trades, curve, last_entry = equity0, [], [], {}, None
    for date in data.dates:
        chain, spot = data.chain(date), float(data.features.at[date, "spot"])
        for pos in list(positions):
            _mark(pos, chain, spot, date)
            pnl = (pos.value() - pos.entry_value) * MULT * pos.contracts
            premium = abs(pos.entry_value) * MULT * pos.contracts
            reason = None
            if date >= pos.expiration:
                reason = "expiry"
            elif spec.profit_target is not None and pnl >= spec.profit_target * premium:
                reason = "profit"
            elif spec.stop_loss is not None and pnl <= -spec.stop_loss * premium:
                reason = "stop"
            elif spec.dte_exit is not None and (pos.expiration - date).days <= spec.dte_exit:
                reason = "dte"
            elif spec.max_hold_days is not None and (date - pos.entry_date).days >= spec.max_hold_days:
                reason = "hold"
            if reason:
                cash += _close(pos, chain, spot, date, reason, spec, trades)
                positions.remove(pos)
        entry_ok = (last_entry is None or (date - last_entry).days >= spec.entry_every_days) and len(positions) < spec.max_positions
        if entry_ok and chain is not None and _in_range(data.features.loc[date], spec.signal):
            legs = select(spec, chain, spot)
            if legs:
                fill = sum(l.side * l.ratio * _fill(l, chain, spot, l.side, spec.slippage) for l in legs)
                equity = cash + sum(p.value() * MULT * p.contracts for p in positions)
                n = size(spec, legs, fill, spot, equity)
                if spec.min_credit is not None and fill < 0 and -fill < spec.min_credit * max_loss(legs, fill, spot):
                    n = 0
                cost = spec.commission * sum(l.ratio for l in legs if l.type != "stock") * n
                if n >= 1 and fill * MULT * n + cost <= cash:
                    cash -= fill * MULT * n + cost
                    exp = min(l.expiration for l in legs if l.expiration)
                    positions.append(Position(legs, n, date, fill, exp, cost))
                    last_entry = date
        curve[date] = cash + sum(p.value() * MULT * p.contracts for p in positions)
    for pos in positions:  # liquidate at the end so the curve is comparable across specs
        cash += _close(pos, data.chain(data.dates[-1]), float(data.features.at[data.dates[-1], "spot"]), data.dates[-1], "end", spec, trades)
    equity = pd.Series(curve, name="equity")
    if len(equity):
        equity.iloc[-1] = cash
    trades = pd.DataFrame(trades)
    return Result(equity, trades, metrics(equity, trades, equity0))


def _close(pos: Position, chain, spot: float, date: dt.date, reason: str, spec: Spec, trades: list) -> float:
    proceeds = 0.0
    for l in pos.legs:
        if l.type == "stock" or (l.expiration and date >= l.expiration) or chain is None or l.symbol not in chain.index:
            price = l.mark
        else:
            price = _fill(l, chain, spot, -l.side, spec.slippage)
        proceeds += l.side * l.ratio * price
    cost = spec.commission * sum(l.ratio for l in pos.legs if l.type != "stock") * pos.contracts
    pnl = (proceeds - pos.entry_value) * MULT * pos.contracts - cost - pos.costs
    trades.append({"entry": pos.entry_date, "exit": date, "days": (date - pos.entry_date).days, "contracts": pos.contracts,
                   "entry_value": pos.entry_value, "exit_value": proceeds, "pnl": pnl, "reason": reason,
                   "legs": " ".join(f"{'+' if l.side > 0 else '-'}{l.ratio}{l.symbol}" for l in pos.legs)})
    return proceeds * MULT * pos.contracts - cost


def metrics(equity: pd.Series, trades: pd.DataFrame, equity0: float) -> dict:
    if equity.empty:
        return {}
    ret = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days, 1) / 365.25
    total = equity.iloc[-1] / equity0 - 1
    dd = equity / equity.cummax() - 1
    down = ret[ret < 0].std()
    cagr = (1 + total) ** (1 / years) - 1
    pnl = trades["pnl"] if len(trades) else pd.Series(dtype=float)
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    yearly = equity.groupby(pd.to_datetime(equity.index).year).agg(["first", "last"])
    return {
        "total_return": float(total), "cagr": float(cagr),
        "sharpe": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0,
        "sortino": float(ret.mean() / down * np.sqrt(252)) if down and down > 0 else 0.0,
        "max_drawdown": float(dd.min()), "calmar": float(cagr / -dd.min()) if dd.min() < 0 else 0.0,
        "n_trades": int(len(trades)), "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "avg_pnl": float(pnl.mean()) if len(pnl) else 0.0, "profit_factor": float(wins / losses) if losses > 0 else float("inf") if wins > 0 else 0.0,
        "avg_days": float(trades["days"].mean()) if len(trades) else 0.0,
        "yearly": {int(y): float(r["last"] / r["first"] - 1) for y, r in yearly.iterrows()},
        "exit_reasons": trades["reason"].value_counts().to_dict() if len(trades) else {},
    }
