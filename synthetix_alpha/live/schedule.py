"""Competition scheduler: fires the runner at fixed times inside the window, once each.

Two books run side by side, a ten-name gap fade basket on the research account and a twenty-name basket on the
deployed one, so the concentrated and diversified versions are compared on live fills rather than in a backtest.

Every action is recorded in a state file before it runs, so a crash and restart cannot enter twice. The window
guard in `live.window` is the real safety net; this only decides when to call the runner.

    python -m synthetix_alpha.live.schedule --dry-run     # rehearse, submits nothing
    python -m synthetix_alpha.live.schedule --execute     # live
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

from synthetix_alpha.live import window

STATE = Path("datasets/schedule_state.json")
# Topping up a few minutes after entry repairs an under-filled open, which is the normal failure there:
# a market order can be cancelled holding a partial fill, silently shrinking the book below its plan.
ENTRY, TOPUP = dt.time(9, 31), dt.time(9, 45)
# Two passes. The exit is a plain market order rather than market-on-close, so the 15:50 cutoff no longer binds
# and these sit as late as is safe: closer to the close the backtest measures, with enough session left to fill.
# The second pass sells whatever the first missed, and is a no-op once the book is flat.
FLATTEN = (dt.time(15, 50), dt.time(15, 56))

# (label, account, gap fade basket). The options and crypto sleeves ride along with each entry run.
BOOKS = [("research n=10", "research", 10), ("deployed n=20", "deployed", 20)]


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _mark(key: str, value: dict) -> None:
    s = _state()
    s[key] = value
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1, sort_keys=True))


def run_action(action: str, account: str, basket: int, execute: bool) -> dict:
    """Invoke the runner as a subprocess so each account gets a clean process and its own credentials."""
    cmd = [sys.executable, "-m", "synthetix_alpha.live.run", "--account", account]
    if action in ("flatten", "topup"):
        cmd += [f"--{action}"]
    else:
        cmd += ["--limit", "12", "--intraday-top", str(basket), "--intraday-budget", "0.60",
                "--crypto-budget", "0.15"]
    if execute:
        cmd += ["--execute"]
    started = dt.datetime.now(window.ET)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    out = (p.stdout or "") + (p.stderr or "")
    print(f"\n=== {started:%Y-%m-%d %H:%M:%S} ET | {action} | {account} | basket {basket} | rc {p.returncode} ===")
    print(out.strip()[-4000:])
    return {"at": started.isoformat(), "rc": p.returncode, "cmd": " ".join(cmd[2:]),
            "tail": out.strip()[-2000:]}


def due(now: dt.datetime) -> list[tuple[str, str, int, str]]:
    """Actions whose time has arrived today and which have not already run."""
    today, s, out = now.date().isoformat(), _state(), []
    for label, account, basket in BOOKS:
        timetable = [("enter", ENTRY, "enter"), ("topup", TOPUP, "topup")]
        timetable += [("flatten", at, f"flatten{i}") for i, at in enumerate(FLATTEN)]
        for action, at, name in timetable:
            key = f"{today}:{name}:{account}"
            if key in s:
                continue
            gate = window.can_flatten if action == "flatten" else window.can_enter
            if now.time() >= at and gate(now)[0]:
                out.append((action, account, basket, name))
    return out


def loop(execute: bool, poll: int = 20) -> None:
    print(f"scheduler up. execute={execute}. {window.describe()}")
    print(f"books: " + ", ".join(f"{l} ({a})" for l, a, _ in BOOKS))
    print(f"entry {ENTRY:%H:%M}, topup {TOPUP:%H:%M}, flatten "
          f"{' and '.join(format(t, '%H:%M') for t in FLATTEN)} ET, state in {STATE}", flush=True)
    print(f"last session {window.LAST_CLOSE:%a %d %b}, equity snapshot "
          f"{window.CLOSES:%a %d %b %H:%M} ET")
    print(flush=True)
    # No self-imposed stop: the organisers take their own snapshot, and a scheduler that decides on its own
    # when the competition is over is one more thing that can decide wrongly. window.can_enter / can_flatten
    # already refuse everything outside the window, so idling past it is inert. Stop it by hand when done.
    while True:
        now = window.now()
        for action, account, basket, name in due(now):
            key = f"{now.date().isoformat()}:{name}:{account}"
            _mark(key, {"started": now.isoformat(), "state": "running"})   # mark first: a crash must not retry
            try:
                _mark(key, run_action(action, account, basket, execute))
            except Exception as e:
                _mark(key, {"at": now.isoformat(), "error": f"{type(e).__name__}: {e}"})
                print(f"  {action}/{account} failed: {type(e).__name__}: {e}", flush=True)
            sys.stdout.flush()
        time.sleep(poll)


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--poll", type=int, default=20)
    a = ap.parse_args()
    loop(a.execute, a.poll)


if __name__ == "__main__":
    main()
