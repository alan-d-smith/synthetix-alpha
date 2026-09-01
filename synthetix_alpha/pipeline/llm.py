"""LLM client with structured output, retry, and mock mode for CI/testing."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_MAX_RETRIES: int = 3
_BACKOFF_BASE: float = 2.0


class LLMAPIError(Exception):
    """Raised when an LLM API call fails after all retries are exhausted."""


class LLMClient:
    """OpenAI-compatible LLM client with structured output and mock fallback.

    Parameters
    ----------
    api_key : str or None
        OpenAI API key.  Falls back to ``OPENAI_API_KEY`` env var.
    base_url : str or None
        Optional custom endpoint.  Falls back to ``OPENAI_BASE_URL``.
    model : str or None
        Model name.  Falls back to ``OPENAI_MODEL`` or ``gpt-4o-mini``.
    mock : bool
        If ``True``, bypass the API and return deterministic structured
        output.  Also auto-enabled when no API key is available.
    seed : int
        Fixed random seed passed to the API for reproducible outputs.
        Defaults to 42.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        mock: bool = False,
        seed: int = 42,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._model = model or os.environ.get("OPENAI_MODEL")
        self._mock = mock or not self._api_key
        self._seed = seed
        self._client: object = None
        if self._mock:
            logger.debug("LLMClient running in mock mode (seed=%d)", self._seed)
    def _openai(self) -> object:
        if self._client is None:
            from openai import OpenAI
            kw: dict = {"api_key": self._api_key or "mock-key"}
            if self._base_url:
                kw["base_url"] = self._base_url
            self._client = OpenAI(**kw)
        return self._client

    def _retry_loop(self, fn, *args, **kwargs) -> str:
        last_exc = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                cls = type(exc).__name__
                from openai import APIError, APITimeoutError, RateLimitError
                retryable = (
                    isinstance(exc, (RateLimitError, APITimeoutError))
                    or (isinstance(exc, APIError) and
                        getattr(exc, "status_code", 0) and
                        exc.status_code >= 500)
                )
                if not retryable or attempt == _MAX_RETRIES:
                    raise LLMAPIError(
                        f"LLM call failed after {attempt+1} attempts: "
                        f"{cls}: {exc}"
                    ) from exc
                delay = _BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "LLM %s - retrying in %ds (%d/%d)",
                    cls, delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(delay)
        raise LLMAPIError("unreachable") from last_exc
    def complete(self, system_prompt, user_prompt, *, temperature=0.0):
        if self._mock:
            return f"MOCK: system={system_prompt[:80]}... user={user_prompt[:80]}..."
        if self._model is None: raise ValueError("No model specified. Pass model= to LLMClient, set OPENAI_MODEL in .env, or set OPENAI_BASE_URL.")
        def _call():
            c = self._openai()
            r = c.chat.completions.create(
                model=self._model,
                temperature=0.0,
                top_p=0.1,
                seed=self._seed,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return r.choices[0].message.content or ""
        return self._retry_loop(_call)

    def complete_structured(self, system_prompt, user_prompt, schema, *, temperature=0.0):
        if self._mock:
            return self._mock_structured(schema)
        aug = (f"{system_prompt}\n\nYou MUST respond with ONLY a valid JSON "
               "object. Do not include markdown fences, explanations, or any "
               "text outside the JSON object.")
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = self.complete(aug, user_prompt, temperature=0.0)
                return schema.model_validate_json(self._strip_json(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt == _MAX_RETRIES:
                    raise LLMAPIError(
                        f"Failed to parse structured output after "
                        f"{attempt+1} attempts: {exc}"
                    ) from exc
                logger.warning(
                    "LLM JSON parse error - retrying (%d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                user_prompt = (
                    f"{user_prompt}\n\nYour last response could not be parsed "
                    f"as JSON. Error: {exc}. Please respond with ONLY a valid "
                    f"JSON object, no markdown fences."
                )
        raise LLMAPIError("unreachable")

    @staticmethod
    def _strip_json(text):
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[-1] if "\n" in t else ""
            if t.endswith("```"):
                t = t[:-3]
        return t.strip()

    @staticmethod
    def _mock_structured(schema):
        kw = {}
        for name, field in schema.model_fields.items():
            ftype = field.annotation
            origin = getattr(ftype, "__origin__", None)
            args = getattr(ftype, "__args__", ()) if origin else ()

            # Extract ge/le from metadata
            lo, hi = 1, 100
            for m in field.metadata:
                if hasattr(m, "ge"):
                    lo = m.ge
                if hasattr(m, "le"):
                    hi = m.le

            if origin and "Literal" in str(origin):
                kw[name] = args[0] if args else "MOCK"
            elif ftype is int or (origin is int):
                kw[name] = (lo + hi) // 2
            elif ftype is float or (origin is float):
                flo = 0.5
                fhi = 1.0
                for m in field.metadata:
                    if hasattr(m, "ge"):
                        flo = m.ge
                    if hasattr(m, "le"):
                        fhi = m.le
                kw[name] = round((flo + fhi) / 2, 2)
            elif ftype is str or (origin is str):
                kw[name] = f"MOCK: {name}"
            elif origin is list:
                kw[name] = [f"MOCK: {name}[0]"]
            elif ftype is bool:
                kw[name] = True
            elif field.default is not None:
                kw[name] = field.default
            else:
                kw[name] = None
        return schema(**kw)
