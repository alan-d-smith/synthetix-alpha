"""Bitquery GraphQL client for on-chain DEX trades.

v2 OAuth token (BITQUERY_TOKEN) against streaming.bitquery.io. Used to find wallets whose past trading predicts
forward returns in tokens Alpaca can actually trade.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from typing import Optional

import httpx
import pandas as pd

ENDPOINT = "https://streaming.bitquery.io/graphql"
EAP = "https://streaming.bitquery.io/eap"

# On-chain symbol -> Alpaca pair. Only tokens Alpaca lists are worth copying.
ALPACA_PAIRS = {"TRUMP": "TRUMP/USD", "WIF": "WIF/USD", "BONK": "BONK/USD", "SOL": "SOL/USD", "WSOL": "SOL/USD",
                "PEPE": "PEPE/USD", "SHIB": "SHIB/USD", "ONDO": "ONDO/USD", "RENDER": "RENDER/USD",
                "LDO": "LDO/USD", "ARB": "ARB/USD", "LINK": "LINK/USD", "UNI": "UNI/USD", "AAVE": "AAVE/USD",
                "GRT": "GRT/USD", "CRV": "CRV/USD", "AVAX": "AVAX/USD", "DOGE": "DOGE/USD", "XRP": "XRP/USD"}


def token() -> str:
    tok = os.environ.get("BITQUERY_TOKEN")
    if not tok:
        raise RuntimeError("BITQUERY_TOKEN not set (see .env.example)")
    return tok


def query(gql: str, variables: Optional[dict] = None, url: str = ENDPOINT, timeout: int = 90,
          retries: int = 5, pause: float = 7.0) -> dict:
    """Run a GraphQL query. Backs off on 429, which the free tier returns readily."""
    delay = pause
    for attempt in range(retries):
        r = httpx.post(url, json={"query": gql, "variables": variables or {}},
                       headers={"Authorization": f"Bearer {token()}"}, timeout=timeout)
        if r.status_code == 429:
            time.sleep(delay)
            delay *= 1.6
            continue
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"bitquery: {body['errors']}")
        return body.get("data") or {}
    raise RuntimeError(f"bitquery: rate limited after {retries} attempts")


def iso(d) -> str:
    if isinstance(d, str):
        return d
    if isinstance(d, dt.datetime):
        return d.replace(microsecond=0).isoformat() + ("Z" if d.tzinfo is None else "")
    return dt.datetime.combine(d, dt.time()).isoformat() + "Z"


TRADES = """
query($mint: String!, $since: DateTime!, $till: DateTime!, $limit: Int!) {
  Solana {
    DEXTradeByTokens(
      where: {Trade: {Currency: {MintAddress: {is: $mint}}},
              Block: {Time: {since: $since, till: $till}}}
      orderBy: {descending: Block_Time}
      limit: {count: $limit}
    ) {
      Block { Time }
      Trade {
        Side { Type Account { Address } }
        Account { Address }
        Amount
        AmountInUSD
        PriceInUSD
        Currency { Symbol MintAddress }
      }
    }
  }
}
"""


def token_trades(mint: str, since, till, limit: int = 25000, url: str = EAP) -> pd.DataFrame:
    """Every DEX trade in one token over a window, one row per fill."""
    data = query(TRADES, {"mint": mint, "since": iso(since), "till": iso(till), "limit": limit}, url=url)
    rows = (data.get("Solana") or {}).get("DEXTradeByTokens") or []
    if not rows:
        return pd.DataFrame(columns=["time", "wallet", "side", "amount", "usd", "price", "symbol"])
    out = []
    for r in rows:
        t = r.get("Trade") or {}
        side = (t.get("Side") or {})
        out.append({"time": r.get("Block", {}).get("Time"),
                    "wallet": (t.get("Account") or {}).get("Address"),
                    "side": (side.get("Type") or "").lower(),
                    "amount": float(t.get("Amount") or 0),
                    "usd": float(t.get("AmountInUSD") or 0),
                    "price": float(t.get("PriceInUSD") or 0),
                    "symbol": (t.get("Currency") or {}).get("Symbol")})
    df = pd.DataFrame(out)
    df["time"] = pd.to_datetime(df["time"], format="mixed", utc=True)
    return df.sort_values("time").reset_index(drop=True)


WALLET_AGG = """
query($mint: String!, $since: DateTime!, $till: DateTime!, $limit: Int!) {
  Solana {
    DEXTradeByTokens(
      where: {Trade: {Currency: {MintAddress: {is: $mint}}}, Block: {Time: {since: $since, till: $till}}}
      orderBy: {descendingByField: "sold_usd"}
      limit: {count: $limit}
    ) {
      Trade { Account { Address } }
      bought_usd: sum(of: Trade_Side_AmountInUSD, if: {Trade: {Side: {Type: {is: sell}}}})
      sold_usd:   sum(of: Trade_Side_AmountInUSD, if: {Trade: {Side: {Type: {is: buy}}}})
      n_buys:  count(if: {Trade: {Side: {Type: {is: sell}}}})
      n_sells: count(if: {Trade: {Side: {Type: {is: buy}}}})
    }
  }
}
"""


def wallet_aggregates(mint: str, since, till, limit: int = 300, url: str = EAP) -> pd.DataFrame:
    """Per-wallet buy/sell USD and counts over a window, aggregated server-side."""
    data = query(WALLET_AGG, {"mint": mint, "since": iso(since), "till": iso(till), "limit": limit}, url=url)
    rows = (data.get("Solana") or {}).get("DEXTradeByTokens") or []
    out = []
    for r in rows:
        out.append({"wallet": ((r.get("Trade") or {}).get("Account") or {}).get("Address"),
                    "bought_usd": float(r.get("bought_usd") or 0), "sold_usd": float(r.get("sold_usd") or 0),
                    "n_buys": int(r.get("n_buys") or 0), "n_sells": int(r.get("n_sells") or 0)})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["net_usd"] = df["sold_usd"] - df["bought_usd"]
    df["trades"] = df["n_buys"] + df["n_sells"]
    return df.sort_values("net_usd", ascending=False).reset_index(drop=True)


WALLET_TRADES = """
query($mint: String!, $wallet: String!, $since: DateTime!, $till: DateTime!) {
  Solana {
    DEXTradeByTokens(
      where: {Trade: {Currency: {MintAddress: {is: $mint}}, Account: {Address: {is: $wallet}}},
              Block: {Time: {since: $since, till: $till}}}
      orderBy: {ascending: Block_Time}
      limit: {count: 10000}
    ) {
      Block { Time }
      Trade { Side { Type } Amount AmountInUSD PriceInUSD }
    }
  }
}
"""


def wallet_trades(mint: str, wallet: str, since, till, url: str = EAP) -> pd.DataFrame:
    """One wallet's fills in a token over a window."""
    data = query(WALLET_TRADES, {"mint": mint, "wallet": wallet, "since": iso(since), "till": iso(till)}, url=url)
    rows = (data.get("Solana") or {}).get("DEXTradeByTokens") or []
    out = []
    for r in rows:
        t = r.get("Trade") or {}
        out.append({"time": r.get("Block", {}).get("Time"),
                    "side": ((t.get("Side") or {}).get("Type") or "").lower(),
                    "usd": float(t.get("AmountInUSD") or 0), "price": float(t.get("PriceInUSD") or 0)})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], format="mixed", utc=True)
    return df.sort_values("time").reset_index(drop=True)
