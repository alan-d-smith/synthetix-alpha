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
ENTRY, FLATTEN = dt.time(9, 31), dt.time(15, 45)

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
    if action == "flatten":
        cmd += ["--flatten"]
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


def due(now: dt.datetime) -> list[tuple[str, str, int]]:
    """Actions whose time has arrived today and which have not already run."""
    today, s, out = now.date().isoformat(), _state(), []
    for label, account, basket in BOOKS:
        for action, at in (("enter", ENTRY), ("flatten", FLATTEN)):
            key = f"{today}:{action}:{account}"
            if key in s:
                continue
            gate = window.can_enter if action == "enter" else window.can_flatten
            if now.time() >= at and gate(now)[0]:
                out.append((action, account, basket))
    return out


def loop(execute: bool, poll: int = 20) -> None:
    print(f"scheduler up. execute={execute}. {window.describe()}")
    print(f"books: " + ", ".join(f"{l} ({a})" for l, a, _ in BOOKS))
    print(f"entry {ENTRY:%H:%M} ET, flatten {FLATTEN:%H:%M} ET, state in {STATE}\n", flush=True)
    while True:
        now = window.now()
        if now > window.CLOSES:
            print(f"{now:%Y-%m-%d %H:%M} ET past the measurement close, scheduler exiting", flush=True)
            return
        for action, account, basket in due(now):
            key = f"{now.date().isoformat()}:{action}:{account}"
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
