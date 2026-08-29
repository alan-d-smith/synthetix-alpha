"""
sentiment.py — Local FinBERT Sentiment Classifier.

Primary:    ProsusAI/finbert         (headlines / short text)
Secondary:  yiyanghkust/finbert-tone  (filings / earnings-call text)

Scores text locally via HuggingFace transformers pipeline before feeding
numeric feature + label into the LLM agent's prompt. Never ask the LLM
to derive sentiment purely from raw text alone.

Lazy-loads pipelines as module-level singletons to avoid repeated
downloads and memory overhead.
"""
from __future__ import annotations

import os
from typing import Any

import torch
from loguru import logger
from transformers import pipeline

# Prevent multiprocessing deadlocks on Windows
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Module-level singletons — lazy-loaded on first call
_headline_pipeline: Any = None
_filing_pipeline: Any = None


def _get_headline_pipeline() -> Any:
    """Lazy-load ProsusAI/finbert for headline sentiment."""
    global _headline_pipeline
    if _headline_pipeline is None:
        logger.info("Loading ProsusAI/finbert pipeline ...")
        device = 0 if torch.cuda.is_available() else -1
        _headline_pipeline = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            device=device,
            truncation=True,
            max_length=512,
        )
        logger.info("ProsusAI/finbert loaded")
    return _headline_pipeline


def _get_filing_pipeline() -> Any:
    """Lazy-load yiyanghkust/finbert-tone for filings/earnings."""
    global _filing_pipeline
    if _filing_pipeline is None:
        logger.info("Loading yiyanghkust/finbert-tone pipeline ...")
        device = 0 if torch.cuda.is_available() else -1
        _filing_pipeline = pipeline(
            "sentiment-analysis",
            model="yiyanghkust/finbert-tone",
            tokenizer="yiyanghkust/finbert-tone",
            device=device,
            truncation=True,
            max_length=512,
        )
        logger.info("yiyanghkust/finbert-tone loaded")
    return _filing_pipeline


def score_headline(text: str) -> dict[str, Any]:
    """Score a short headline using ProsusAI/finbert.

    Args:
        text: Headline or short text string.

    Returns:
        Dict with {'label': 'positive'|'neutral'|'negative', 'score': float}.
    """
    if not text or not text.strip():
        return {"label": "neutral", "score": 0.0}

    try:
        pipe = _get_headline_pipeline()
        result = pipe(text[:512])[0]
        return {
            "label": result["label"].lower(),
            "score": round(float(result["score"]), 4),
        }
    except Exception as e:
        logger.warning(f"FinBERT headline scoring failed: {e}")
        return {"label": "neutral", "score": 0.0}


def score_filing(text: str) -> dict[str, Any]:
    """Score longer-form text (filings / earnings) using finbert-tone.

    Args:
        text: Filing or earnings-call text.

    Returns:
        Dict with {'label': 'positive'|'neutral'|'negative', 'score': float}.
    """
    if not text or not text.strip():
        return {"label": "neutral", "score": 0.0}

    try:
        pipe = _get_filing_pipeline()
        result = pipe(text[:512])[0]
        return {
            "label": result["label"].lower(),
            "score": round(float(result["score"]), 4),
        }
    except Exception as e:
        logger.warning(f"FinBERT-tone filing scoring failed: {e}")
        return {"label": "neutral", "score": 0.0}