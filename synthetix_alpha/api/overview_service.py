"""Dashboard overview prewarm — populates read-only stage TTL caches on startup."""

from __future__ import annotations

import logging
import threading

from synthetix_alpha.api.overview import build_overview

logger = logging.getLogger(__name__)


def prewarm() -> None:
    """Run one overview build to warm screen/gather/critique caches (best-effort)."""
    try:
        build_overview()
        logger.info("Overview prewarm complete")
    except Exception:
        logger.exception("Overview prewarm failed")


def start_prewarm() -> None:
    threading.Thread(target=prewarm, name="overview-prewarm", daemon=True).start()


def reset_for_tests() -> None:
    from synthetix_alpha.api.ttl_cache import critique_cache, gather_cache, screen_cache
    from synthetix_alpha.api import trade_store

    screen_cache.clear()
    gather_cache.clear()
    critique_cache.clear()
    trade_store.clear()
