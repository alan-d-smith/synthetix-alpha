"""WRDS REST client.

Research only: OptionMetrics stops at 2025-08-29 and CRSP daily at 2024-12-31, so nothing here can reach the
order path. It exists to validate the spec's gates on the data the literature actually uses, rather than on the
DoltHub mirror the screen runs against live.

Two API quirks worth knowing, both found the hard way:
  - `count` is stale and lies. It carries values across unrelated requests: a filter matching nothing still
    reports thousands. Only len(results) means anything.
  - Only columns registered as filterable accept a filter, and the rest are ignored rather than rejected, so a
    typo or an unregistered column looks like it worked. `fields()` asks the endpoint which are which: on the
    OptionMetrics tables only `date` and `secid` qualify, so maturity and call/put are selected client-side.
    Operators are Django-style suffixes (`date__gte`, `secid__in`, `symbol__startswith`).
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import pandas as pd

BASE = "https://wrds-api.wharton.upenn.edu/data"
PAGE = 500


def token() -> str:
    tok = os.environ.get("WRDS")
    if not tok:
        raise RuntimeError("WRDS not set (see .env.example)")
    return tok


def fields(table: str) -> pd.DataFrame:
    """Columns of a table and which of them can actually be filtered on."""
    with httpx.Client(timeout=60, follow_redirects=True,
                      headers={"Authorization": f"Token {token()}"}) as c:
        r = c.options(f"{BASE}/{table}/")
        r.raise_for_status()
        f = r.json().get("fields") or {}
    return (pd.DataFrame([{"column": k, "type": v.get("type"), "filterable": v.get("filter_field")}
                          for k, v in f.items()])
            .sort_values(["filterable", "column"], ascending=[False, True]).reset_index(drop=True))


def get(table: str, *, limit: Optional[int] = None, **params: Any) -> pd.DataFrame:
    """Every row matching the filters, following pagination."""
    rows: list[dict] = []
    url: Optional[str] = f"{BASE}/{table}/"
    q: Optional[dict] = {"limit": PAGE, **{k: v for k, v in params.items() if v is not None}}
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"Authorization": f"Token {token()}"}) as c:
        while url:
            r = c.get(url, params=q)
            r.raise_for_status()
            body = r.json()
            rows += body.get("results") or []
            if limit and len(rows) >= limit:
                break
            url, q = body.get("next"), None
    df = pd.DataFrame(rows[:limit] if limit else rows)
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def secids(tickers: list[str]) -> dict[str, int]:
    """Ticker to OptionMetrics secid. Tickers get reused, so prefer the most recently effective mapping."""
    out: dict[str, int] = {}
    for t in tickers:
        df = get("optionm.secnmd", ticker=t)
        if df.empty:
            continue
        df = df.sort_values("effect_date")
        out[t] = int(df["secid"].iloc[-1])
    return out


def atm_iv(secid: int, year: int, days: int = 30, cp: str = "P") -> pd.DataFrame:
    """At-the-money implied volatility from the standardised option file, one row per date."""
    df = get(f"optionm.stdopd{year}", secid=str(secid))
    if df.empty:
        return df
    df = df[(df["days"] == days) & (df["cp_flag"] == cp)]     # neither filter binds server-side
    return df[["date", "impl_volatility", "premium", "vega", "strike_price"]].rename(
        columns={"impl_volatility": "iv"}).sort_values("date").reset_index(drop=True)


def realised_vol(secid: int, year: int, days: int = 30) -> pd.DataFrame:
    """OptionMetrics' own realised volatility over the trailing `days`, so IV and RV share a convention."""
    df = get(f"optionm.hvold{year}", secid=str(secid))
    if df.empty:
        return df
    df = df[df["days"] == days]
    return df[["date", "volatility"]].rename(columns={"volatility": "rv"}).sort_values("date").reset_index(drop=True)
