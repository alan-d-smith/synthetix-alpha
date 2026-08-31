"""Competition trading window. Nothing may reach the wire outside it.

The organisers snapshot total account equity at 09:30 ET on Friday 4 September. That is before Friday's open, so
Thursday's close is the last print that can move the number and Monday-Thursday are the four sessions that count.
The guard runs to the snapshot rather than to Thursday's close, so the final overnight stays supervised; the
entry and flatten sub-windows below are what actually keep Friday untradeable.

Trading opens Monday 31 August; 09:31 rather than 09:30 leaves a minute of margin against clock skew and a late
opening print.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPENS = dt.datetime(2026, 8, 31, 9, 31, tzinfo=ET)
CLOSES = dt.datetime(2026, 9, 4, 9, 30, tzinfo=ET)       # the equity snapshot; nothing after this counts
LAST_CLOSE = dt.datetime(2026, 9, 3, 16, 0, tzinfo=ET)   # last print that can move it, so the last chance to be flat
ENTRY_UNTIL = dt.time(10, 30)                            # gap fade is an opening trade, never a late one
FLATTEN_FROM, FLATTEN_UNTIL = dt.time(15, 30), dt.time(15, 55)   # market-on-close cutoff is 15:50


def now() -> dt.datetime:
    return dt.datetime.now(ET)


def _within(t: dt.datetime) -> tuple[bool, str]:
    if t < OPENS:
        return False, f"before the window opens ({OPENS:%a %d %b %H:%M} ET, in {OPENS - t})"
    if t > CLOSES:
        return False, f"after the measurement close ({CLOSES:%a %d %b %H:%M} ET)"
    if t.weekday() >= 5:
        return False, "weekend"
    return True, "inside the competition window"


def can_enter(t: dt.datetime | None = None) -> tuple[bool, str]:
    """Opening entries only, so a late or mistimed run cannot put the book on at the wrong price.

    Friday is unreachable by construction: the snapshot lands at 09:30 and entries start at 09:31.
    """
    t = t or now()
    ok, why = _within(t)
    if not ok:
        return False, why
    if not (OPENS.timetz() <= t.timetz() <= ENTRY_UNTIL.replace(tzinfo=ET)):
        return False, f"outside the entry window 09:31-{ENTRY_UNTIL:%H:%M} ET (now {t:%H:%M})"
    return True, "entry allowed"


def can_flatten(t: dt.datetime | None = None) -> tuple[bool, str]:
    """Closing out is allowed later in the day, and on the final session too."""
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
