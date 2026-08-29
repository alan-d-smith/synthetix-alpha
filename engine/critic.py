"""
critic.py — Stage 4: Deterministic Validation Layer.

Validates merged signals (quant screener + research agent output) against
config/governance.yaml. Rejects or flags before any sizing logic runs.
Logs every rejection reason.

This gate runs on the merged output of stages 2 and 3.
"""
from __future__ import annotations

import math
from typing import Any

from loguru import logger


# Valid enums for governance validation
VALID_SENTIMENTS = {"bullish", "bearish", "neutral"}


def validate_signals(
    merged_signals: list[dict[str, Any]],
    governance_rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate merged signals against governance rules.

    Checks:
        1. Required fields present: ticker, sentiment, confidence_score, thesis
        2. confidence_score within [0.0, 1.0]
        3. sentiment is valid enum value

    Args:
        merged_signals: List of merged signal dicts from stages 2+3.
        governance_rules: Dict loaded from config/governance.yaml.

    Returns:
        (approved_signals, rejection_reasons) tuple.
    """
    required_fields = governance_rules.get("required_fields", [
        "ticker", "sentiment", "confidence_score", "thesis",
    ])

    approved: list[dict[str, Any]] = []
    rejections: list[str] = []

    for i, signal in enumerate(merged_signals):
        ticker = signal.get("ticker", f"signal[{i}]")
        reasons: list[str] = []

        # Check required fields
        for field in required_fields:
            if field not in signal or signal[field] is None:
                reasons.append(f"missing required field '{field}'")

        # Validate confidence_score
        if "confidence_score" in signal:
            cs = signal["confidence_score"]
            if not isinstance(cs, (int, float)):
                reasons.append(f"confidence_score not numeric: {cs}")
            elif cs < 0.0 or cs > 1.0:
                reasons.append(f"confidence_score out of range [0,1]: {cs}")
            elif math.isnan(float(cs)):
                reasons.append("confidence_score is NaN")

        # Validate sentiment
        if "sentiment" in signal:
            if signal["sentiment"] not in VALID_SENTIMENTS:
                reasons.append(
                    f"invalid sentiment '{signal['sentiment']}' "
                    f"(expected bullish|bearish|neutral)"
                )

        if reasons:
            for reason in reasons:
                msg = f"REJECTED {ticker}: {reason}"
                logger.warning(msg)
                rejections.append(msg)
        else:
            approved.append(signal)

    logger.info(
        f"Critic: {len(approved)} approved, {len(rejections)} rejected "
        f"from {len(merged_signals)} signals"
    )
    return approved, rejections