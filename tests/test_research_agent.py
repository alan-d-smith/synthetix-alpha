"""
test_research_agent.py — Unit tests for the LLM-driven research agent.

Tests schema compliance, sentiment scoring integration, and LLM prompt
structure guards. All external dependencies (Finnhub, FinBERT, LLM) are
mocked so tests run offline.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.research_agent import (
    _aggregate_sentiment,
    _build_prompt,
    _parse_llm_response,
    _validate_output,
    VALID_SENTIMENTS,
    VALID_ALIGNMENTS,
)


# ============================================================
# _aggregate_sentiment tests
# ============================================================

class TestAggregateSentiment:
    def test_empty_headlines(self) -> None:
        label, avg, scored = _aggregate_sentiment([])
        assert label == "neutral"
        assert avg == 0.0
        assert scored == []

    @patch("agents.research_agent.score_headline")
    def test_all_positive(self, mock_score: object) -> None:
        mock_score.return_value = {"label": "positive", "score": 0.95}
        articles = [
            {"headline": "Great quarter", "summary": ""},
            {"headline": "Record revenue", "summary": ""},
        ]
        label, avg, scored = _aggregate_sentiment(articles)
        assert label == "bullish"
        assert avg == 0.95
        assert len(scored) == 2

    @patch("agents.research_agent.score_headline")
    def test_mixed_sentiment(self, mock_score: object) -> None:
        mock_score.side_effect = [
            {"label": "positive", "score": 0.9},
            {"label": "negative", "score": 0.8},
            {"label": "positive", "score": 0.7},
        ]
        articles = [
            {"headline": "A", "summary": ""},
            {"headline": "B", "summary": ""},
            {"headline": "C", "summary": ""},
        ]
        label, avg, scored = _aggregate_sentiment(articles)
        assert label == "bullish"
        assert avg == pytest.approx(0.8, abs=0.01)
        assert len(scored) == 3


# ============================================================
# _build_prompt tests
# ============================================================

class TestBuildPrompt:
    def test_prompt_contains_ticker(self) -> None:
        prompt = _build_prompt("AAPL", "bullish", 0.85, [], [])
        assert "AAPL" in prompt
        assert "bullish" in prompt
        assert "0.85" in prompt

    def test_prompt_contains_schema_keys(self) -> None:
        prompt = _build_prompt("AAPL", "bullish", 0.85, [], [])
        for key in ("ticker", "sentiment", "confidence_score", "thesis", "macro_alignment"):
            assert key in prompt


# ============================================================
# _parse_llm_response tests
# ============================================================

class TestParseLLMResponse:
    def test_clean_json(self) -> None:
        raw = '{"ticker": "AAPL", "sentiment": "bullish", "confidence_score": 0.8}'
        result = _parse_llm_response(raw, "AAPL")
        assert result is not None
        assert result["sentiment"] == "bullish"

    def test_markdown_json(self) -> None:
        raw = '```json\n{"ticker": "AAPL", "sentiment": "bearish"}\n```'
        result = _parse_llm_response(raw, "AAPL")
        assert result is not None
        assert result["sentiment"] == "bearish"

    def test_garbage_returns_none(self) -> None:
        raw = "I'm sorry, I cannot provide that analysis."
        result = _parse_llm_response(raw, "AAPL")
        assert result is None


# ============================================================
# _validate_output tests
# ============================================================

class TestValidateOutput:
    def test_valid_data_passes_through(self) -> None:
        result = _validate_output(
            {"ticker": "AAPL", "sentiment": "bullish", "confidence_score": 0.82,
             "thesis": "Strong buy", "macro_alignment": "aligned"},
            "AAPL",
        )
        assert result["sentiment"] == "bullish"
        assert result["confidence_score"] == 0.82

    def test_bad_sentiment_sanitized(self) -> None:
        result = _validate_output({"sentiment": "extremely_bullish"}, "AAPL")
        assert result["sentiment"] == "neutral"

    def test_confidence_clamped(self) -> None:
        result = _validate_output({"confidence_score": 1.5}, "AAPL")
        assert result["confidence_score"] == 1.0
        result = _validate_output({"confidence_score": -0.5}, "AAPL")
        assert result["confidence_score"] == 0.0

    def test_thesis_truncated(self) -> None:
        long_thesis = "x" * 1000
        result = _validate_output({"thesis": long_thesis}, "AAPL")
        assert len(result["thesis"]) <= 500

    def test_bad_macro_sanitized(self) -> None:
        result = _validate_output({"macro_alignment": "extremely_aligned"}, "AAPL")
        assert result["macro_alignment"] == "neutral"
# ============================================================
# research_tickers integration tests (mocked)
# ============================================================

class TestResearchTickers:
    @patch("agents.research_agent.call_llm")
    @patch("agents.research_agent.get_company_news")
    @patch("agents.research_agent.score_headline")
    def test_returns_list_with_schema(
        self, mock_score: object, mock_news: object, mock_llm: object
    ) -> None:
        from agents.research_agent import research_tickers

        mock_news.return_value = [
            {"headline": "Great earnings", "summary": "", "datetime": "2026-01-01", "source": "CNBC"}
        ]
        mock_score.return_value = {"label": "positive", "score": 0.9}
        mock_llm.return_value = (
            '{"ticker": "AAPL", "sentiment": "bullish", '
            '"confidence_score": 0.85, '
            '"thesis": "Strong growth ahead", '
            '"macro_alignment": "aligned"}'
        )

        results = research_tickers(["AAPL"])
        assert isinstance(results, list)
        assert len(results) == 1
        r = results[0]
        for key in ("ticker", "sentiment", "confidence_score", "thesis", "macro_alignment"):
            assert key in r
        assert r["sentiment"] in VALID_SENTIMENTS
        assert 0.0 <= r["confidence_score"] <= 1.0
        assert r["macro_alignment"] in VALID_ALIGNMENTS

    @patch("agents.research_agent.call_llm")
    @patch("agents.research_agent.get_company_news")
    @patch("agents.research_agent.score_headline")
    def test_llm_failure_returns_fallback(
        self, mock_score: object, mock_news: object, mock_llm: object
    ) -> None:
        from agents.research_agent import research_tickers

        mock_news.return_value = [{"headline": "Test", "summary": ""}]
        mock_score.return_value = {"label": "neutral", "score": 0.5}
        mock_llm.side_effect = RuntimeError("API down")

        results = research_tickers(["AAPL"])
        assert len(results) == 1
        assert results[0]["sentiment"] == "neutral"
        assert results[0]["confidence_score"] == 0.5

    @patch("agents.research_agent.call_llm")
    @patch("agents.research_agent.get_company_news")
    @patch("agents.research_agent.score_headline")
    def test_empty_tickers_returns_empty(
        self, mock_score: object, mock_news: object, mock_llm: object
    ) -> None:
        from agents.research_agent import research_tickers
        assert research_tickers([]) == []