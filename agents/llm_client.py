"""
llm_client.py — Featherless / DeepSeek-V4-Pro LLM client.

Featherless provides an OpenAI-compatible API at api.featherless.ai.
Uses the openai SDK with the Featherless base URL and API key.
"""
from __future__ import annotations

import os
import time

from loguru import logger
from openai import OpenAI


def _get_client() -> OpenAI:
    """Get or create an OpenAI client pointed at Featherless."""
    api_key = os.getenv("FEATHERLESS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FEATHERLESS_API_KEY not set in environment. "
            "Set it in .env and restart."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://api.featherless.ai/v1",
        timeout=60.0,
    )


def call_llm(
    prompt: str,
    system_prompt: str = "You are a quantitative research analyst.",
    temperature: float = 0.1,
    max_tokens: int = 1024,
    model: str = "deepseek-ai/DeepSeek-V4-Pro",
    retries: int = 2,
) -> str:
    """Call the LLM with a prompt and return the response text.

    Args:
        prompt: User prompt.
        system_prompt: System prompt for the LLM.
        temperature: Sampling temperature (0.0–1.0).
        max_tokens: Maximum tokens in response.
        model: Model name (default: deepseek-ai/DeepSeek-V4-Pro).
        retries: Number of retries on transient errors.

    Returns:
        Raw response text from the LLM.
    """
    client = _get_client()
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            logger.info(
                f"LLM call: model={model}, tokens={response.usage.total_tokens if response.usage else '?'}"
            )
            return content.strip()
        except Exception as e:
            last_error = e
            logger.warning(f"LLM call attempt {attempt + 1}/{retries + 1} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s

    raise RuntimeError(f"LLM call failed after {retries + 1} attempts: {last_error}")