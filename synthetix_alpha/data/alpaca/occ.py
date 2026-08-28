"""OCC option symbols as used by Alpaca, e.g. SPY240816C00550000 = SPY, 2024-08-16, call, 550.0."""

import datetime as dt
from typing import NamedTuple, Union


class OccSymbol(NamedTuple):
    underlying: str
    expiration: dt.date
    option_type: str  # "call" | "put"
    strike: float

    @property
    def symbol(self) -> str:
        return build_occ_symbol(*self)


def parse_occ_symbol(symbol: str) -> OccSymbol:
    s = symbol.strip().upper()
    if len(s) < 16 or not s[-8:].isdigit() or s[-9] not in "CP" or not s[-15:-9].isdigit():
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    expiration = dt.datetime.strptime(s[-15:-9], "%y%m%d").date()
    return OccSymbol(s[:-15], expiration, "call" if s[-9] == "C" else "put", int(s[-8:]) / 1000)


def build_occ_symbol(underlying: str, expiration: Union[dt.date, str], option_type: str, strike: float) -> str:
    if isinstance(expiration, str):
        expiration = dt.date.fromisoformat(expiration)
    cp = {"c": "C", "call": "C", "p": "P", "put": "P"}[option_type.lower()]
    return f"{underlying.upper()}{expiration:%y%m%d}{cp}{round(strike * 1000):08d}"
