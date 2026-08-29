"""
research_agent.py — Stage 3: LLM-driven Research Agent.

Non-deterministic. Runs ONLY on tickers that passed the quant screener
(stage 2), never the full universe (cost control).

Pipeline per ticker:
    1. Fetch Finnhub news
    2. Score each headline via FinBERT (ProsusAI/finbert)
    3. Aggregate FinBERT scores → dominant label + avg confidence
    4. Build structured prompt with all raw data
    5. Call LLM (DeepSeek-V4-Pro via Featherless)
    6. Parse JSON response → fixed schema

Returns fixed schema per ticker:
    {ticker, sentiment, confidence_score (0-1), thesis, macro_alignment}
Never free-form text without this schema.
"""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from agents.llm_client import call_llm
from agents.sentiment import score_headline
from data.finnhub_client import get_company_news

# Valid enum values for schema validation
VALID_SENTIMENTS = {"bullish", "bearish", "neutral"}
VALID_ALIGNMENTS = {"aligned", "diverging", "neutral"}


def _aggregate_sentiment(
    headlines: list[dict[str, Any]],
) -> tuple[str, float, list[dict[str, Any]]]:
    """Run FinBERT on each headline and aggregate.

    Returns:
        (dominant_label, avg_confidence, scored_headlines)
    """
    if not headlines:
        return "neutral", 0.0, []

    scored = []
    label_counts: dict[str, float] = {"positive": 0, "neutral": 0, "negative": 0}

    for article in headlines:
        text = article.get("headline", "") or article.get("summary", "")
        if not text.strip():
            continue
        result = score_headline(text)
        label = result["label"]
        label_counts[label] = label_counts.get(label, 0) + 1
        scored.append({
            "headline": text,
            "finbert_label": label,
            "finbert_score": result["score"],
        })

    if not scored:
        return "neutral", 0.0, []

    dominant = max(label_counts, key=lambda k: label_counts[k])
    avg_score = sum(s["finbert_score"] for s in scored) / len(scored)
    label_map = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}
    return label_map.get(dominant, "neutral"), round(avg_score, 4), scored


def _build_prompt(
    ticker: str,
    finbert_label: str,
    finbert_avg: float,
    scored_headlines: list[dict[str, Any]],
    raw_articles: list[dict[str, Any]],
) -> str:
    """Build the LLM prompt with FinBERT scores + raw headlines."""
    headlines_text = ""
    for i, a in enumerate(raw_articles[:10]):
        hl = a.get("headline", "")
        src = a.get("source", "")
        dt = a.get("datetime", "")
        headlines_text += f"{i+1}. [{src}] {hl} ({dt})\n"

    finbert_detail = ""
    for s in scored_headlines[:10]:
        finbert_detail += (
            f"  - \"{s['headline'][:80]}...\" "
            f"→ {s['finbert_label']} ({s['finbert_score']:.2f})\n"
        )

    prompt = (
        f"Ticker: {ticker}\n\n"
        f"FinBERT Aggregated Sentiment: {finbert_label} "
        f"(average confidence: {finbert_avg:.2f})\n\n"
        f"FinBERT per-headline scores:\n{finbert_detail}\n"
        f"Raw headlines:\n{headlines_text}\n"
        "Based on the above data, output a JSON object with exactly these keys:\n"
        "  - ticker: the stock symbol\n"
        "  - sentiment: one of \"bullish\", \"bearish\", \"neutral\"\n"
        "  - confidence_score: a float between 0.0 and 1.0\n"
        "  - thesis: a 1-2 sentence summary of the investment thesis\n"
        "  - macro_alignment: one of \"aligned\", \"diverging\", \"neutral\"\n\n"
        "Output ONLY the JSON object, no markdown fences, no extra text."
    )
    return prompt


def _parse_llm_response(raw: str, ticker: str) -> dict[str, Any] | None:
    """Parse the LLM's JSON response. Falls back to regex extraction."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning(f"Failed to parse LLM response for {ticker}: {raw[:200]}")
    return None


def _validate_output(data: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Validate and sanitize the parsed output against the fixed schema."""
    sentiment = data.get("sentiment", "neutral")
    if sentiment not in VALID_SENTIMENTS:
        sentiment = "neutral"
    confidence = data.get("confidence_score", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = round(max(0.0, min(1.0, float(confidence))), 4)
    thesis = str(data.get("thesis", ""))[:500]
    macro = data.get("macro_alignment", "neutral")
    if macro not in VALID_ALIGNMENTS:
        macro = "neutral"
    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "confidence_score": confidence,
        "thesis": thesis,
        "macro_alignment": macro,
    }
def research_ticker(
    ticker: str,
    model: str = "deepseek-ai/DeepSeek-V4-Pro",
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Run the full research pipeline on a single ticker.

    Steps: Finnhub news → FinBERT scoring → LLM analysis → JSON parse.
    """
    articles = get_company_news(ticker, days_back=7)
    finbert_label, finbert_avg, scored = _aggregate_sentiment(articles)
    logger.info(
        f"{ticker}: {len(articles)} articles, FinBERT: {finbert_label} "
        f"(avg {finbert_avg:.2f})"
    )

    prompt = _build_prompt(ticker, finbert_label, finbert_avg, scored, articles)
    system = (
        "You are a quantitative research analyst. Given news headlines, "
        "FinBERT sentiment scores, and ticker information, produce a "
        "concise investment thesis. Always output valid JSON with the "
        "exact keys: ticker, sentiment, confidence_score, thesis, "
        "macro_alignment."
    )

    try:
        raw_response = call_llm(
            prompt=prompt,
            system_prompt=system,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
    except Exception as e:
        logger.error(f"LLM call failed for {ticker}: {e}")
        return _validate_output({}, ticker)

    parsed = _parse_llm_response(raw_response, ticker)
    if parsed is None:
        logger.warning(f"Using fallback for {ticker} due to parse failure")
        return _validate_output({}, ticker)

    return _validate_output(parsed, ticker)


def research_tickers(
    screened_tickers: list[str],
    llm_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run LLM-driven research on tickers that passed the quant screen.

    Args:
        screened_tickers: Tickers that passed stage 2 quant screen.
        llm_config: Optional LLM provider / model / temperature settings.

    Returns:
        List of research output dicts with schema:
            ticker, sentiment, confidence_score, thesis, macro_alignment.
    """
    cfg = llm_config or {}
    model = cfg.get("model", "deepseek-ai/DeepSeek-V4-Pro")
    temperature = cfg.get("temperature", 0.1)
    max_tokens = cfg.get("max_tokens", 1024)

    results: list[dict[str, Any]] = []
    for ticker in screened_tickers:
        try:
            result = research_ticker(
                ticker,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Research failed for {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "sentiment": "neutral",
                "confidence_score": 0.0,
                "thesis": f"Research failed: {e}",
                "macro_alignment": "neutral",
            })

    logger.info(f"Research agent: {len(results)} tickers analyzed")
    return results