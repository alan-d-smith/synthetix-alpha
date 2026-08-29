"""
finnhub_client.py — Finnhub API client.

Provides company news, insider sentiment, and earnings calendar data
for the research agent's NLP pipeline.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import finnhub
from loguru import logger


def _get_client() -> finnhub.Client:
    """Get or create a Finnhub client from the API key."""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FINNHUB_API_KEY not set in environment. "
            "Set it in .env and restart."
        )
    return finnhub.Client(api_key=api_key)


def get_company_news(ticker: str, days_back: int = 7) -> list[dict[str, Any]]:
    """Fetch recent news articles for a given ticker.

    Args:
        ticker: Stock symbol.
        days_back: Number of days of news to retrieve.

    Returns:
        List of news article dicts with keys: headline, summary, datetime,
        source, url, sentiment (optional — from Finnhub).
    """
    try:
        client = _get_client()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)
        raw = client.company_news(
            ticker,
            _from=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d"),
        )
        articles = []
        for item in raw[:20]:  # Cap at 20 articles
            articles.append({
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "datetime": datetime.fromtimestamp(
                    item.get("datetime", 0), tz=timezone.utc
                ).isoformat(),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
            })
        logger.info(f"Finnhub: {len(articles)} news articles for {ticker} "
                     f"(last {days_back} days)")
        return articles
    except Exception as e:
        logger.warning(f"Finnhub company_news failed for {ticker}: {e}")
        return []


def get_insider_sentiment(ticker: str) -> dict[str, Any]:
    """Fetch insider transaction sentiment for a ticker.

    Args:
        ticker: Stock symbol.

    Returns:
        Dict with insider sentiment metrics.
    """
    try:
        client = _get_client()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        data = client.stock_insider_sentiment(
            ticker,
            _from=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d"),
        )
        if not data or "data" not in data or not data["data"]:
            return {}
        latest = data["data"][-1]
        return {
            "mspr": latest.get("mspr", 0.0),
            "change": latest.get("change", 0),
            "month": latest.get("month", 0),
            "year": latest.get("year", 0),
        }
    except Exception as e:
        logger.warning(f"Finnhub insider_sentiment failed for {ticker}: {e}")
        return {}


def get_earnings_calendar(
    ticker: str,
    days_ahead: int = 30,
) -> list[dict[str, Any]]:
    """Fetch upcoming earnings dates for a ticker.

    Args:
        ticker: Stock symbol.
        days_ahead: Look-ahead window in days.

    Returns:
        List of upcoming earnings event dicts.
    """
    try:
        client = _get_client()
        end = datetime.now(timezone.utc)
        start = end + timedelta(days=days_ahead)
        data = client.earnings_calendar(
            _from=end.strftime("%Y-%m-%d"),
            to=start.strftime("%Y-%m-%d"),
            symbol=ticker,
            international=False,
        )
        if not data or "earningsCalendar" not in data:
            return []
        events = []
        for item in data["earningsCalendar"]:
            if item.get("symbol") == ticker:
                events.append({
                    "date": item.get("date", ""),
                    "eps_estimate": item.get("epsEstimate"),
                    "revenue_estimate": item.get("revenueEstimate"),
                })
        return events
    except Exception as e:
        logger.warning(f"Finnhub earnings_calendar failed for {ticker}: {e}")
        return []