"""Append-only log of evaluated strategies. JSONL is the source of truth; the table renders only the improvements."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Optional

from synthetix_alpha.strategy.run import backtest
from synthetix_alpha.strategy.spec import Spec
from synthetix_alpha.strategy.verify import score

LOG = Path("docs/progress.jsonl")
TABLE = Path("docs/progress.md")

HEADER = """# Strategy progress log

Each row beat every candidate evaluated before it, so this is the improvement path of the search rather than a list of
everything tried. Rows marked ⚠ are corrections: the same strategy restated after an engine change, kept even when the
score falls, because a number that is no longer believed should not remain the headline. Appended by `python -m synthetix_alpha.strategy.progress <spec.json> --gen N`; the full history,
including evaluations that did not improve, stays in the append-only `progress.jsonl` beside this file.

Score is the search's selection score:
`0.5*mean_sharpe + 0.5*min_sharpe + 2*worst_year + 3*max(maxDD, -1) + (positive_years - 1)`, with fewer than 40 trades
scoring -9. Return is the mean across the underlyings traded, each on its own $100k.

| evaluated (UTC) | gen | strategy | underlyings | return | mean Sharpe | min Sharpe | max DD | worst year | trades | score | what changed |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""


def entry(spec: Spec, results: dict, gen: int, note: str = "", when: Optional[dt.datetime] = None,
          source: str = "kaggle", correction: bool = False) -> dict:
    s = results["summary"]
    total = sum(m["total_return"] for m in results["results"].values()) / max(len(results["results"]), 1)
    return {"evaluated_utc": (when or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M"),
            "gen": gen, "strategy": spec.name, "underlyings": "+".join(results["results"]), "source": source,
            "total_return": round(total, 4), "mean_sharpe": round(s["mean_sharpe"], 3),
            "min_sharpe": round(s["min_sharpe"], 3), "worst_drawdown": round(s["worst_drawdown"], 4),
            "worst_year": round(s["worst_year"], 4), "trades": s["total_trades"],
            "score": round(score(s), 3), "note": note, "correction": correction}


def append(rows: list[dict], log: Path = LOG) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load(log: Path = LOG) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def improvements(rows: list[dict]) -> list[dict]:
    """Rows that beat every earlier score, plus corrections. A correction restates a score on a changed engine, so it
    resets the bar rather than being filtered out for being lower."""
    best, out = None, []
    for r in sorted(rows, key=lambda r: (r["evaluated_utc"], r["strategy"])):
        if r.get("correction") or best is None or r["score"] > best:
            best, _ = r["score"], out.append(r)
    return out


def render(log: Path = LOG, table: Path = TABLE) -> Path:
    rows = load(log)
    kept = improvements(rows)
    md = HEADER + "".join(
        f"| {r['evaluated_utc']} | {r['gen']} | `{r['strategy']}` | {r['underlyings']} | {r['total_return']:+.1%} | "
        f"{r['mean_sharpe']:.2f} | {r['min_sharpe']:.2f} | {r['worst_drawdown']:.1%} | {r['worst_year']:+.1%} | "
        f"{r['trades']} | **{r['score']:+.3f}** | {'⚠ ' if r.get('correction') else ''}{r.get('note', '')} |\n"
        for r in kept)
    if kept:
        md += (f"\n{len(kept)} improvements across {len(rows)} logged evaluations; "
               f"score {kept[0]['score']:+.3f} -> {kept[-1]['score']:+.3f}, "
               f"mean Sharpe {kept[0]['mean_sharpe']:.2f} -> {kept[-1]['mean_sharpe']:.2f}.\n")
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(md, encoding="utf-8")
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="spec to evaluate and log; omit to only re-render the table")
    ap.add_argument("--gen", type=int, default=0)
    ap.add_argument("--note", default="")
    ap.add_argument("--source", default="kaggle", choices=["kaggle", "dolt"])
    ap.add_argument("--correction", action="store_true", help="a restated score on a changed engine; always rendered")
    a = ap.parse_args()
    if a.spec:
        spec = Spec.load(a.spec)
        append([entry(spec, backtest(spec, source=a.source), a.gen, a.note, source=a.source, correction=a.correction)])
    print(render())


if __name__ == "__main__":
    main()
