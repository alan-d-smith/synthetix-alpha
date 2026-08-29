"""Declarative options strategy spec. The engine interprets it; research agents mutate it. No code in the loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Union

LEG_TYPES = ("call", "put", "stock")
SIDES = ("long", "short")
FEATURES = ("iv_rank", "atm_iv", "rv20", "iv_rv_ratio", "mom20", "sma50_ratio", "sma200_ratio", "skew25",
            "term_slope", "rsi", "bollinger_pos", "macd", "vix", "vix_rank", "vix_rv_ratio", "rvol", "vwap_dev", "vix_term", "nfci", "days_to_earnings")
SIZING = ("max_loss", "margin", "notional")


@dataclass
class Leg:
    type: str  # call | put | stock
    side: str  # long | short
    delta: Optional[float] = None  # target |delta| (options)
    moneyness: Optional[float] = None  # strike / spot - 1
    width: Optional[float] = None  # $ strike offset from the previous leg (+ above, - below)
    dte_offset: int = 0  # shift this leg's expiration target (calendars/diagonals)
    ratio: int = 1


@dataclass
class Spec:
    name: str
    legs: list[Leg]
    underlyings: list[str] = field(default_factory=lambda: ["SPY"])
    dte_target: int = 45
    dte_min: int = 30
    dte_max: int = 60
    entry_every_days: int = 7
    max_positions: int = 4
    signal: dict[str, list] = field(default_factory=dict)  # feature -> [min, max]; null = unbounded
    profit_target: Optional[float] = 0.5  # close when pnl >= x * |premium|
    stop_loss: Optional[float] = 2.0  # close when pnl <= -x * |premium|
    dte_exit: Optional[int] = 21
    max_hold_days: Optional[int] = None
    risk_fraction: float = 0.02  # of equity, per position
    sizing: str = "max_loss"  # max_loss | margin (20% spot notional per short leg) | notional (spot * 100)
    max_contracts: int = 100
    commission: float = 0.65  # per contract per leg, each way
    slippage: float = 0.5  # fraction of the half-spread paid on each leg fill
    min_bid: float = 0.05
    min_volume: float = 0.0  # contracts traded that day; ignored where the source has no volume
    source: Optional[str] = None  # provenance, e.g. an arXiv id and title
    min_credit: Optional[float] = None  # credit structures only: skip entries where credit / max_loss < this

    def __post_init__(self):
        self.legs = [Leg(**l) if isinstance(l, dict) else l for l in self.legs]
        self.validate()

    def validate(self) -> None:
        if not self.legs or not any(l.type != "stock" for l in self.legs):
            raise ValueError("spec needs at least one option leg")
        for i, l in enumerate(self.legs):
            if l.type not in LEG_TYPES or l.side not in SIDES or l.ratio < 1:
                raise ValueError(f"bad leg {l}")
            if l.type != "stock" and sum(x is not None for x in (l.delta, l.moneyness, l.width)) != 1:
                raise ValueError(f"leg {i}: set exactly one of delta / moneyness / width")
            if l.width is not None and i == 0:
                raise ValueError("first leg cannot use width")
        if not 0 < self.dte_min <= self.dte_target <= self.dte_max:
            raise ValueError("need 0 < dte_min <= dte_target <= dte_max")
        unknown = set(self.signal) - set(FEATURES)
        if unknown:
            raise ValueError(f"unknown signal features {sorted(unknown)}; known: {FEATURES}")
        if self.sizing not in SIZING or not 0 < self.risk_fraction <= 1:
            raise ValueError("bad sizing / risk_fraction")
        if self.min_credit is not None and not 0 < self.min_credit < 1:
            raise ValueError("min_credit must be in (0, 1)")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Spec":
        return cls(**d)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Spec":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))
