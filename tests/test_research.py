import datetime as dt
import json


from synthetix_alpha.research import arxiv, loop

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2608.11111v1</id>
    <published>2026-08-20T00:00:00Z</published><updated>2026-08-20T00:00:00Z</updated>
    <title>Harvesting the Variance Risk Premium with Option Spreads</title>
    <summary>We study implied volatility richness and credit spread returns.</summary>
    <author><name>A Researcher</name></author>
    <category term="q-fin.PM"/>
    <link title="pdf" href="http://arxiv.org/pdf/2608.11111v1"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2608.22222v1</id>
    <published>2026-08-19T00:00:00Z</published><updated>2026-08-19T00:00:00Z</updated>
    <title>Implied Volatility on a Uniswap DEX</title>
    <summary>A crypto AMM proxy for implied volatility in decentralised markets.</summary>
    <author><name>B Researcher</name></author>
    <category term="q-fin.TR"/>
    <link title="pdf" href="http://arxiv.org/pdf/2608.22222v1"/>
  </entry>
</feed>"""


def test_parse_feed():
    papers = arxiv.parse(FEED)
    assert [p["id"] for p in papers] == ["2608.11111v1", "2608.22222v1"]
    p = papers[0]
    assert p["published"] == "2026-08-20" and p["categories"] == ["q-fin.PM"]
    assert p["pdf_url"].endswith("2608.11111v1") and p["authors"] == ["A Researcher"]


def test_relevance_ranks_options_over_crypto():
    options, crypto = arxiv.parse(FEED)
    assert arxiv.relevance(options) > 0.5
    assert arxiv.relevance(crypto) == 0.0  # excluded regardless of the volatility keywords


def test_library_is_append_only_and_dedupes(tmp_path):
    lib = tmp_path / "papers.jsonl"
    papers = arxiv.parse(FEED)
    arxiv.record(papers, "queued", lib)
    arxiv.record(papers, "done", lib)  # same ids must not be written twice
    assert len(arxiv.load_library(lib)) == 2
    assert len(lib.read_text(encoding="utf-8").strip().splitlines()) == 2
    assert arxiv.load_library(lib)["2608.11111v1"]["status"] == "queued"


def test_pending_skips_seen_and_filters(tmp_path, monkeypatch):
    lib = tmp_path / "papers.jsonl"
    monkeypatch.setattr(arxiv, "_get", lambda params: FEED)
    first = arxiv.pending(path=lib, since_days=3650)
    assert [p["id"] for p in first] == ["2608.11111v1"]  # crypto entry filtered out by relevance
    arxiv.record(first, "queued", lib)
    assert arxiv.pending(path=lib, since_days=3650) == []


def test_since_filter(monkeypatch):
    monkeypatch.setattr(arxiv, "_get", lambda params: FEED)
    assert len(arxiv.search(since=dt.date(2026, 8, 20))) == 1
    assert arxiv.search(since=dt.date(2027, 1, 1)) == []


def test_brief_lists_papers_and_noise_floor():
    text = loop.brief(arxiv.parse(FEED)[:1])
    assert "2608.11111v1" in text and str(loop.NOISE_FLOOR) in text and "missing_primitives" in text


def test_evaluate_reports_errors_without_raising(tmp_path):
    (tmp_path / "paper_broken.json").write_text(json.dumps({"name": "broken", "legs": []}))
    rows = loop.evaluate(tmp_path, incumbent=None, log=False)
    assert len(rows) == 1 and "error" in rows[0]


def test_spec_carries_provenance(tmp_path):
    from synthetix_alpha.strategy.spec import Spec
    s = Spec("paper_x", legs=[{"type": "put", "side": "short", "delta": 0.3}],
             source="arXiv:2608.20020v1 Reconfiguration Premium")
    s.save(tmp_path / "s.json")
    assert Spec.load(tmp_path / "s.json").source.startswith("arXiv:2608.20020v1")


def test_evaluate_reports_source(tmp_path):
    from synthetix_alpha.strategy.spec import Spec
    Spec("paper_demo", legs=[{"type": "put", "side": "short", "delta": 0.3},
                             {"type": "put", "side": "long", "delta": 0.15}],
         underlyings=["SPY"], source="arXiv:9999.1 Demo").save(tmp_path / "paper_demo.json")
    rows = loop.evaluate(tmp_path, incumbent=None, log=False)
    assert rows[0].get("source") == "arXiv:9999.1 Demo"
