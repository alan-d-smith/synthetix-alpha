"""Unified model benchmarking: research (Spec generation) and critic (risk evaluation)."""

from __future__ import annotations
import argparse, datetime as dt, json, logging, os, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from synthetix_alpha import config
from synthetix_alpha.pipeline.critic import ENSEMBLE_RUNS, CriticAgent, CriticDecision, CriticInput
from synthetix_alpha.pipeline.llm import LLMAPIError, LLMClient
from synthetix_alpha.pipeline.benchmark_research import (
    DEFAULT_BASE_URL as RESEARCH_DEFAULT_BASE_URL,
    INCUMBENT_SHARPE,
    NOISE_FLOOR,
    MOCK_RESEARCH_SPEC,
    RESEARCH_SYSTEM_PROMPT,
    ResearchPerPaper,
    ResearchBenchmarkResult,
    load_research_papers,
    benchmark_research,
)

logger = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_LIMIT = 15
OUTPUT = config.ROOT / "docs" / "model_benchmark_results.md"

DEFAULT_MODELS = [
    "deepseek-ai/DeepSeek-R1:featherless-ai",
    "Qwen/QwQ-32B:featherless-ai",
    "meta-llama/Llama-3.3-70B-Instruct:hf-inference",
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503:hf-inference",
    "google/gemma-3-27b-it:hf-inference",
]


# ============================================================
# RESEARCH PHASE -- Spec generation from arXiv papers
# ============================================================

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




# ============================================================
# RESEARCH PHASE ? Spec generation from arXiv papers
# ============================================================

@dataclass
class ResearchPerPaper:
    """Outcome for one paper in the research phase."""

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
    """Aggregated research metrics for one model."""

    model: str
    spec_validity_rate: float = 0.0
    avg_sharpe: float = 0.0
    incumbent_beat_rate: float = 0.0
    noise_floor_beat_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_papers: int = 0
    errors: list = field(default_factory=list)
    per_paper: list = field(default_factory=list)



@dataclass
class PerCandidateResult:
    """Outcome of the 3-run ensemble for one candidate."""

    ticker: str
    scenario: str = ""
    decisions: list = field(default_factory=list)
    parsed: int = 0
    consistent: bool = False
    final_decision: str = ""
    total_latency_ms: float = 0.0
    error: str = ""


@dataclass
class BenchmarkResult:
    """Aggregated metrics for one model."""

    model: str
    schema_compliance: float = 0.0
    avg_latency_ms: float = 0.0
    self_consistency: float = 0.0
    approval_rate: float = 0.0
    total_candidates: int = 0
    total_runs: int = 0
    errors: list = field(default_factory=list)
    per_candidate: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic test batch
# ---------------------------------------------------------------------------
def generate_test_batch(limit: int = DEFAULT_LIMIT) -> list:
    """Return a diverse set of (CriticInput, scenario_label) pairs."""
    approve_batch = []
    for ticker, sector, headlines in [
        ("SPY", "ETF", []),
        ("QQQ", "ETF", []),
        ("IWM", "ETF", []),
        ("MSFT", "Technology", ["Microsoft cloud revenue beats estimates"]),
        ("JPM", "Financial", ["JPMorgan reports strong quarter"]),
    ]:
        approve_batch.append((
            CriticInput(
                ticker=ticker, iv=0.35, hv=0.22, iv_rv=1.59, iv_rank=0.85,
                rsi=52.0, bollinger_pos=0.55, macd=0.001,
                company_name=f"{ticker} Inc.", sector=sector,
                market_cap=1_500_000_000_000, analyst_consensus=1.2,
                insider_mspr=-10.0, recent_headlines=headlines,
                yield_curve=0.15, hy_spread=3.2, nfci=-0.15,
            ),
            f"APPROVE: {ticker} (textbook)"
        ))
    reject_reg = []
    for ticker, headline in [
        ("AAPL", "SEC opens investigation into App Store practices"),
        ("GOOGL", "DOJ files antitrust lawsuit against Google"),
        ("META", "FTC probe into Meta data privacy widens"),
    ]:
        reject_reg.append((
            CriticInput(
                ticker=ticker, iv=0.40, hv=0.26, iv_rv=1.54, iv_rank=0.90,
                company_name=f"{ticker} Inc.", sector="Technology",
                market_cap=1_200_000_000_000, analyst_consensus=0.8,
                recent_headlines=[headline, f"{ticker} reports mixed earnings"],
                yield_curve=-0.05, hy_spread=3.8, nfci=0.1,
            ),
            f"REJECT: {ticker} (regulatory)"
        ))
    reject_macro = []
    for ticker in ("XLI", "CAT"):
        reject_macro.append((
            CriticInput(
                ticker=ticker, iv=0.28, hv=0.24, iv_rv=1.17, iv_rank=0.60,
                company_name=f"{ticker} Inc.", sector="Industrials",
                market_cap=200_000_000_000,
                yield_curve=-0.95, hy_spread=5.2, nfci=-0.65,
            ),
            f"REJECT: {ticker} (recession)"
        ))
    borderline_low_iv = []
    for ticker, sector in [("KO", "Consumer Defensive"), ("PG", "Consumer Defensive"), ("WMT", "Consumer Defensive")]:
        borderline_low_iv.append((
            CriticInput(
                ticker=ticker, iv=0.15, hv=0.16, iv_rv=0.94, iv_rank=0.28,
                company_name=f"{ticker} Co.", sector=sector,
                market_cap=350_000_000_000, analyst_consensus=0.5,
                yield_curve=0.20, hy_spread=3.0, nfci=-0.2,
            ),
            f"BORDERLINE: {ticker} (low IV)"
        ))
    borderline_credit = []
    for ticker in ("HYG", "LQD"):
        borderline_credit.append((
            CriticInput(
                ticker=ticker, iv=0.32, hv=0.20, iv_rv=1.60, iv_rank=0.82,
                company_name=f"{ticker} ETF", sector="Fixed Income",
                yield_curve=-0.30, hy_spread=4.8, nfci=0.5,
            ),
            f"BORDERLINE: {ticker} (credit stress)"
        ))
    batch = (approve_batch + reject_reg + reject_macro + borderline_low_iv + borderline_credit)
    return batch[:limit]


# ---------------------------------------------------------------------------
# Single-model benchmark
# ---------------------------------------------------------------------------
def benchmark_model(model_id, batch, *, base_url=None, api_key=None, mock=False, seed=42):
    """Run the full 3-run consistency evaluation on every candidate."""
    result = BenchmarkResult(model=model_id, total_candidates=len(batch), total_runs=len(batch) * ENSEMBLE_RUNS)
    logger.info("Benchmarking %s (%d x %d)", model_id, len(batch), ENSEMBLE_RUNS)
    llm = LLMClient(api_key=api_key, base_url=base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
                    model=model_id, mock=mock, seed=seed)
    critic = CriticAgent(llm=llm)
    total_latency = 0.0; total_parsed = 0; total_consistent = 0; total_approved = 0

    for inp, scenario in batch:
        per = PerCandidateResult(ticker=inp.ticker, scenario=scenario)
        start = time.perf_counter()
        try:
            decisions = []
            for run_i in range(ENSEMBLE_RUNS):
                try:
                    d = critic.evaluate(inp)
                    decisions.append(d)
                    per.parsed += 1
                except (LLMAPIError, ValueError, json.JSONDecodeError) as exc:
                    logger.debug("Run %d/%d for %s failed: %s", run_i + 1, ENSEMBLE_RUNS, inp.ticker, exc)
                    per.error = str(exc)[:200]
            per.decisions = [d.decision for d in decisions]
            per.consistent = (len(per.decisions) == ENSEMBLE_RUNS and len(set(per.decisions)) == 1)
            if per.parsed >= 2:
                approved = sum(1 for d in decisions if d.decision == "APPROVED")
                per.final_decision = "APPROVED" if approved >= 2 else "REJECTED"
            elif per.parsed == 1:
                per.final_decision = decisions[0].decision
            else:
                per.final_decision = "REJECTED"
        except Exception as exc:
            per.error = f"{type(exc).__name__}: {exc}"[:200]
            per.final_decision = "REJECTED"
            logger.error("Unhandled error benchmarking %s: %s", inp.ticker, exc)
        per.total_latency_ms = (time.perf_counter() - start) * 1000
        total_latency += per.total_latency_ms
        total_parsed += per.parsed
        if per.consistent:
            total_consistent += 1
        if per.final_decision == "APPROVED":
            total_approved += 1
        result.per_candidate.append(per)

    n = max(len(batch), 1)
    runs = n * ENSEMBLE_RUNS
    result.schema_compliance = total_parsed / max(runs, 1) * 100
    result.avg_latency_ms = total_latency / n
    result.self_consistency = total_consistent / n * 100
    result.approval_rate = total_approved / n * 100
    logger.info("%s: schema=%.1f%% lat=%.0fms cons=%.1f%% appr=%.1f%%",
                model_id, result.schema_compliance, result.avg_latency_ms,
                result.self_consistency, result.approval_rate)
    return result


# ---------------------------------------------------------------------------
# Leaderboard rendering
# ---------------------------------------------------------------------------
def render_markdown(results, base_url, seed):
    """Produce a Markdown leaderboard and per-candidate detail for the best model."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Critic Agent Model Benchmark",
        "",
        f"**Generated:** {now}",
        f"**Base URL:** `{base_url}`",
        f"**Seed:** {seed}",
        f"**Candidates per model:** {results[0].total_candidates if results else 0}",
        f"**Ensemble runs per candidate:** {ENSEMBLE_RUNS}",
        "",
        "---",
        "",
        "## Leaderboard",
        "",
        "| Rank | Model | Schema OK | Consistency | Latency (ms) | Approval % | Errors |",
        "|------|-------|-----------|-------------|-------------|------------|--------|",
    ]
    ranked = sorted(results, key=lambda r: (r.schema_compliance, r.self_consistency), reverse=True)
    for rank, r in enumerate(ranked, 1):
        star = " **" if rank == 1 else ""
        lines.append(
            f"| {rank}{star} | `{r.model}` "
            f"| {r.schema_compliance:.1f}% "
            f"| {r.self_consistency:.1f}% "
            f"| {r.avg_latency_ms:.0f} "
            f"| {r.approval_rate:.1f}% "
            f"| {len(r.errors)} |"
        )
    lines += ["", "---", "", f"## Per-Candidate Detail -- `{ranked[0].model}`", ""]
    lines += [
        "| Ticker | Scenario | Run 1 | Run 2 | Run 3 | Consistent | Final | Latency (ms) |",
        "|--------|----------|-------|-------|-------|------------|-------|-------------|",
    ]
    for pc in ranked[0].per_candidate:
        runs = pc.decisions + ["--"] * (ENSEMBLE_RUNS - len(pc.decisions))
        lines.append(
            f"| {pc.ticker} | {pc.scenario} "
            f"| {runs[0]} | {runs[1]} | {runs[2]} "
            f"| {'OK' if pc.consistent else 'NO'} "
            f"| {pc.final_decision} "
            f"| {pc.total_latency_ms:.0f} |"
        )
    lines += ["", "---", "", "## Notes", ""]
    lines += [
        "- **Schema OK**: percentage of individual runs that produced valid `CriticDecision` JSON.",
        "- **Consistency**: percentage of candidates where all 3 ensemble runs agreed on APPROVED/REJECTED.",
        "- **Approval %**: percentage of final (majority-vote) decisions that were APPROVED.",
        f"- All models run with `temperature=0.0`, `top_p=0.1`, `seed={seed}`.",
        "- The test batch is deterministic -- identical inputs for every model.",
        "",
    ]
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# Unified dual-phase leaderboard renderer
# ---------------------------------------------------------------------------
def render_unified_markdown(critic_results, research_results, base_url, seed):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Model Benchmark Report",
        "",
        f"**Generated:** {now}  |  **Base URL:** `{base_url}`  |  **Seed:** {seed}",
        "",
        "---",
        "",
        "## Generator Leaderboard (Research)",
        "",
        "| Rank | Model | Spec Validity | Avg Sharpe | Beat Incumbent | Clear Noise Floor | Avg Latency |",
        "|------|-------|--------------|------------|----------------|-------------------|-------------|",
    ]

    if research_results:
        ranked_r = sorted(research_results,
                         key=lambda r: (r.spec_validity_rate, r.incumbent_beat_rate), reverse=True)
        for rank, r in enumerate(ranked_r, 1):
            star = " **" if rank == 1 else ""
            lines.append(
                f"| {rank}{star} | `{r.model}` "
                f"| {r.spec_validity_rate:.1f}% "
                f"| {r.avg_sharpe:.3f} "
                f"| {r.incumbent_beat_rate:.1f}% "
                f"| {r.noise_floor_beat_rate:.1f}% "
                f"| {r.avg_latency_ms:.0f}ms |"
            )
        lines.append("")
        lines.append(f"### Best Generator Detail -- `{ranked_r[0].model}`")
        lines.append("")
        lines.append("| Paper | Spec Valid | Sharpe | Trades | Beats Incumbent | Clear Noise | Latency |")
        lines.append("|-------|-----------|--------|--------|-----------------|-------------|--------|")
        for pp in ranked_r[0].per_paper:
            lines.append(
                f"| {pp.paper_id} | {'Y' if pp.spec_valid else 'N'} "
                f"| {pp.mean_sharpe:.3f} "
                f"| {pp.total_trades} "
                f"| {'Y' if pp.beats_incumbent else 'N'} "
                f"| {'Y' if pp.above_noise_floor else 'N'} "
                f"| {pp.latency_ms:.0f}ms |"
            )
        lines.append("")
    else:
        lines += ["| -- | *(no research results)* | -- | -- | -- | -- | -- |", ""]

    lines += [
        "---",
        "",
        "## Evaluator Leaderboard (Critic)",
        "",
        "| Rank | Model | Schema OK | Consistency | Latency (ms) | Approval % | Errors |",
        "|------|-------|-----------|-------------|-------------|------------|--------|",
    ]

    if critic_results:
        ranked_c = sorted(critic_results,
                         key=lambda r: (r.schema_compliance, r.self_consistency), reverse=True)
        for rank, r in enumerate(ranked_c, 1):
            star = " **" if rank == 1 else ""
            lines.append(
                f"| {rank}{star} | `{r.model}` "
                f"| {r.schema_compliance:.1f}% "
                f"| {r.self_consistency:.1f}% "
                f"| {r.avg_latency_ms:.0f} "
                f"| {r.approval_rate:.1f}% "
                f"| {len(r.errors)} |"
            )
        lines.append("")
        lines.append(f"### Best Evaluator Detail -- `{ranked_c[0].model}`")
        lines.append("")
        lines.append("| Ticker | Scenario | Run 1 | Run 2 | Run 3 | Consistent | Final | Latency |")
        lines.append("|--------|----------|-------|-------|-------|------------|-------|--------|")
        for pc in ranked_c[0].per_candidate[:10]:
            runs = pc.decisions + ["--"] * (ENSEMBLE_RUNS - len(pc.decisions))
            lines.append(
                f"| {pc.ticker} | {pc.scenario} "
                f"| {runs[0]} | {runs[1]} | {runs[2]} "
                f"| {'OK' if pc.consistent else 'NO'} "
                f"| {pc.final_decision} "
                f"| {pc.total_latency_ms:.0f}ms |"
            )
        lines.append("")
    else:
        lines += ["| -- | *(no critic results)* | -- | -- | -- | -- | -- |", ""]

    lines += [
        "---",
        "",
        "## Recommendations",
        "",
    ]
    if research_results and critic_results:
        best_gen = ranked_r[0].model
        best_eval = ranked_c[0].model
        lines.append(f"- **Best Generator**: `{best_gen}` -- highest incumbent beat rate")
        lines.append(f"- **Best Evaluator**: `{best_eval}` -- best schema compliance / consistency")
        gen_scores = {r.model: r.spec_validity_rate + r.incumbent_beat_rate for r in ranked_r}
        crit_scores = {r.model: r.schema_compliance + r.self_consistency for r in ranked_c}
        all_models = set(gen_scores) & set(crit_scores)
        if all_models:
            best_overall = max(all_models, key=lambda m: gen_scores.get(m, 0) + crit_scores.get(m, 0))
            lines.append(f"- **Best Overall**: `{best_overall}` -- strongest in both phases")
    lines += ["", "---", ""]
    return "\n".join(lines)
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="Unified model benchmarking: research (Spec generation) and critic (risk evaluation)")
    p.add_argument("--mock", action="store_true", help="Use mock LLM responses (dry-run)")
    p.add_argument("--models", type=str, default=None, help="Comma-separated model list")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Number of test candidates (default: {DEFAULT_LIMIT})")
    p.add_argument("--base-url", type=str, default=None, help="API base URL")
    p.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p.add_argument("--output", type=str, default=str(OUTPUT), help="Output Markdown path")
    p.add_argument("--phase", type=str, default="both", choices=["critic", "research", "both"],
                   help="Benchmark phase: critic, research, or both (default: both)")
    p.add_argument("--research-papers", type=int, default=3, help="Number of papers for research phase (default: 3)")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable DEBUG logging")
    args = p.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    if args.models:
        model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        model_ids = DEFAULT_MODELS

    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("OPENAI_API_KEY")

    if not args.mock and not api_key:
        logger.warning("No OPENAI_API_KEY set -- falling back to mock mode.")
        args.mock = True

    batch = generate_test_batch(args.limit)
    logger.info("Test batch: %d candidates", len(batch))

    print()
    phase = args.phase
    print(f"{'='*70}")
    print(f"  MODEL BENCHMARK: {len(model_ids)} models | Phase: {phase}")
    print(f"  Base URL: {base_url}")
    print(f"  Mock: {args.mock}  Seed: {args.seed}")
    if phase in ("research", "both"):
        print(f"  Research Papers: {args.research_papers}")
    print(f"{'='*70}")
    print()

    critic_results = []
    research_results = []

    if phase in ("critic", "both"):
        batch = generate_test_batch(args.limit)
        logger.info("Critic test batch: %d candidates", len(batch))
        for i, model_id in enumerate(model_ids, 1):
            print(f"[Critic {i}/{len(model_ids)}] Benchmarking {model_id} ...")
            r = benchmark_model(model_id, batch, base_url=base_url, api_key=api_key, mock=args.mock, seed=args.seed)
            critic_results.append(r)
            print(f"         schema={r.schema_compliance:.1f}%  consistency={r.self_consistency:.1f}%  latency={r.avg_latency_ms:.0f}ms  approve={r.approval_rate:.1f}%  errors={len(r.errors)}")
            print()

    if phase in ("research", "both"):
        papers = load_research_papers(args.research_papers)
        logger.info("Research papers loaded: %d", len(papers))
        if not papers:
            logger.warning("No queued papers found; using mock fallback papers")
            papers = [
                {"id": "2501.00001", "title": "Options Implied Volatility Surface Arbitrage", "categories": ["q-fin.TR", "q-fin.PR"], "published": "2025-01-01", "status": "queued", "relevance": 0.9},
                {"id": "2501.00002", "title": "Machine Learning for Options Market Making", "categories": ["q-fin.TR", "cs.LG"], "published": "2025-01-02", "status": "queued", "relevance": 0.85},
                {"id": "2501.00003", "title": "Tail Risk Hedging with Variance Risk Premium", "categories": ["q-fin.RM", "q-fin.PR"], "published": "2025-01-03", "status": "queued", "relevance": 0.8},
            ]
        for i, model_id in enumerate(model_ids, 1):
            print(f"[Research {i}/{len(model_ids)}] Benchmarking {model_id} ...")
            r = benchmark_research(model_id, papers, base_url=base_url, api_key=api_key, mock=args.mock, seed=args.seed)
            research_results.append(r)
            print(f"         spec_valid={r.spec_validity_rate:.1f}%  sharpe={r.avg_sharpe:.3f}  beat_incumbent={r.incumbent_beat_rate:.1f}%  latency={r.avg_latency_ms:.0f}ms  errors={len(r.errors)}")
            print()

    md = render_unified_markdown(critic_results, research_results, base_url, args.seed)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    print(f"Leaderboard written to {output_path}")
    print()

    if critic_results:
        ranked = sorted(critic_results, key=lambda r: (r.schema_compliance, r.self_consistency), reverse=True)
        print("CRITIC RANK  MODEL                                             SCHEMA   CONSIST  LATENCY  APPROVE")
        print("-----------  ------------------------------------------------  -------  -------  -------  -------")
        for rank, r in enumerate(ranked, 1):
            star = " *" if rank == 1 else "  "
            print(f" {rank:3d}{star} {r.model:<48s}  {r.schema_compliance:6.1f}%  {r.self_consistency:6.1f}%  {r.avg_latency_ms:6.0f}ms  {r.approval_rate:6.1f}%")

    if research_results:
        ranked_r = sorted(research_results, key=lambda r: (r.spec_validity_rate, r.incumbent_beat_rate), reverse=True)
        print()
        print("RESEARCH RANK  MODEL                                             VALID    SHARPE   BEAT%   NOISE%")
        print("------------  ------------------------------------------------  -------  -------  -------  -------")
        for rank, r in enumerate(ranked_r, 1):
            star = " *" if rank == 1 else "  "
            print(f" {rank:4d}{star} {r.model:<48s}  {r.spec_validity_rate:6.1f}%  {r.avg_sharpe:6.3f}  {r.incumbent_beat_rate:6.1f}%  {r.noise_floor_beat_rate:6.1f}%")


if __name__ == "__main__":
    main()
