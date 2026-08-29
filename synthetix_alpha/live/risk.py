"""Deterministic risk gates applied after sizing, before any order reaches the broker.

Ported from the quant-agent PR's risk_guard, adapted to this repo's option-order shape:
caps are read from config/governance.yaml so limits are auditable and changeable without code.
Every rejection returns a reason string; nothing is silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from synthetix_alpha import config

GOVERNANCE = config.ROOT / "config" / "governance.yaml"


@dataclass
class Rules:
    max_leverage: float = 1.0
    max_single_position_pct: float = 0.10
    max_open_positions: int = 10
    max_daily_drawdown_pct: float = 0.05
    max_total_drawdown_pct: float = 0.20
    defined_risk_only: bool = True
    max_premium_at_risk_pct: float = 0.02

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Rules":
        raw = yaml.safe_load(Path(path or GOVERNANCE).read_text()) or {}
        g = raw.get("governance", raw)
        opts = g.get("options", {})
        return cls(**{f: v for f, v in {**g, **opts}.items() if f in cls.__dataclass_fields__})


@dataclass
class Decision:
    """Orders cleared to send, plus a reason for every one that was not."""

    approved: list[dict] = field(default_factory=list)
    halts: list[str] = field(default_factory=list)

    @property
    def halted(self) -> bool:
        return bool(self.halts)


def _notional(o: dict) -> float:
    return float(o.get("max_loss") or o.get("estimated_notional") or 0.0)


def _position_notional(positions: list[dict], symbol: Optional[str] = None) -> float:
    return sum(abs(float(p.get("qty", 0)) * float(p.get("avg_entry_price", 0)))
               for p in positions if symbol is None or p.get("symbol") == symbol)


def apply(orders: list[dict], positions: list[dict], nav: float, rules: Optional[Rules] = None,
          day_pnl: float = 0.0) -> Decision:
    """Gate `orders` against account state. Order keys: symbol, max_loss (risk $), defined_risk, underlying."""
    r = rules or Rules.load()
    d = Decision()
    if nav <= 0:
        return Decision([], ["HALT: non-positive NAV"])

    total_pl = sum(float(p.get("unrealized_pl", 0.0)) for p in positions)
    if total_pl < 0 and abs(total_pl) / nav >= r.max_total_drawdown_pct:
        return Decision([], [f"HALT ALL: total drawdown {abs(total_pl)/nav:.2%} >= {r.max_total_drawdown_pct:.2%}"])
    if day_pnl < 0 and abs(day_pnl) / nav >= r.max_daily_drawdown_pct:
        return Decision([], [f"HALT ALL: daily drawdown {abs(day_pnl)/nav:.2%} >= {r.max_daily_drawdown_pct:.2%}"])

    slots = r.max_open_positions - len(positions)
    if slots <= 0:
        return Decision([], [f"HALT ALL: {len(positions)}/{r.max_open_positions} positions open"])

    remaining_leverage = nav * r.max_leverage - _position_notional(positions)
    for o in orders:
        sym = o.get("symbol") or o.get("underlying", "?")
        risk = _notional(o)
        if r.defined_risk_only and not o.get("defined_risk", False):
            d.halts.append(f"HALT {sym}: options must be defined-risk")
            continue
        if risk > nav * r.max_premium_at_risk_pct:
            d.halts.append(f"HALT {sym}: risk ${risk:,.0f} exceeds {r.max_premium_at_risk_pct:.1%} of NAV")
            continue
        combined = _position_notional(positions, sym) + risk
        if combined > nav * r.max_single_position_pct:
            d.halts.append(f"HALT {sym}: combined ${combined:,.0f} exceeds {r.max_single_position_pct:.0%} cap")
            continue
        if risk > remaining_leverage:
            d.halts.append(f"HALT {sym}: exceeds remaining leverage ${remaining_leverage:,.0f}")
            continue
        if len(d.approved) >= slots:
            d.halts.append(f"HALT {sym}: no position slots left ({r.max_open_positions} max)")
            continue
        remaining_leverage -= risk
        d.approved.append(o)
    return d
