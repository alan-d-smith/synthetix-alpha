"""Research loop CLI: find papers, download them for the agent, evaluate the specs it writes back.

    python -m synthetix_alpha.research.loop find              # queue papers, print the agent brief
    python -m synthetix_alpha.research.loop evaluate <dir>    # backtest specs, log survivors, mark papers done
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from synthetix_alpha.research import arxiv
from synthetix_alpha.strategy import progress
from synthetix_alpha.strategy.run import backtest
from synthetix_alpha.strategy.spec import Spec
from synthetix_alpha.strategy.verify import score

SPEC_DIR = Path("datasets/research/papers/specs")
NOISE_FLOOR = 0.54  # smallest Sharpe difference this sample can resolve; see docs/research.md

BRIEF = """Read each paper and write any strategy it implies as a Spec JSON (see synthetix_alpha/strategy/spec.py).
Rules that matter:
- Only ideas the engine can express: daily decisions, static positions, legs by delta/moneyness/width, signal gates
  over the listed features. Anything else goes in missing_primitives instead of a spec.
- Name specs paper_<arxivid>_<short>.json, write them to {spec_dir}, and set the spec's `source` field to
  "arXiv:<id> <short title>" so every result stays attributable to the paper it came from.
- Do not tune on the backtest. Write the paper's idea, then let `loop evaluate` score it.
- A candidate is only interesting if it beats the incumbent by more than {floor} Sharpe; smaller differences are
  inside this sample's noise. Say so rather than claiming an improvement.

Papers queued:
{papers}
"""


# Both sleeves. The equity topics were added once the gap fade became the validated core: searching only for
# option papers cannot turn up anything about the strategy that is actually carrying the book.
# Both sleeves. The equity topics target the gap fade obliquely as well as directly: the sizing, timing and
# cost questions it faces are the same ones the intraday microstructure literature works on, so a paper need
# not name the trade to sharpen it.
TOPICS = ("variance risk premium", "volatility risk premium", "option returns", "covered call",
          "put writing", "implied volatility term structure", "option trading strategy", "delta hedging",
          "overnight returns stocks", "close-to-open return", "intraday return predictability",
          "short-term reversal stocks", "opening auction imbalance", "cross-section of stock returns",
          "execution cost equity", "order flow imbalance", "intraday portfolio sorts")


def find(limit: int = 5, min_relevance: float = 0.4, since_days: int = 120, download: bool = True,
         topics: Optional[list[str]] = None) -> list[dict]:
    """Recent submissions plus targeted topic searches, filtered against the library."""
    seen = arxiv.load_library()
    found = {p["id"]: p for p in arxiv.pending(min_relevance=min_relevance, since_days=since_days, limit=limit * 3)}
    for t in (topics if topics is not None else TOPICS):
        for p in arxiv.search(terms=[t], max_results=15):
            if p["id"] not in seen and arxiv.relevance(p) >= min_relevance:
                found.setdefault(p["id"], p)
    papers = sorted(found.values(), key=lambda p: (-arxiv.relevance(p), p["published"]), reverse=False)[:limit]
    for p in papers:
        p["local_pdf"] = str(arxiv.download(p)) if download else ""
    arxiv.record(papers, status="queued")
    return papers


def brief(papers: list[dict], spec_dir: Path = SPEC_DIR) -> str:
    lines = [f"- {p['id']} ({p['published']}, relevance {arxiv.relevance(p):.2f}) {p['title']}\n"
             f"    pdf: {p.get('local_pdf') or p['pdf_url']}" for p in papers]
    return BRIEF.format(spec_dir=spec_dir, floor=NOISE_FLOOR, papers="\n".join(lines) or "  (none)")


def evaluate(spec_dir: Path = SPEC_DIR, incumbent: Optional[Path] = None, log: bool = True) -> list[dict]:
    """Backtest every spec in the directory and report which clear the incumbent by more than the noise floor."""
    base = score(backtest(Spec.load(incumbent))["summary"]) if incumbent else None
    out = []
    for path in sorted(spec_dir.glob("paper_*.json")):
        if path.name.endswith("_results.json"):
            continue
        try:
            spec = Spec.load(path)
            res = backtest(spec)
        except Exception as e:
            out.append({"spec": path.name, "error": f"{type(e).__name__}: {e}"})
            continue
        s = score(res["summary"])
        row = {"spec": spec.name, "score": round(s, 3), "mean_sharpe": round(res["summary"]["mean_sharpe"], 3),
               "trades": res["summary"]["total_trades"],
               "beats_incumbent": None if base is None else bool(s - base > 0)}
        if base is not None:
            row["above_noise_floor"] = bool(res["summary"]["mean_sharpe"] - base > NOISE_FLOOR)
        Path(str(path).replace(".json", "_results.json")).write_text(json.dumps(res, indent=1, default=str))
        row["source"] = spec.source
        if log and (base is None or s > base):
            note = f"from {spec.source}" if spec.source else f"paper-derived: {path.stem}"
            progress.append([progress.entry(spec, res, gen=99, note=note)])
        out.append(row)
    if log and out:
        progress.render()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--limit", type=int, default=5)
    f.add_argument("--min-relevance", type=float, default=0.4)
    f.add_argument("--since-days", type=int, default=120)
    f.add_argument("--no-download", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("spec_dir", nargs="?", default=str(SPEC_DIR))
    e.add_argument("--incumbent", default="strategies/put_vertical_ivrv.json")
    a = ap.parse_args()
    if a.cmd == "find":
        papers = find(a.limit, a.min_relevance, a.since_days, not a.no_download)
        print(brief(papers))
    else:
        for row in evaluate(Path(a.spec_dir), Path(a.incumbent) if a.incumbent else None):
            print(json.dumps(row))


if __name__ == "__main__":
    main()
