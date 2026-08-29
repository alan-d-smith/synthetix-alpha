"""arXiv search and a persistent library of papers already seen by the research loop."""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional

import httpx

from synthetix_alpha import config

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
LIBRARY = config.ROOT / "docs" / "papers.jsonl"
PDF_DIR = config.ROOT / "datasets" / "papers"
CATEGORIES = ("q-fin.PM", "q-fin.TR", "q-fin.ST", "q-fin.CP", "q-fin.RM", "q-fin.MF")
MIN_INTERVAL = 3.0  # arXiv asks for one request per three seconds

# Terms that map onto what the engine can express: option structures, vol signals, premium capture.
RELEVANT = ("option", "volatility", "variance risk", "implied vol", "straddle", "strangle", "iron condor",
            "vertical spread", "credit spread", "covered call", "put write", "skew", "term structure",
            "delta hedg", "gamma", "vega", "premium", "vix", "derivative")
IRRELEVANT = ("crypto", "bitcoin", "ethereum", "uniswap", "defi", "dex", "amm ", "token", "nft", "blockchain",
              "energy market", "electricity", "insurance", "carbon", "sports betting", "housing", "agricultur")
_last_call = 0.0


def _get(params: dict) -> str:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    r = httpx.get(API, params=params, timeout=60, follow_redirects=True)
    r.raise_for_status()
    _last_call = time.monotonic()
    return r.text


def _text(entry, tag: str) -> str:
    return " ".join((entry.findtext(f"a:{tag}", "", NS) or "").split())


def parse(xml: str) -> list[dict]:
    out = []
    for e in ET.fromstring(xml).findall("a:entry", NS):
        arxiv_id = _text(e, "id").rsplit("/", 1)[-1]
        pdf = next((l.get("href") for l in e.findall("a:link", NS) if l.get("title") == "pdf"), None)
        out.append({"id": arxiv_id, "title": _text(e, "title"), "abstract": _text(e, "summary"),
                    "published": _text(e, "published")[:10], "updated": _text(e, "updated")[:10],
                    "categories": [c.get("term") for c in e.findall("a:category", NS)],
                    "authors": [_text(a, "name") for a in e.findall("a:author", NS)][:6],
                    "pdf_url": pdf or f"https://arxiv.org/pdf/{arxiv_id}"})
    return out


def search(categories: Iterable[str] = CATEGORIES, terms: Optional[Iterable[str]] = None,
           max_results: int = 50, since: Optional[dt.date] = None) -> list[dict]:
    """Most recent submissions in the given categories, newest first."""
    query = " OR ".join(f"cat:{c}" for c in categories)
    if terms:
        query = f"({query}) AND ({' OR '.join(f'all:%22{t}%22' for t in terms)})"
    papers = parse(_get({"search_query": query, "start": 0, "max_results": max_results,
                         "sortBy": "submittedDate", "sortOrder": "descending"}))
    if since:
        papers = [p for p in papers if p["published"] >= since.isoformat()]
    return papers


def relevance(paper: dict) -> float:
    """Keyword score in [0, 1]; a cheap filter before spending an agent on the full text."""
    text = f"{paper['title']} {paper['abstract']}".lower()
    if any(w in text for w in IRRELEVANT):
        return 0.0
    hits = sum(1 for w in RELEVANT if w in text)
    title_hits = sum(1 for w in RELEVANT if w in paper["title"].lower())
    return min(1.0, (hits + 2 * title_hits) / 8)


def load_library(path: Path = LIBRARY) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def record(papers: list[dict], status: str, path: Path = LIBRARY, **extra) -> None:
    """Append papers to the library so later runs skip them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = load_library(path)
    with path.open("a", encoding="utf-8") as f:
        for p in papers:
            if p["id"] in seen:
                continue
            f.write(json.dumps({"id": p["id"], "title": p["title"], "published": p["published"],
                                "categories": p["categories"], "pdf_url": p["pdf_url"],
                                "relevance": round(relevance(p), 3), "status": status,
                                "seen_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                **extra}) + "\n")


def pending(min_relevance: float = 0.4, max_results: int = 80, since_days: int = 120,
            limit: int = 8, path: Path = LIBRARY) -> list[dict]:
    """Relevant papers not yet in the library, best first."""
    seen = load_library(path)
    since = dt.date.today() - dt.timedelta(days=since_days)
    fresh = [p for p in search(max_results=max_results, since=since) if p["id"] not in seen]
    scored = [(relevance(p), p) for p in fresh]
    return [p for s, p in sorted(scored, key=lambda t: -t[0]) if s >= min_relevance][:limit]


def download(paper: dict, directory: Path = PDF_DIR) -> Path:
    """Fetch the PDF so an agent can read it locally."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{re.sub(r'[^A-Za-z0-9._-]', '_', paper['id'])}.pdf"
    if not path.exists():
        r = httpx.get(paper["pdf_url"], timeout=120, follow_redirects=True)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path
