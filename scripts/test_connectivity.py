#!/usr/bin/env python
"""
test_connectivity.py — Smoke-test script for data client connectivity.

Prints one real API response for one ticker (AAPL) to confirm that
Alpaca Market Data, Alpaca Options Data, and FRED clients are working.

Usage:
    python scripts/test_connectivity.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

TEST_TICKER = "AAPL"


def _section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _subsection(title: str) -> None:
    """Print a formatted sub-section header."""
    print(f"\n--- {title} ---")


def test_market_bars() -> None:
    """Fetch 15-min bars for the test ticker and print the latest bar."""
    from data.alpaca_market_data import get_bars

    _section("1. Alpaca Market Data — 15-Minute Bars")

    try:
        bars = get_bars([TEST_TICKER], timeframe="15Min", limit=5)
        if not bars or TEST_TICKER not in bars:
            print(f"  WARNING: No bars returned for {TEST_TICKER}")
            return

        bar_list = bars[TEST_TICKER]
        print(f"  Ticker: {TEST_TICKER}")
        print(f"  Bars returned: {len(bar_list)}")
        if bar_list:
            latest = bar_list[-1]
            print(f"  Latest bar ({latest['timestamp']}):")
            print(f"    Open:   {latest['open']:.2f}")
            print(f"    High:   {latest['high']:.2f}")
            print(f"    Low:    {latest['low']:.2f}")
            print(f"    Close:  {latest['close']:.2f}")
            print(f"    Volume: {latest['volume']:,}")
            print(f"    VWAP:   {latest['vwap']:.4f}")
    except Exception as e:
        print(f"  ERROR: {e}")


def test_market_snapshot() -> None:
    """Fetch a full snapshot (trade, quote, bars) for the test ticker."""
    from data.alpaca_market_data import get_snapshots

    _section("2. Alpaca Market Data — Snapshot")

    try:
        snapshots = get_snapshots([TEST_TICKER])
        if not snapshots or TEST_TICKER not in snapshots:
            print(f"  WARNING: No snapshot returned for {TEST_TICKER}")
            return

        snap = snapshots[TEST_TICKER]

        _subsection("Latest Trade")
        t = snap.get("latest_trade", {})
        print(f"  Price: {t.get('price')}")
        print(f"  Size:  {t.get('size')}")
        print(f"  Time:  {t.get('timestamp')}")

        _subsection("Latest Quote")
        q = snap.get("latest_quote", {})
        print(f"  Bid: {q.get('bid_price')} x {q.get('bid_size')}")
        print(f"  Ask: {q.get('ask_price')} x {q.get('ask_size')}")

        _subsection("Latest Minute Bar")
        mb = snap.get("latest_minute_bar", {})
        print(f"  O: {mb.get('open')}  H: {mb.get('high')}  "
              f"L: {mb.get('low')}  C: {mb.get('close')}  V: {mb.get('volume')}")

        _subsection("Latest Daily Bar")
        db = snap.get("latest_daily_bar", {})
        print(f"  O: {db.get('open')}  H: {db.get('high')}  "
              f"L: {db.get('low')}  C: {db.get('close')}  V: {db.get('volume')}")

    except Exception as e:
        print(f"  ERROR: {e}")


def test_options_chain() -> None:
    """Fetch the nearest options chain for the test ticker (5 calls + 5 puts)."""
    from data.alpaca_options_data import get_option_chain

    _section("3. Alpaca Options Data — Chain (5 calls + 5 puts)")

    try:
        contracts = get_option_chain(TEST_TICKER, strike_count=5)
        if not contracts:
            print(f"  WARNING: No options chain returned for {TEST_TICKER}")
            print("  (This may be normal if no options for the nearest expiration)")
            return

        calls = [c for c in contracts if c.get("type") == "call"]
        puts = [c for c in contracts if c.get("type") == "put"]

        print(f"  Underlying: {TEST_TICKER}")
        print(f"  Total: {len(contracts)}  (calls: {len(calls)}, puts: {len(puts)})")

        if calls:
            exp = calls[0].get("expiration_date", "N/A")
            print(f"  Expiration: {exp}")
            _subsection("Calls (first 3)")
            for c in calls[:3]:
                print(f"    {c['symbol']}")
                print(f"      Strike: {c['strike_price']}  "
                      f"IV: {c.get('implied_volatility', 'N/A')}")
                q = c.get("latest_quote", {})
                print(f"      Bid: {q.get('bid_price')}  Ask: {q.get('ask_price')}")
                g = c.get("greeks", {})
                if g.get("delta") is not None:
                    print(f"      D: {g['delta']:.4f}  G: {g['gamma']:.4f}  "
                          f"T: {g['theta']:.4f}")

        if puts:
            _subsection("Puts (first 3)")
            for p in puts[:3]:
                print(f"    {p['symbol']}")
                print(f"      Strike: {p['strike_price']}  "
                      f"IV: {p.get('implied_volatility', 'N/A')}")
                q = p.get("latest_quote", {})
                print(f"      Bid: {q.get('bid_price')}  Ask: {q.get('ask_price')}")
                g = p.get("greeks", {})
                if g.get("delta") is not None:
                    print(f"      D: {g['delta']:.4f}  G: {g['gamma']:.4f}  "
                          f"T: {g['theta']:.4f}")

    except Exception as e:
        print(f"  ERROR: {e}")


def test_fred_macro() -> None:
    """Fetch FRED macro snapshot (VIX, yields, CPI, Fed funds)."""
    from data.fred_client import get_macro_snapshot

    _section("4. FRED Macro Snapshot")

    key_configured = bool(os.getenv("FRED_API_KEY"))
    if not key_configured:
        print("  FRED_API_KEY not set — skipping (FRED is optional)")
        print("  Free key: https://fred.stlouisfed.org/docs/api/api_key.html")
        return

    try:
        macro = get_macro_snapshot()
        print(f"  Timestamp:   {macro.get('timestamp', 'N/A')}")
        print(f"  VIX:         {macro.get('vix')}")
        print(f"  10Y Yield:   {macro.get('yield_10y')}")
        print(f"  2Y Yield:    {macro.get('yield_2y')}")
        print(f"  Yield Spread:{macro.get('yield_spread')}  (10Y - 2Y)")
        print(f"  CPI YoY:     {macro.get('cpi_yoy')}%")
        print(f"  Fed Funds:   {macro.get('fed_funds_rate')}")
    except Exception as e:
        print(f"  ERROR: {e}")


def main() -> None:
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")

    if not api_key or not api_secret:
        print("\n" + "!" * 70)
        print("  MISSING CREDENTIALS")
        print("  ALPACA_API_KEY and ALPACA_API_SECRET must be set in .env")
        print("!" * 70)
        sys.exit(1)

    print("=" * 70)
    print("  synthetix-alpha — Connectivity Smoke Test")
    print(f"  Test ticker: {TEST_TICKER}")
    print("=" * 70)

    test_market_bars()
    test_market_snapshot()
    test_options_chain()
    test_fred_macro()

    print(f"\n{'=' * 70}")
    print("  Smoke test complete.")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()