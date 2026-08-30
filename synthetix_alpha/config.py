import os
import shutil
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)

PAPER = os.environ.get("ALPACA_LIVE_TRADE", "").strip().lower() not in ("1", "true", "yes")  # same switch as the Alpaca CLI
OPTIONS_FEED = os.environ.get("ALPACA_OPTIONS_FEED", "indicative")  # "opra" needs a subscription

ROOT = Path(__file__).resolve().parents[1]
DOLT_BIN = os.environ.get("DOLT_BIN") or shutil.which("dolt") or "C:/Program Files/Dolt/bin/dolt.exe"
DOLT_OPTIONS_DB = Path(os.environ.get("DOLT_OPTIONS_DB", ROOT / "datasets" / "options"))  # dolt clone post-no-preference/options
DOLT_CACHE = ROOT / "datasets" / "cache" / "dolt"
# alpacahq/cli: the hackathon requires the CLI or MCP server, not the SDK, in the order path
def _alpaca_bin() -> str:
    if os.environ.get("ALPACA_BIN"):
        return os.environ["ALPACA_BIN"]
    found = shutil.which("alpaca")
    if found:
        return found
    for name in ("alpaca.exe", "alpaca"):        # vendored next to the repo, Windows or Linux
        candidate = ROOT / "tools" / name
        if candidate.exists():
            return str(candidate)
    return "alpaca"


ALPACA_BIN = _alpaca_bin()


ACCOUNTS = {"research": ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_SECRET_KEY"),
            "deployed": ("ALPACA_DEPLOYED_API_KEY", "ALPACA_DEPLOYED_API_SECRET", None)}


def credentials(account: str = "research") -> tuple[str, str]:
    """Keys for one account. Two are kept apart so a research script cannot reach the judged account."""
    if account not in ACCOUNTS:
        raise ValueError(f"unknown account {account!r}, expected one of {sorted(ACCOUNTS)}")
    key_var, secret_var, alt = ACCOUNTS[account]
    key = os.environ.get(key_var)
    secret = os.environ.get(secret_var) or (os.environ.get(alt) if alt else None)
    if not key or not secret:
        raise RuntimeError(f"{key_var} / {secret_var} not set for the {account!r} account (see .env.example)")
    return key, secret
