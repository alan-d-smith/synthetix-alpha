"""
main.py — CLI entry point for the synthetix-alpha 7-stage pipeline.

Usage:
    python main.py --pipeline          # full paper-trading run
    python main.py --dry-run           # pipeline without order submission
    python main.py --screener-only     # run quant screener only
"""
from __future__ import annotations

import argparse
import sys

from loguru import logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="synthetix-alpha: autonomous risk-gated paper-trading agent"
    )
    parser.add_argument(
        "--pipeline", action="store_true",
        help="Run the full 7-stage pipeline (universe → execution)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run pipeline without submitting orders"
    )
    parser.add_argument(
        "--screener-only", action="store_true",
        help="Run only the quant screener (stage 2)"
    )
    parser.add_argument(
        "--config", type=str, default="config/settings.yaml",
        help="Path to settings YAML file"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.screener_only:
        logger.info("[main] Running quant screener only ...")
        from engine.quant_screener import screen_universe
        from data.alpaca_market_data import get_bars
        from utils.config_loader import load_universe_tickers

        tickers = load_universe_tickers()
        bars = get_bars(tickers, timeframe="15Min", limit=100)
        signals = screen_universe(bars)
        print(f"\nQuant screener: {len(signals)} signals")
        for s in signals[:10]:
            print(f"  {s['ticker']}: score={s['composite_score']:.2f} "
                  f"rsi={s['rsi']:.1f} rvol={s['rvol']:.1f}")
        return

    if args.pipeline or args.dry_run:
        from engine.pipeline import Pipeline

        pipeline = Pipeline(config_path=args.config)
        dry = args.dry_run or not args.pipeline
        pipeline.run(dry_run=dry, monitor_loop=(not dry))
        return

    print("No action specified. Use --pipeline, --dry-run, or --screener-only.")
    print("Example:  python main.py --dry-run")


if __name__ == "__main__":
    main()