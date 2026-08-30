"""Forward collection of on-chain wallet activity.

The Bitquery token in use is realtime-only: `archive` returns 403 and the realtime dataset retains hours, not days.
Wallet skill therefore cannot be measured from history, so it is accumulated going forward instead. Each snapshot
records per-wallet buy/sell USD in a trailing window alongside the Alpaca price, which is what a copy would trade.

    python -m synthetix_alpha.research.wallets collect --interval 1800
    python -m synthetix_alpha.research.wallets status
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path

import pandas as pd

from synthetix_alpha.data import bitquery as bq

STORE = Path("datasets/wallets")
MINTS = {"TRUMP": "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN",
         "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
         "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"}


def _env() -> None:
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def price(symbol: str) -> float:
    """Latest Alpaca price for the pair we would copy into."""
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoLatestTradeRequest

    from synthetix_alpha import config
    k, s = config.credentials()
    pair = bq.ALPACA_PAIRS.get(symbol, f"{symbol}/USD")
    t = CryptoHistoricalDataClient(k, s).get_crypto_latest_trade(CryptoLatestTradeRequest(symbol_or_symbols=[pair]))
    return float(t[pair].price)


def snapshot(window_hours: int = 6, limit: int = 300) -> pd.DataFrame:
    """One pass over the tracked tokens."""
    now = dt.datetime.now(dt.timezone.utc)
    frames = []
    for sym, mint in MINTS.items():
        try:
            df = bq.wallet_aggregates(mint, now - dt.timedelta(hours=window_hours), now, limit=limit)
        except Exception as e:
            print(f"  {sym}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if df.empty:
            continue
        df["symbol"], df["snapshot"], df["window_hours"] = sym, now, window_hours
        try:
            df["px"] = price(sym)
        except Exception:
            df["px"] = float("nan")
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def collect(interval: int = 1800, window_hours: int = 6, rounds: int = 0) -> None:
    """Append a snapshot every `interval` seconds. rounds=0 runs until stopped."""
    _env()
    STORE.mkdir(parents=True, exist_ok=True)
    n = 0
    while rounds == 0 or n < rounds:
        df = snapshot(window_hours)
        if not df.empty:
            ts = df["snapshot"].iloc[0].strftime("%Y%m%dT%H%M%SZ")
            df.to_parquet(STORE / f"snap_{ts}.parquet", compression="zstd", index=False)
            print(f"{ts}  {len(df)} wallet rows across {df['symbol'].nunique()} tokens", flush=True)
        n += 1
        if rounds == 0 or n < rounds:
            time.sleep(interval)


def load() -> pd.DataFrame:
    files = sorted(STORE.glob("snap_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def status() -> None:
    df = load()
    if df.empty:
        print("no snapshots yet")
        return
    span = df["snapshot"].max() - df["snapshot"].min()
    print(f"{df['snapshot'].nunique()} snapshots over {span}  ({df['snapshot'].min()} -> {df['snapshot'].max()})")
    print(df.groupby("symbol").agg(rows=("wallet", "size"), wallets=("wallet", "nunique")).to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--interval", type=int, default=1800)
    c.add_argument("--window-hours", type=int, default=6)
    c.add_argument("--rounds", type=int, default=0)
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.interval, a.window_hours, a.rounds)
    else:
        _env(); status()


if __name__ == "__main__":
    main()
