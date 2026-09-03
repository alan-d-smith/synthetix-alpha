#!/usr/bin/env python3
"""Benchmark cold vs warm overview. Run: python scripts/profile_overview.py"""

from __future__ import annotations

import time

from synthetix_alpha.api.overview import build_overview
from synthetix_alpha.api.overview_service import reset_for_tests


def timed(label: str, fn) -> float:
    t0 = time.perf_counter()
    fn()
    secs = time.perf_counter() - t0
    print(f"  {secs:7.2f}s  {label}")
    return secs


def main() -> None:
    reset_for_tests()
    print("=== Cold build_overview (cache empty) ===")
    cold = timed("build_overview (cold)", lambda: build_overview())

    print("\n=== Warm build_overview (caches populated) ===")
    warm = timed("build_overview (warm #1)", lambda: build_overview())
    warm2 = timed("build_overview (warm #2)", lambda: build_overview())

    print(f"\nSummary: cold={cold:.1f}s warm1={warm:.1f}s warm2={warm2:.1f}s")


if __name__ == "__main__":
    main()
