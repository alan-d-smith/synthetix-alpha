import datetime as dt
import json

from synthetix_alpha.strategy import progress
from synthetix_alpha.strategy.spec import Spec

SPEC = Spec("demo", legs=[{"type": "put", "side": "short", "delta": 0.3},
                          {"type": "put", "side": "long", "delta": 0.15}])
RESULTS = {"results": {"SPY": {"total_return": 0.08, "yearly": {"2021": 0.05}},
                       "QQQ": {"total_return": 0.04, "yearly": {"2021": 0.03}}},
           "summary": {"mean_sharpe": 1.0, "min_sharpe": 0.9, "worst_year": 0.01,
                       "positive_years": 1.0, "worst_drawdown": -0.02, "total_trades": 100}}


def test_entry_shape():
    e = progress.entry(SPEC, RESULTS, gen=3, note="hi", when=dt.datetime(2026, 9, 1, 12, 30, tzinfo=dt.timezone.utc))
    assert e["evaluated_utc"] == "2026-09-01 12:30" and e["underlyings"] == "SPY+QQQ"
    assert e["total_return"] == 0.06 and e["trades"] == 100 and e["score"] > 0.8


def test_log_is_append_only_and_renders(tmp_path):
    log, table = tmp_path / "p.jsonl", tmp_path / "p.md"
    first = progress.entry(SPEC, RESULTS, 1, "first", dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc))
    progress.append([first], log)
    worse = {**RESULTS, "summary": {**RESULTS["summary"], "mean_sharpe": 0.1, "min_sharpe": 0.0}}
    progress.append([progress.entry(SPEC, worse, 2, "worse", dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc))], log)
    assert len(progress.load(log)) == 2  # nothing overwritten
    md = progress.render(log, table).read_text(encoding="utf-8")
    assert md.count("| 2026-09-0") == 3  # 2 rows in the table + 1 in the best-over-time section
    assert "worse" in md and "first" in md


def test_best_over_time_only_records_improvements(tmp_path):
    log, table = tmp_path / "p.jsonl", tmp_path / "p.md"
    rows = []
    for i, sharpe in enumerate([0.2, 0.1, 0.9]):  # middle entry is a regression
        r = {**RESULTS, "summary": {**RESULTS["summary"], "mean_sharpe": sharpe, "min_sharpe": sharpe}}
        rows.append(progress.entry(SPEC, r, i, "", dt.datetime(2026, 9, i + 1, tzinfo=dt.timezone.utc)))
    progress.append(rows, log)
    best = progress.render(log, table).read_text(encoding="utf-8").split("## All evaluations")[0]
    assert "2026-09-01" in best and "2026-09-03" in best and "2026-09-02" not in best
