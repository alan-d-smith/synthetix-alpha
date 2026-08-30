"""Finnhub client for fundamental data, analyst recommendations, market news, and social sentiment.

Returns pandas 3.x DataFrames with canonical column layouts.  Respects the free-tier rate limit
(60 calls / minute) with token-bucket pacing and exponential backoff on transient errors.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from typing import Any, Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit constants (Finnhub free tier: 60 req / min → 1.0 s between calls;
# use a slightly relaxed 1.05 s to stay comfortably under the cap)
# ---------------------------------------------------------------------------
_MIN_INTERVAL: float = 1.05
_MAX_RETRIES: int = 2
_BACKOFF_BASE: float = 2.0  # exponential: 2s, 4s, 8s ...

# ---------------------------------------------------------------------------
# Canonical column sets
# ---------------------------------------------------------------------------
PROFILE_COLUMNS = [
    "ticker", "name", "exchange", "currency", "ipo",
    "market_capitalization", "share_outstanding",
    "finnhub_industry", "finnhub_sector", "country",
    "weburl", "logo", "phone",
]

NEWS_COLUMNS = [
    "datetime", "headline", "source", "summary", "url",
    "category", "related_symbols",
]

RECOMMENDATION_COLUMNS = [
    "period", "strongSell", "sell", "hold", "buy", "strongBuy",
    "consensus_score",
]

SOCIAL_SENTIMENT_COLUMNS = [
    "source", "at_time", "symbol", "mention", "positive_score",
    "negative_score", "score",
]

INSIDER_COLUMNS = [
    "year", "month", "symbol", "change", "mspr",
]


def _today_str() -> str:
    """ISO-format today's date as a string (Finnhub API expects strings)."""
    return dt.date.today().isoformat()


def _days_ago_str(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


class FinnhubAPIError(Exception):
    """Raised when a Finnhub API call fails after all retries are exhausted."""


class FinnhubClient:
    """Synchronous Finnhub IO client returning pandas DataFrames.

    Parameters
    ----------
    api_key : str or None
        Finnhub API key.  Falls back to the ``FINNHUB_API_KEY`` env var.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        resolved = api_key or os.environ.get("FINNHUB_API_KEY")
        if not resolved:
            raise ValueError(
                "FinnhubClient requires an API key.  "
                "Set FINNHUB_API_KEY in .env or pass api_key=..."
            )
        import finnhub

        self._client = finnhub.Client(api_key=resolved)
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pace(self) -> None:
        """Enforce the minimum inter-call interval."""
        now = time.monotonic()
        wait = self._last_call + _MIN_INTERVAL - now
        if wait > 0:
            logger.debug("rate-limit: sleeping %.2fs", wait)
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call(
        self,
        fn: Callable[..., dict],
        *args: Any,
        retries: int = _MAX_RETRIES,
        **kwargs: Any,
    ) -> dict:
        """Invoke *fn* with pacing and exponential-backoff retries.

        Returns the raw ``dict`` on success or an empty ``dict`` on a
        non-fatal error (e.g. symbol not found).  Re-raises
        ``FinnhubAPIError`` when retries are exhausted.
        """
        import finnhub

        for attempt in range(retries + 1):
            self._pace()
            try:
                return fn(*args, **kwargs) or {}
            except finnhub.FinnhubAPIException as exc:
                status = getattr(exc, "status_code", 0)
                if status == 429:
                    delay = _BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "Finnhub rate-limited (429) — sleeping %ds", delay
                    )
                    time.sleep(delay)
                    if attempt == retries:
                        raise FinnhubAPIError(
                            f"Rate-limited after {retries + 1} attempts"
                        ) from exc
                    continue
                if status in (400, 404):
                    logger.info("Finnhub call returned %d — returning empty", status)
                    return {}
                logger.warning("Finnhub error (status=%d): %s", status, exc)
                if attempt == retries:
                    return {}
            except (ConnectionError, TimeoutError) as exc:
                delay = _BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Finnhub network error — retrying in %ds (%s)", delay, exc
                )
                time.sleep(delay)
                if attempt == retries:
                    raise FinnhubAPIError(
                        f"Network error after {retries + 1} attempts"
                    ) from exc
        return {}  # pragma: no cover

    @staticmethod
    def _df(raw: list[dict], columns: list[str]) -> pd.DataFrame:
        """Normalize a list-of-dicts into a DataFrame with the given *columns*."""
        if not raw:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(raw)
        for c in columns:
            if c not in df.columns:
                df[c] = None
        return df[columns].infer_objects(copy=False)
# ------------------------------------------------------------------
    # Public methods — each returns a pd.DataFrame
    # ------------------------------------------------------------------

    def company_profile(self, symbol: str) -> pd.DataFrame:
        """Company fundamentals: sector, industry, market cap, IPO date, etc.

        Returns
        -------
        pd.DataFrame
            Single-row frame with columns defined by ``PROFILE_COLUMNS``.
            Returns an empty frame when the symbol is not found.
        """
        raw = self._call(self._client.company_profile2, symbol=symbol.upper())
        if not raw:
            return pd.DataFrame(columns=PROFILE_COLUMNS)
        return self._df([{
            "ticker": raw.get("ticker"),
            "name": raw.get("name"),
            "exchange": raw.get("exchange"),
            "currency": raw.get("currency"),
            "ipo": raw.get("ipo"),
            "market_capitalization": raw.get("marketCapitalization"),
            "share_outstanding": raw.get("shareOutstanding"),
            "finnhub_industry": raw.get("finnhubIndustry"),
            "finnhub_sector": None,
            "country": raw.get("country"),
            "weburl": raw.get("weburl"),
            "logo": raw.get("logo"),
            "phone": raw.get("phone"),
        }], PROFILE_COLUMNS)

    def company_financials(self, symbol: str) -> pd.DataFrame:
        """Key financial metrics (PE, EPS, beta, margins, etc.).

        Returns
        -------
        pd.DataFrame
            Columns are the finnhub metric keys; a single row per symbol.
            Empty frame when no data is available.
        """
        raw = self._call(
            self._client.company_basic_financials, symbol.upper(), "all"
        )
        metric: dict = raw.get("metric", {})
        if not metric:
            return pd.DataFrame()
        df = pd.DataFrame([metric]).infer_objects(copy=False)
        # Normalise finnhub camelCase to snake_case for readability
        renames = {
            c: (
                c[0].lower()
                + "".join(
                    "_" + x.lower() if x.isupper() else x for x in c[1:]
                )
            )
            for c in df.columns
        }
        return df.rename(columns=renames)

    def company_news(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Recent company-specific news articles.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        start : str or None
            ISO date string (YYYY-MM-DD).  Defaults to 7 days ago.
        end : str or None
            ISO date string.  Defaults to today.

        Returns
        -------
        pd.DataFrame
            Sorted by *datetime* descending.  Empty when no articles are found.
        """
        s = start or _days_ago_str(7)
        e = end or _today_str()
        raw: list[dict] = self._call(
            self._client.company_news, symbol.upper(), _from=s, to=e
        )
        if not raw:
            return pd.DataFrame(columns=NEWS_COLUMNS)
        rows = []
        for article in raw:
            related = article.get("related", "")
            rows.append({
                "datetime": (
                    pd.Timestamp(article["datetime"], unit="s")
                    if "datetime" in article
                    else None
                ),
                "headline": article.get("headline"),
                "source": article.get("source"),
                "summary": article.get("summary"),
                "url": article.get("url"),
                "category": article.get("category"),
                "related_symbols": (
                    ",".join(related) if isinstance(related, list)
                    else related
                ),
            })
        return (
            self._df(rows, NEWS_COLUMNS)
            .sort_values("datetime", ascending=False, na_position="last")
            .reset_index(drop=True)
        )
    def get_bulk_news(
        self,
        symbols: list[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        *,
        dedup: bool = True,
    ) -> pd.DataFrame:
        """Fetch news for multiple symbols, optionally deduplicating
        stories that mention more than one of the requested names.

        Parameters
        ----------
        symbols : list[str]
            Ticker symbols to fetch news for.
        start, end : str or None
            Date range.
        dedup : bool
            If ``True`` (default), drop duplicate (headline, source,
            datetime) rows and produce a ``tickers`` column that
            aggregates all symbols that referenced each story.

        Returns
        -------
        pd.DataFrame
            ``NEWS_COLUMNS`` + ``tickers`` when *dedup* is True.
        """
        frames: list[pd.DataFrame] = []
        total_pulled = 0
        for sym in symbols:
            df = self.company_news(sym, start=start, end=end)
            if df.empty:
                continue
            df["symbol"] = sym.upper()
            total_pulled += len(df)
            frames.append(df)

        if not frames:
            logger.info("bulk_news: no articles for %d symbols", len(symbols))
            cols = NEWS_COLUMNS + (["tickers"] if dedup else [])
            return pd.DataFrame(columns=cols)

        combined = pd.concat(frames, ignore_index=True)

        if not dedup or len(frames) <= 1:
            return combined.sort_values(
                "datetime", ascending=False, na_position="last"
            ).reset_index(drop=True)

        # -- deduplication -------------------------------------------------
        dedup_keys = ["headline", "source", "datetime"]
        groups = combined.groupby(dedup_keys, dropna=False, sort=False)

        deduped_rows: list[dict] = []
        for _, grp in groups:
            row = grp.iloc[0].to_dict()
            symbols_set = set(grp.get("symbol", pd.Series(dtype=str)).dropna())
            row["tickers"] = ",".join(sorted(symbols_set))
            deduped_rows.append(row)

        after = len(deduped_rows)
        logger.info(
            "bulk_news: %d articles -> %d unique (deduped from %d symbols)",
            total_pulled,
            after,
            len(symbols),
        )
        return (
            self._df(deduped_rows, [*NEWS_COLUMNS, "tickers"])
            .sort_values("datetime", ascending=False, na_position="last")
            .reset_index(drop=True)
        )
    def recommendation_trends(self, symbol: str) -> pd.DataFrame:
        """Analyst consensus trend over time.

        Returns
        -------
        pd.DataFrame
            Columns: *period*, *strongSell*, *sell*, *hold*, *buy*,
            *strongBuy*, and the computed *consensus_score*
            (-2 = unanimous strong sell ... +2 = unanimous strong buy).
            Sorted by *period* ascending.
        """
        raw: list[dict] = self._call(
            self._client.recommendation_trends, symbol.upper()
        )
        if not raw:
            return pd.DataFrame(columns=RECOMMENDATION_COLUMNS)
        df = self._df(raw, ["period", "strongSell", "sell", "hold", "buy", "strongBuy"])
        df["period"] = pd.to_datetime(df["period"])
        # Weighted consensus: -2 ... +2
        weights = {"strongSell": -2, "sell": -1, "hold": 0, "buy": 1, "strongBuy": 2}
        total = df[list(weights)].sum(axis=1)
        weighted = sum(df[k] * v for k, v in weights.items())
        df["consensus_score"] = (weighted / total.replace(0, pd.NA)).round(3)
        return df.sort_values("period").reset_index(drop=True)

    def social_sentiment(self, symbol: str) -> pd.DataFrame:
        """Reddit and Twitter sentiment for a symbol.

        Returns a unified frame (one row per observation) with columns
        defined by ``SOCIAL_SENTIMENT_COLUMNS``.  Sorted by *at_time*
        descending.
        """
        raw = self._call(self._client.stock_social_sentiment, symbol.upper())
        rows: list[dict] = []
        for source_key in ("reddit", "twitter"):
            for entry in raw.get(source_key, []) or []:
                rows.append({
                    "source": source_key,
                    "at_time": pd.Timestamp(entry.get("atTime")),
                    "symbol": symbol.upper(),
                    "mention": entry.get("mention", 0),
                    "positive_score": entry.get("positiveScore", 0.0),
                    "negative_score": entry.get("negativeScore", 0.0),
                    "score": entry.get("score", 0.0),
                })
        if not rows:
            return pd.DataFrame(columns=SOCIAL_SENTIMENT_COLUMNS)
        return (
            self._df(rows, SOCIAL_SENTIMENT_COLUMNS)
            .sort_values("at_time", ascending=False, na_position="last")
            .reset_index(drop=True)
        )

    def insider_sentiment(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Monthly insider transaction trends (net purchase/sale).

        Returns
        -------
        pd.DataFrame
            Columns: *year*, *month*, *symbol*, *change* (net shares),
            *mspr* (Monthly Share Purchase Ratio).
            Sorted by *year*, *month* ascending.
        """
        raw: dict = self._call(
            self._client.stock_insider_sentiment,
            symbol.upper(),
            start or "2020-01-01",
            end or _today_str(),
        )
        data: list[dict] = raw.get("data", [])
        if not data:
            return pd.DataFrame(columns=INSIDER_COLUMNS)
        df = self._df(data, ["year", "month", "change", "mspr"])
        for col in ("year", "month"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("change", "mspr"):
            df[col] = df[col].astype(float)
        df["symbol"] = symbol.upper()
        return df.sort_values(["year", "month"]).reset_index(drop=True)