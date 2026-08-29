"""Append-only log of every evaluated strategy. JSONL is the source of truth; the table is rendered from it."""

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
COLUMNS = ["evaluated_utc", "gen", "strategy", "underlyings", "total_return", "mean_sharpe", "min_sharpe",
           "worst_drawdown", "worst_year", "trades", "score"]


def entry(spec: Spec, results: dict, gen: int, note: str = "", when: Optional[dt.datetime] = None,
          source: str = "kaggle") -> dict:
    s = results["summary"]
    total = sum(m["total_return"] for m in results["results"].values()) / max(len(results["results"]), 1)
    return {"evaluated_utc": (when or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M"),
            "gen": gen, "strategy": spec.name, "underlyings": "+".join(results["results"]), "source": source,
            "total_return": round(total, 4), "mean_sharpe": round(s["mean_sharpe"], 3),
            "min_sharpe": round(s["min_sharpe"], 3), "worst_drawdown": round(s["worst_drawdown"], 4),
            "worst_year": round(s["worst_year"], 4), "trades": s["total_trades"],
            "score": round(score(s), 3), "note": note}


def append(rows: list[dict], log: Path = LOG) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load(log: Path = LOG) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]


def render(log: Path = LOG, table: Path = TABLE) -> Path:
    rows = sorted(load(log), key=lambda r: (r["evaluated_utc"], r["strategy"]))
    best, progression = None, []
    for r in rows:
        if best is None or r["score"] > best["score"]:
            best = r
            progression.append(r)
    head = ("# Strategy progress log\n\n"
            "Every candidate promoted out of a generation, in evaluation order. Appended by\n"
            "`python -m synthetix_alpha.strategy.progress <spec.json> --gen N`; the table is rendered from\n"
            "`progress.jsonl`, which is append-only, so history cannot be rewritten by a later run.\n\n"
            "Score is the selection score used by the search: "
            "`0.5·mean_sharpe + 0.5·min_sharpe + 2·worst_year + 3·max(maxDD,−1) + (positive_years−1)`, "
            "with fewer than 40 trades scoring −9. Returns are the mean across the underlyings traded, each on its "
            "own $100k.\n\n")
    if progression:
        head += "## Best score over time\n\n| evaluated (UTC) | gen | strategy | score |\n|---|---|---|---|\n"
        for r in progression:
            head += f"| {r['evaluated_utc']} | {r['gen']} | `{r['strategy']}` | **{r['score']:+.3f}** |\n"
        head += "\n"
    head += ("## All evaluations\n\n| evaluated (UTC) | gen | strategy | underlyings | return | mean Sharpe | "
             "min Sharpe | max DD | worst year | trades | score | note |\n"
             "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        head += (f"| {r['evaluated_utc']} | {r['gen']} | `{r['strategy']}` | {r['underlyings']} | "
                 f"{r['total_return']:+.1%} | {r['mean_sharpe']:.2f} | {r['min_sharpe']:.2f} | "
                 f"{r['worst_drawdown']:.1%} | {r['worst_year']:+.1%} | {r['trades']} | {r['score']:+.3f} | "
                 f"{r.get('note', '')} |\n")
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(head, encoding="utf-8")
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="spec to evaluate and log; omit with --render to rebuild the table")
    ap.add_argument("--gen", type=int, default=0)
    ap.add_argument("--note", default="")
    ap.add_argument("--source", default="kaggle", choices=["kaggle", "dolt"])
    ap.add_argument("--render", action="store_true", help="only re-render the table from the log")
    a = ap.parse_args()
    if a.spec:
        spec = Spec.load(a.spec)
        append([entry(spec, backtest(spec, source=a.source), a.gen, a.note, source=a.source)])
    print(render())


if __name__ == "__main__":
    main()
