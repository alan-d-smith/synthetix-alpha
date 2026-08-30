"""FRED (Federal Reserve Economic Data) client for macroeconomic regime context.

Provides yield-curve spreads, credit stress gauges, financial conditions indices,
and inflation expectations — all as pandas 3.x DataFrames with UTC DatetimeIndex.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests

from synthetix_alpha import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit constants (FRED free tier: 120 req / min)
# ---------------------------------------------------------------------------
FRED_BASE = "https://api.stlouisfed.org/fred"
_MIN_INTERVAL: float = 0.55  # 120 calls/min; 0.55 s is comfortably safe
_MAX_RETRIES: int = 2
_BACKOFF_BASE: float = 2.0

# Core macro snapshot series
_MACRO_SERIES: dict[str, str] = {
    "t10y2y": "T10Y2Y",        # 10Y-2Y Treasury spread
    "t10y3m": "T10Y3M",        # 10Y-3M Treasury spread
    "dgs10": "DGS10",          # 10Y Constant Maturity rate
    "hy_oas": "BAMLH0A0HYM2",  # ICE BofA US High Yield OAS
    "nfci": "NFCI",            # Chicago Fed Nat'l Financial Conditions Index
    "stlfsi": "STLFSI4",       # St. Louis Fed Financial Stress Index
    "t5yifr": "T5YIFR",        # 5Y Forward Inflation Expectation Rate
    "t10yie": "T10YIE",        # 10Y Breakeven Inflation Rate
}

CACHE_DIR = config.ROOT / "datasets" / "fred"


class FredAPIError(Exception):
    """Raised when a FRED API call fails after all retries are exhausted."""


class FredClient:
    """Synchronous FRED API client returning pandas DataFrames.

    Parameters
    ----------
    api_key : str or None
        FRED API key.  Falls back to the ``FRED_API_KEY`` env var.
    cache_dir : Path or None
        Directory for local parquet cache.  Defaults to
        ``datasets/fred/`` under the project root.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self._key = api_key or os.environ.get("FRED_API_KEY")
        if not self._key:
            raise ValueError(
                "FredClient requires an API key.  "
                "Set FRED_API_KEY in .env or pass api_key=..."
            )
        self._cache = Path(cache_dir) if cache_dir else CACHE_DIR
        self._cache.mkdir(parents=True, exist_ok=True)
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pace(self) -> None:
        """Enforce the minimum inter-call interval."""
        now = time.monotonic()
        wait = self._last_call + _MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _api_request(
        self,
        endpoint: str,
        params: dict[str, Any],
        retries: int = _MAX_RETRIES,
    ) -> dict:
        """GET *endpoint* with pacing and exponential-backoff retries.

        Returns the parsed JSON ``dict`` on success, an empty ``dict``
        on a non-fatal error, or raises ``FredAPIError`` when retries
        are exhausted.
        """
        params = {**params, "api_key": self._key, "file_type": "json"}
        url = f"{FRED_BASE}/{endpoint.lstrip('/')}"

        for attempt in range(retries + 1):
            self._pace()
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    delay = _BACKOFF_BASE ** (attempt + 1)
                    logger.warning("FRED rate-limited (429) — sleeping %ds", delay)
                    time.sleep(delay)
                    if attempt == retries:
                        raise FredAPIError(
                            f"Rate-limited after {retries + 1} attempts"
                        )
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in (400, 404):
                    logger.info("FRED %d for %s — returning empty", status, endpoint)
                    return {}
                logger.warning("FRED HTTP error (status=%d): %s", status, exc)
                if attempt == retries:
                    return {}
            except (requests.Timeout, requests.ConnectionError) as exc:
                delay = _BACKOFF_BASE ** (attempt + 1)
                logger.warning("FRED network error — retrying in %ds (%s)", delay, exc)
                time.sleep(delay)
                if attempt == retries:
                    raise FredAPIError(
                        f"Network error after {retries + 1} attempts"
                    ) from exc
            except requests.RequestException as exc:
                logger.warning("FRED request error: %s", exc)
                return {}
            except ValueError as exc:
                logger.warning("FRED JSON decode error: %s", exc)
                if attempt == retries:
                    return {}
        return {}

    @staticmethod
    def _parse_observations(raw: dict, series_id: str) -> pd.DataFrame:
        """Convert a FRED observations JSON payload into a DataFrame.

        Handles ``"."`` -> ``NaN`` coercion and constructs a UTC
        ``DatetimeIndex`` named ``timestamp``.
        """
        obs: list[dict] = raw.get("observations", [])
        if not obs:
            return pd.DataFrame()

        rows: list[dict] = []
        for o in obs:
            date_str = o.get("date", "")
            val = o.get("value", ".")
            if not date_str:
                continue
            rows.append({"timestamp": date_str, "value": val})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.dropna(subset=["timestamp"])

        col = series_id.lower()
        df[col] = pd.to_numeric(
            df["value"].replace(".", np.nan), errors="coerce"
        ).astype("float64")
        df = df.drop(columns=["value"]).set_index("timestamp")
        return df[~df.index.duplicated(keep="last")].sort_index()
# ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_series(
        self,
        series_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch a single FRED series.

        Parameters
        ----------
        series_id : str
            FRED series identifier (e.g. ``"T10Y2Y"``, ``"BAMLH0A0HYM2"``).
        start : str or None
            ISO date string (YYYY-MM-DD).  Defaults to the earliest
            observation.
        end : str or None
            ISO date string.  Defaults to the latest observation.

        Returns
        -------
        pd.DataFrame
            UTC ``DatetimeIndex`` named ``timestamp`` with a single
            ``float64`` column named after the lowercased *series_id*.
            Returns an empty frame when the series is not found.
        """
        cache_path = self._cache / f"{series_id.lower()}.parquet"
        cached = self._load_cached(cache_path, start, end)
        if cached is not None:
            return cached

        params: dict[str, Any] = {
            "series_id": series_id.upper(),
            "limit": 100_000,
            "sort_order": "asc",
        }
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end

        raw = self._api_request("series/observations", params)
        df = self._parse_observations(raw, series_id)
        if not df.empty:
            self._save_cached(df, cache_path)
        return df
    def get_series_metadata(self, series_id: str) -> dict:
        """Retrieve metadata for a FRED series.

        Returns
        -------
        dict
            Keys include ``id``, ``title``, ``units``, ``frequency``,
            ``seasonal_adjustment``, ``last_updated``, and ``notes``.
            Returns an empty ``dict`` when the series is not found.
        """
        raw = self._api_request(
            "series", {"series_id": series_id.upper()}
        )
        if not raw:
            return {}
        s = raw.get("seriess", [{}])[0]
        return {
            "id": s.get("id"),
            "title": s.get("title"),
            "units": s.get("units"),
            "frequency": s.get("frequency"),
            "seasonal_adjustment": s.get("seasonal_adjustment"),
            "last_updated": s.get("last_updated"),
            "notes": s.get("notes"),
        }

    def get_macro_snapshot(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        *,
        ffill: bool = True,
    ) -> pd.DataFrame:
        """Fetch and align the 8 core macro indicators into a single DataFrame.

        Parameters
        ----------
        start, end : str or None
            Date range forwarded to each ``get_series`` call.
        ffill : bool
            If ``True`` (default), forward-fill gaps caused by
            differing observation schedules (daily vs. weekly).

        Returns
        -------
        pd.DataFrame
            UTC ``DatetimeIndex`` with one ``float64`` column per
            indicator.  Columns use the short keys from ``_MACRO_SERIES``
            (``t10y2y``, ``hy_oas``, ...).
        """
        frames: dict[str, pd.DataFrame] = {}
        for short, fred_id in _MACRO_SERIES.items():
            df = self.get_series(fred_id, start=start, end=end)
            if df.empty:
                logger.info("macro_snapshot: %s (%s) returned empty", short, fred_id)
                continue
            frames[short] = df

        if not frames:
            logger.warning("macro_snapshot: no series returned any data")
            return pd.DataFrame()

        combined = pd.concat(frames.values(), axis=1, join="outer")
        if ffill:
            combined = combined.ffill()
        return combined.infer_objects(copy=False)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _load_cached(
        self,
        path: Path,
        start: Optional[str],
        end: Optional[str],
    ) -> Optional[pd.DataFrame]:
        """Return a cached DataFrame if it covers the requested range,
        or ``None`` when a fetch is needed."""
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
        except Exception:
            logger.debug("cache read failed for %s — refetching", path.name)
            return None

        idx = df.index
        if idx.empty or not isinstance(idx, pd.DatetimeIndex):
            return None

        # Check coverage
        if start:
            req_start = pd.Timestamp(start, tz="utc")
            if idx.min() > req_start:
                return None
        if end:
            req_end = pd.Timestamp(end, tz="utc")
            if idx.max() < req_end:
                return None

        # Slice to requested range
        if start:
            df = df[df.index >= pd.Timestamp(start, tz="utc")]
        if end:
            df = df[df.index <= pd.Timestamp(end, tz="utc")]
        return df.infer_objects(copy=False)

    def _save_cached(self, df: pd.DataFrame, path: Path) -> None:
        """Merge with any existing cache to avoid losing older data,
        then persist."""
        if path.exists():
            try:
                existing = pd.read_parquet(path)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")].sort_index()
            except Exception:
                pass
        df.to_parquet(path, compression="zstd")