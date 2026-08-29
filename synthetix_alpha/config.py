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


def credentials() -> tuple[str, str]:
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET") or os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set (see .env.example)")
    return key, secret
