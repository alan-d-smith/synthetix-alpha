"""Research phase for the model benchmarking suite."""

from __future__ import annotations
import json, logging, os, time
from dataclasses import dataclass, field
from synthetix_alpha import config
from synthetix_alpha.pipeline.llm import LLMAPIError, LLMClient

logger = logging.getLogger(__name__)
INCUMBENT_SHARPE = 0.92
NOISE_FLOOR = 0.54
DEFAULT_BASE_URL = "https://router.huggingface.co/v1"


@dataclass
class ResearchPerPaper:
    paper_id: str
    title: str
    spec_valid: bool = False
    spec_json_raw: str = ""
    spec_name: str = ""
    mean_sharpe: float = 0.0
    total_trades: int = 0
    beats_incumbent: bool = False
    above_noise_floor: bool = False
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class ResearchBenchmarkResult:
    model: str
    spec_validity_rate: float = 0.0
    avg_sharpe: float = 0.0
    incumbent_beat_rate: float = 0.0
    noise_floor_beat_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_papers: int = 0
    errors: list = field(default_factory=list)
    per_paper: list = field(default_factory=list)

RESEARCH_SYSTEM_PROMPT = (
    "﻿You are a quantitative options researcher. Your job is to read a research paper\n"
    "abstract and write a strategy Spec JSON that the deterministic backtester can\n"
    "score.  Follow the rules below exactly.\n"
    "\n"
    "Spec DSL reference:\n"
    "- Legs: type (call|put|stock), side (long|short), exactly one of delta /\n"
    "  moneyness / width, optional dte_offset and ratio.\n"
    "- Entry: every entry_every_days days when positions < max_positions and every\n"
    "  signal feature is inside its [min, max] range.\n"
    "- Features: iv_rank, atm_iv, rv20, iv_rv_ratio, mom20, sma50_ratio,\n"
    "  sma200_ratio, skew25, term_slope, rsi, bollinger_pos, macd, vix, vix_rank,\n"
    "  vix_rv_ratio, vix_term, nfci, rvol, vwap_dev, days_to_earnings.\n"
    "- Exits: profit_target, stop_loss, dte_exit, max_hold_days.\n"
    "- Sizing: risk_fraction over max_loss|margin|notional, min_credit, min_volume.\n"
    "\n"
    "Data available: SPY 2020-2022, QQQ 2021-2022, AAPL 2016-2023, TSLA 2019-2022,\n"
    "NVDA 2020-2022 (EOD chains, real bid/ask/IV/greeks); Dolt surfaces 2019-2026.\n"
    "\n"
    "What is already known:\n"
    "- The IV/RV gate is the entire edge. Ungated put-spread selling scores -0.78;\n"
    "  gated at 1.27 it scores +1.11.\n"
    "- Directional and technical filters all HURT: RSI, MACD, Bollinger, momentum,\n"
    "  sma200 (-0.001 to -1.02).\n"
    "- RVOL and VWAP deviation looked good in sample and failed out of sample.\n"
    "- Earnings avoidance is the one large single-name effect (+0.99 on AAPL).\n"
    "- This sample resolves Sharpe differences of about 0.54.\n"
    "\n"
    "Deployed incumbent: put_vertical_ivrv, Sharpe 0.92, score +0.520.\n"
    "\n"
    "Output a JSON object with these fields:\n"
    "{\n"
    "  \"paper_id\": \"<arxiv id>\",\n"
    "  \"usable\": true/false,\n"
    "  \"summary\": \"one sentence on what the paper claims\",\n"
    "  \"specs\": [\n"
    "    {\n"
    "      \"name\": \"paper_<id>_<short>\",\n"
    "      \"thesis\": \"one sentence on why this strategy should work\",\n"
    "      \"json_spec\": { <full Spec JSON as defined in spec.py> }\n"
    "    }\n"
    "  ],\n"
    "  \"missing_primitives\": [\"<what the engine lacks>\"],\n"
    "  \"engine_issues\": \"<why it cannot be tested>\"\n"
    "}\n"
    "\n"
    "If the paper needs data or mechanics the engine cannot express, set usable=false\n"
    "and list what is missing instead of forcing a spec.  Do NOT include markdown\n"
    "fences around the JSON.\n"
)

MOCK_RESEARCH_SPEC = {
    "name": "benchmark_mock_put_spread",
    "legs": [
        {"type": "put", "side": "short", "delta": 0.20, "ratio": 1},
        {"type": "put", "side": "long", "delta": 0.10, "ratio": 1},
    ],
    "underlyings": ["SPY"],
    "dte_target": 45,
    "dte_min": 30,
    "dte_max": 60,
    "entry_every_days": 1,
    "max_positions": 4,
    "signal": {"iv_rv_ratio": [1.27, None]},
    "profit_target": 0.75,
    "stop_loss": 2.0,
    "dte_exit": 14,
    "risk_fraction": 0.03,
    "sizing": "max_loss",
    "source": "benchmark mock",
}


def load_research_papers(limit=3):
    papers = []
    lib_path = config.ROOT / "docs" / "papers.jsonl"
    if lib_path.exists():
        for line in lib_path.read_text().splitlines():
            if line.strip():
                p = json.loads(line)
                if p.get("status") == "queued":
                    papers.append(p)
    papers.sort(key=lambda p: p.get("relevance", 0), reverse=True)
    return papers[:limit]


def benchmark_research(model_id, papers, *, base_url=None, api_key=None, mock=False, seed=42):
    result = ResearchBenchmarkResult(model=model_id, total_papers=len(papers))
    logger.info("Research benchmark %s (%d papers)", model_id, len(papers))
    llm = LLMClient(
        api_key=api_key,
        base_url=base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        model=model_id, mock=mock, seed=seed)
    total_sharpe = 0.0
    total_latency = 0.0
    total_valid = 0
    total_beat = 0
    total_above_noise = 0
    for paper in papers:
        per = ResearchPerPaper(paper_id=paper["id"], title=paper["title"])
        cats = ", ".join(paper.get("categories", []))
        abstract = (
            f"This paper is in categories {cats}. "
            f"Based on the title and categories, infer what strategy it likely proposes."
        )
        user_prompt = (
            f"Paper: {paper["id"]} - {paper["title"]}\n"
            f"Published: {paper.get("published", "unknown")}\n"
            f"Categories: {cats}\n\n"
            f"{abstract}\n\n"
            f"Write a Spec JSON for the strategy implied by this paper, "
            f"or set usable=false if the engine cannot express it."
        )
        start = time.perf_counter()
        try:
            if mock:
                raw = json.dumps({
                    "paper_id": paper["id"], "usable": True,
                    "summary": f"Mock: strategy derived from {paper["title"]}",
                    "specs": [{"name": "benchmark_mock", "thesis": "mock", "json_spec": MOCK_RESEARCH_SPEC}],
                    "missing_primitives": [], "engine_issues": "",
                })
            else:
                raw = llm.complete(RESEARCH_SYSTEM_PROMPT, user_prompt)
            per.spec_json_raw = raw
            parsed = json.loads(LLMClient._strip_json(raw))
            if not parsed.get("usable", True):
                per.error = f"Paper not expressible: {parsed.get("engine_issues", "")}"
                result.per_paper.append(per)
                continue
            specs = parsed.get("specs", [])
            if not specs:
                per.error = "No specs returned"
                result.per_paper.append(per)
                continue
            spec_data = specs[0].get("json_spec", {})
            if not spec_data:
                per.error = "Empty json_spec"
                result.per_paper.append(per)
                continue
            try:
                from synthetix_alpha.strategy.spec import Spec
                spec = Spec.from_dict(spec_data)
                per.spec_valid = True
                per.spec_name = spec.name
                total_valid += 1
                from synthetix_alpha.strategy.run import backtest
                bt = backtest(spec)
                summary = bt.get("summary", {})
                per.mean_sharpe = summary.get("mean_sharpe", 0.0)
                per.total_trades = summary.get("total_trades", 0)
                total_sharpe += per.mean_sharpe
                if per.mean_sharpe > INCUMBENT_SHARPE:
                    per.beats_incumbent = True
                    total_beat += 1
                if per.mean_sharpe - INCUMBENT_SHARPE > NOISE_FLOOR:
                    per.above_noise_floor = True
                    total_above_noise += 1
            except Exception as exc:
                per.error = f"Spec/backtest: {type(exc).__name__}: {exc}"[:200]
        except (json.JSONDecodeError, LLMAPIError, ValueError) as exc:
            per.error = f"Parse: {type(exc).__name__}: {exc}"[:200]
        except Exception as exc:
            per.error = f"{type(exc).__name__}: {exc}"[:200]
            logger.error("Research benchmark error %s: %s", paper["id"], exc)
        per.latency_ms = (time.perf_counter() - start) * 1000
        total_latency += per.latency_ms
        result.per_paper.append(per)
    n = max(len(papers), 1)
    result.spec_validity_rate = total_valid / n * 100
    result.avg_sharpe = total_sharpe / max(total_valid, 1)
    result.incumbent_beat_rate = total_beat / n * 100
    result.noise_floor_beat_rate = total_above_noise / n * 100
    result.avg_latency_ms = total_latency / n
    logger.info(
        "%s: valid=%.1f%% sharpe=%.3f beat=%.1f%% noise=%.1f%%",
        model_id, result.spec_validity_rate, result.avg_sharpe,
        result.incumbent_beat_rate, result.noise_floor_beat_rate)
    return result

