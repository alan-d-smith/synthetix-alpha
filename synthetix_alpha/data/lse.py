"""London Strategic Edge option chains: live implied volatility and greeks.

The only live IV source in the project. The DoltHub mirror the screen reads returns zero marks, and
OptionMetrics stops at 2025-08-29 so it can validate but never trade.

The feed cannot be trusted as returned. Measured on 2026-09-02, 61% of an AAPL chain had already expired,
and the server's own `dte` field is wrong on 1,641 of 2,323 rows: it reported `dte: 1` for a contract that
expired 62 days earlier. Because the server-side `max_dte` filter is computed from that field, asking for
`max_dte=30` still returned 1,408 expired contracts. So `dte` and `max_dte` are never used here. Expiry is
taken from the OSI ticker, cross-checked against the `expiry` column, and anything that disagrees is dropped
rather than guessed at.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Optional

OSI = re.compile(r"^(?P<root>[A-Z][A-Z0-9.]{0,9})(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
MAX_SANE_IV = 3.0          # 300%: above this the quote is stale or the contract untraded
DEFAULT_STALE_DAYS = 5


def _client(api_key: Optional[str] = None):
    from lse import LSE

    key = api_key or os.environ.get("LSE_API_KEY")
    if not key:
        raise RuntimeError("LSE_API_KEY not set (see .env.example)")
    return LSE(api_key=key)


def osi_expiry(ticker: str) -> Optional[dt.date]:
    """Expiry decoded from the OSI symbol itself, which cannot drift from the contract it names."""
    m = OSI.match(str(ticker or "").strip().upper())
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group("ymd"), "%y%m%d").date()
    except ValueError:
        return None


def _as_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_ts(value: Any) -> Optional[dt.date]:
    return _as_date(value)


def live_contracts(rows: list[dict], *, asof: Optional[dt.date] = None, min_dte: int = 0,
                   max_dte: Optional[int] = None, max_stale_days: int = DEFAULT_STALE_DAYS,
                   max_iv: float = MAX_SANE_IV, require_greeks: bool = True) -> list[dict]:
    """Keep only contracts that are genuinely tradeable, and recompute `dte` from the expiry.

    Every rejection is deliberate. A contract survives when its OSI ticker parses, the expiry encoded there
    agrees with the `expiry` column, it has not expired, it carries a usable implied volatility, and it has
    traded recently enough that the quote means something.
    """
    today = asof or dt.date.today()
    out = []
    for r in rows:
        exp = osi_expiry(r.get("ticker"))
        if exp is None:                                   # unparseable symbol: refuse to guess
            continue
        stated = _as_date(r.get("expiry"))
        if stated is not None and stated != exp:          # the two disagree: the row is not trustworthy
            continue
        dte = (exp - today).days
        if dte < max(min_dte, 0):                         # expired, or too near to be what was asked for
            continue
        if max_dte is not None and dte > max_dte:
            continue
        iv = r.get("iv")
        if iv is None or not (0 < float(iv) <= max_iv):
            continue
        if require_greeks and r.get("delta") is None:
            continue
        traded = _as_ts(r.get("last_trade_at")) or _as_ts(r.get("updated_at"))
        if traded is None or (today - traded).days > max_stale_days:
            continue
        out.append({**r, "expiry": exp.isoformat(), "dte": dte})
    return out


def monthly_expiries(start: dt.date, end: dt.date) -> list[dt.date]:
    """Standard third-Friday expiries falling in a date range."""
    out, y, m = [], start.year, start.month
    while dt.date(y, m, 1) <= end:
        first = dt.date(y, m, 1)
        third_friday = first + dt.timedelta(days=(4 - first.weekday()) % 7 + 14)
        if start <= third_friday <= end:
            out.append(third_friday)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def chain(underlying: str, kind: str = "put", *, min_dte: int = 0, max_dte: Optional[int] = None,
          max_stale_days: int = DEFAULT_STALE_DAYS, client=None, asof: Optional[dt.date] = None) -> list[dict]:
    """Tradeable contracts for one underlying, queried one expiry at a time.

    A bulk pull cannot be used. The row limit is consumed by expired contracts before it reaches a live one:
    on 2026-09-02 an unfiltered SPY request returned 5,000 rows spanning 2026-07-02 to 2026-08-18, every one
    of them dead, while asking for the 2026-10-16 expiry directly returned 171 live contracts. Requesting
    each expiry explicitly sidesteps the limit, and the server's dte filter is never used because it is
    computed from a field that is wrong more often than it is right.
    """
    c = client or _client()
    today = asof or dt.date.today()
    lo = today + dt.timedelta(days=max(min_dte, 0))
    hi = today + dt.timedelta(days=max_dte if max_dte is not None else 365)
    rows: list[dict] = []
    for exp in monthly_expiries(lo, hi):
        try:
            rows += c.options(underlying, type=kind, expiry=exp.isoformat(), limit=5000)
        except Exception:
            continue                                   # one bad expiry must not lose the whole chain
    if not rows:                                       # fall back for names without monthly expiries
        try:
            rows = c.options(underlying, type=kind, limit=5000)
        except Exception:
            return []
    return live_contracts(rows, asof=today, min_dte=min_dte, max_dte=max_dte,
                          max_stale_days=max_stale_days)
