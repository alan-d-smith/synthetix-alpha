import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)

DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")
TRADING_URL = os.environ.get("ALPACA_TRADING_URL", "https://paper-api.alpaca.markets")
OPTIONS_FEED = os.environ.get("ALPACA_OPTIONS_FEED", "indicative")  # "opra" needs a subscription


def credentials() -> tuple[str, str]:
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET") or os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET not set (see .env.example)")
    return key, secret
