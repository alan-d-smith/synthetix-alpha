"""Small thread-safe TTL cache for read-only dashboard adapter data."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    """In-process TTL cache with double-checked locking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if now - stored_at >= ttl:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value)

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], T]) -> T:
        cached = self.get(key, ttl)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# Shared adapter caches (read-only market / enrichment data only).
screen_cache = TTLCache()
gather_cache = TTLCache()
critique_cache = TTLCache()

# Default TTLs (seconds) for expensive read-only stages.
SCREEN_TTL = 45.0
GATHER_TTL = 45.0
CRITIQUE_TTL = 45.0
