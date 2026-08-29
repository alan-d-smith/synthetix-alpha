"""
logging_config.py — Structured logging setup for synthetix-alpha.

Uses loguru for JSON-structured or colorized console output with
automatic log file rotation. Configurable via LOG_LEVEL env var.
"""
from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging(log_level: str = "INFO", log_file: str = "logs/synthetix-alpha.log") -> None:
    """Configure structured logging for the pipeline.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR.
        log_file: Path to rotating log file.
    """
    logger.remove()  # Remove default handler

    # Console: colorized, human-readable
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File: JSON-structured, rotated at 10 MB with 3 backups
    logger.add(
        log_file,
        level=log_level,
        format="{time} {level} {name} {function} {line} {message}",
        rotation="10 MB",
        retention=3,
        serialize=True,  # JSON lines
        enqueue=True,    # Non-blocking
    )

    logger.info(f"Logging configured — level={log_level}, file={log_file}")