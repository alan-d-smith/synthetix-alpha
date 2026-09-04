"""Daily trading windows. Nothing may reach the wire outside them.

Entries are opening trades: 09:31 rather than 09:30 leaves a minute of margin against clock skew and a late
opening print, and nothing goes on after 10:30. Flattening runs late in the session, with enough left for a
market order to fill. Weekends are refused; a market holiday is inert because the ranking refuses a stale session.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ENTRY_FROM, ENTRY_UNTIL = dt.time(9, 31), dt.time(10, 30)        # gap fade is an opening trade, never a late one
FLATTEN_FROM, FLATTEN_UNTIL = dt.time(15, 30), dt.time(15, 58)   # a market order still fills this late


def now() -> dt.datetime:
    return dt.datetime.now(ET)


def _within(t: dt.datetime) -> tuple[bool, str]:
    if t.weekday() >= 5:
        return False, "weekend"
    return True, "trading day"


def can_enter(t: dt.datetime | None = None) -> tuple[bool, str]:
    """Opening entries only, so a late or mistimed run cannot put the book on at the wrong price."""
    t = t or now()
    ok, why = _within(t)
    if not ok:
        return False, why
    if not (ENTRY_FROM <= t.time() <= ENTRY_UNTIL):
        return False, f"outside the entry window {ENTRY_FROM:%H:%M}-{ENTRY_UNTIL:%H:%M} ET (now {t:%H:%M})"
    return True, "entry allowed"


def can_flatten(t: dt.datetime | None = None) -> tuple[bool, str]:
    """Closing out is allowed later in the day."""
    t = t or now()
    ok, why = _within(t)
    if not ok:
        return False, why
    if not (FLATTEN_FROM <= t.time() <= FLATTEN_UNTIL):
        return False, f"outside the flatten window {FLATTEN_FROM:%H:%M}-{FLATTEN_UNTIL:%H:%M} ET (now {t:%H:%M})"
    return True, "flatten allowed"


def describe(t: dt.datetime | None = None) -> str:
    t = t or now()
    e, why_e = can_enter(t)
    f, why_f = can_flatten(t)
    return (f"{t:%a %d %b %H:%M} ET | enter: {'YES' if e else 'no'} ({why_e}) | "
            f"flatten: {'YES' if f else 'no'} ({why_f})")
