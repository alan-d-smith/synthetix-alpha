"""FOMC statement dates scraped from federalreserve.gov, cached as parquet.

The statement lands on the last day of each meeting, which is the day the event risk resolves.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from synthetix_alpha import config

CACHE = config.ROOT / "datasets" / "fomc.parquet"
CURRENT = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HISTORICAL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
# pages mix full names and three-letter abbreviations, e.g. "Jul/Aug 31-1 Meeting - 2018"
MONTHS = {m: i for i, m in enumerate(_NAMES, start=1)} | {m[:3]: i for i, m in enumerate(_NAMES, start=1)}


def _page(url: str) -> str:
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text


def parse(html: str, year: Optional[int] = None) -> list[dt.date]:
    """Statement dates from a Fed calendar page. Handles two-day and month-spanning meetings."""
    out = []
    for block in re.findall(r'<div class="panel panel-default">.*?(?=<div class="panel panel-default">|\Z)', html, re.S):
        y = year or next((int(m) for m in re.findall(r"(20\d\d) FOMC Meetings", block)), None)
        for months, days, tail in re.findall(
                r'fomc-meeting__month[^>]*>\s*(?:<strong>)?([A-Za-z/]+)(?:</strong>)?\s*<.*?'
                r'fomc-meeting__date[^>]*>\s*([\d\-–/ ]+)(.{0,60})', block, re.S):
            if any(w in tail.lower() for w in ("notation", "unscheduled", "cancelled")):
                continue
            nums = [int(n) for n in re.findall(r"\d+", days)]
            names = [m for m in months.split("/") if m in MONTHS]
            if not nums or not names or y is None:
                continue
            month = MONTHS[names[-1]]  # a January/February meeting resolves in February
            day = nums[-1]
            yy = y + 1 if month == 1 and len(names) > 1 and names[0] == "December" else y
            try:
                out.append(dt.date(yy, month, day))
            except ValueError:
                continue
    return sorted(set(out))


def parse_historical(html: str) -> list[dt.date]:
    """Older pages read '<h5>January 28-29 Meeting - 2020</h5>'; skip unscheduled, cancelled and notation votes."""
    out = []
    for heading in re.findall(r"<h5[^>]*>([^<]{4,90})</h5>", html):
        low = heading.lower()
        if any(w in low for w in ("unscheduled", "cancelled", "notation")) or "meeting" not in low:
            continue
        year = re.search(r"(20\d\d)", heading)
        months = [w for w in re.findall(r"[A-Za-z]+", heading) if w in MONTHS]
        clean = heading.replace(year.group(1), "") if year else heading  # keep the year out of the day list
        days = [int(n) for n in re.findall(r"(\d{1,2})", clean)]
        if not (year and months and days):
            continue
        month, y = MONTHS[months[-1]], int(year.group(1))
        if month == 1 and len(months) > 1 and MONTHS[months[0]] == 12:  # a Dec/Jan meeting resolves next year
            y += 1
        try:
            out.append(dt.date(y, month, days[-1]))
        except ValueError:
            continue
    return sorted(set(out))


def refresh(years: range = range(2016, 2021), cache: Path = CACHE) -> pd.Series:
    """Fetch the current calendar plus the historical pages and cache the result."""
    dates = set(parse(_page(CURRENT)))
    for y in years:
        try:
            dates |= set(parse_historical(_page(HISTORICAL.format(year=y))))
        except Exception:
            continue
    s = pd.Series(sorted(dates), name="date")
    cache.parent.mkdir(parents=True, exist_ok=True)
    s.to_frame().to_parquet(cache, compression="zstd", index=False)
    return s


def dates(cache: Path = CACHE) -> pd.Series:
    if not cache.exists():
        return refresh(cache=cache)
    return pd.to_datetime(pd.read_parquet(cache)["date"]).dt.date.sort_values().reset_index(drop=True)


def days_to_fomc(index, horizon: int = 120, cache: Path = CACHE) -> pd.Series:
    """Calendar days from each date to the next statement. NaN beyond the horizon."""
    known = list(dates(cache))
    if not known:
        return pd.Series(float("nan"), index=index, name="days_to_fomc")
    ann = pd.Series(known)
    out = []
    for d in index:
        nxt = ann[ann >= d]
        gap = (nxt.iloc[0] - d).days if len(nxt) else None
        out.append(float(gap) if gap is not None and gap <= horizon else float("nan"))
    return pd.Series(out, index=index, name="days_to_fomc")
