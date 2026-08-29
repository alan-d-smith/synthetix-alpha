"""
pipeline.py — Full 7-stage orchestrator.

No stage may be skipped or short-circuited. Every transition is logged.
Includes a 15-minute position monitor loop after the initial run.
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from agents.research_agent import research_tickers
from data.alpaca_market_data import get_bars, get_snapshots
from engine.critic import validate_signals
from engine.risk_guard import apply_risk_controls
from engine.sizing import compute_sizes
from engine.quant_screener import screen_universe
from execution.alpaca_client import (
    monitor_positions,
    preview_order,
    submit_bracket_order,
    _get_client,
)
from utils.config_loader import (
    load_governance_rules,
    load_settings,
    load_universe_tickers,
)


class Pipeline:
    """Orchestrates all 7 stages with structured logging at every transition."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path
        self.settings = load_settings()
        self.governance = load_governance_rules()
        self.tickers = load_universe_tickers()
        self.poll_interval = self.settings.get(
            "position_poll_interval_min", 15
        ) * 60

    # Stage 1 -----------------------------------------------------------

    def stage1_load_context(self) -> dict[str, Any]:
        account = self._get_account_safe()
        logger.info(
            "[PIPELINE] Stage 1: Universe={} tickers, NAV=${:,.0f}, {} positions",
            len(self.tickers), account["nav"], len(account["positions"]),
        )
        return account

    # Stage 2 -----------------------------------------------------------

    def stage2_quant_screen(self) -> list[dict[str, Any]]:
        logger.info(
            "[PIPELINE] Stage 2: Fetching 15-min bars for {} tickers ...",
            len(self.tickers),
        )
        try:
            ticker_bars = get_bars(self.tickers, timeframe="15Min", limit=100)
        except Exception as e:
            logger.error(f"[PIPELINE] Stage 2 FAILED: {e}")
            return []
        signals = screen_universe(ticker_bars)
        logger.info(
            "[PIPELINE] Stage 2→3: {} signals from {} tickers",
            len(signals), len(self.tickers),
        )
        return signals

    # Stage 3 -----------------------------------------------------------

    def stage3_research(
        self, quant_signals: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not quant_signals:
            logger.info("[PIPELINE] Stage 3: No quant passes — skipping")
            return []
        screened = [s["ticker"] for s in quant_signals]
        llm_cfg = self.settings.get("llm", {})
        logger.info("[PIPELINE] Stage 3: Research on {} tickers ...", len(screened))
        results = research_tickers(screened, llm_config=llm_cfg)
        logger.info(
            "[PIPELINE] Stage 3→4: {} research outputs from {} tickers",
            len(results), len(screened),
        )
        return results

    # Stage 4 -----------------------------------------------------------

    def stage4_critic(
        self,
        quant_signals: list[dict[str, Any]],
        research_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = self._merge_signals(quant_signals, research_outputs)
        logger.info(
            "[PIPELINE] Stage 4: Merged {} quant + {} research → {} signals",
            len(quant_signals), len(research_outputs), len(merged),
        )
        approved, rejections = validate_signals(merged, self.governance)
        for r in rejections:
            logger.warning(f"[PIPELINE] Stage 4 REJECTED: {r}")
        logger.info(
            "[PIPELINE] Stage 4→5: {} approved, {} rejected",
            len(approved), len(rejections),
        )
        return approved

    # Stage 5 -----------------------------------------------------------

    def stage5_sizing(
        self,
        approved_signals: list[dict[str, Any]],
        account_nav: float,
    ) -> list[dict[str, Any]]:
        if not approved_signals:
            logger.info("[PIPELINE] Stage 5: No approved signals — skipping")
            return []
        approved = self._enrich_with_prices(approved_signals)
        sizing_rules = {
            "max_single_position_pct": self.governance.get("max_single_position_pct", 0.10),
            "take_profit_pct": self.governance.get("take_profit_pct", 0.05),
            "stop_loss_pct": self.governance.get("stop_loss_pct", 0.03),
            "time_stop_min": self.governance.get("time_stop_min", 120),
        }
        orders = []
        for signal in approved:
            ref_price = signal.get("entry_price", 100.0)
            rules = dict(sizing_rules)
            rules["reference_price"] = ref_price
            result = compute_sizes([signal], account_nav, rules)
            orders.extend(result)
        logger.info(
            "[PIPELINE] Stage 5→6: {} bracket orders (NAV=${:,.0f})",
            len(orders), account_nav,
        )
        return orders

    # Stage 6 -----------------------------------------------------------

    def stage6_risk_guard(
        self,
        sized_orders: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        account_nav: float,
    ) -> list[dict[str, Any]]:
        if not sized_orders:
            logger.info("[PIPELINE] Stage 6: No orders — skipping")
            return []
        final, halts = apply_risk_controls(
            sized_orders, positions, account_nav, self.governance
        )
        for h in halts:
            logger.warning(f"[PIPELINE] Stage 6 HALT: {h}")
        logger.info(
            "[PIPELINE] Stage 6→7: {} passed, {} halted from {} orders",
            len(final), len(halts), len(sized_orders),
        )
        return final

    # Stage 7 -----------------------------------------------------------

    def stage7_execute(
        self,
        final_orders: list[dict[str, Any]],
        dry_run: bool = True,
    ) -> list[dict[str, Any]]:
        if not final_orders:
            logger.info("[PIPELINE] Stage 7: No orders to execute")
            return []
        results: list[dict[str, Any]] = []
        for i, order in enumerate(final_orders):
            logger.info(
                "[PIPELINE] Stage 7: Order {}/{} — {} {} x{} (${:,.0f} notional)",
                i + 1, len(final_orders),
                order["ticker"], order["side"].upper(), order["qty"],
                order.get("estimated_notional", 0),
            )
            print(preview_order(order))
            result = submit_bracket_order(order, dry_run=dry_run)
            if result:
                logger.success(
                    "[PIPELINE] Order SUBMITTED: id={} status={}",
                    result.get("id", "?"), result.get("status", "?"),
                )
                results.append(result)
            else:
                logger.info("[PIPELINE] Order PREVIEWED (dry run — not submitted)")
        logger.info("[PIPELINE] Stage 7: {} orders processed", len(final_orders))
        return results

    # Full run ----------------------------------------------------------

    def run(self, dry_run: bool = True, monitor_loop: bool = True) -> dict[str, Any]:
        logger.info("=" * 70)
        logger.info("  SYNTHETIX-ALPHA PIPELINE  |  {} ", "DRY RUN" if dry_run else "PAPER TRADING")
        logger.info("=" * 70)

        account = self.stage1_load_context()
        nav = account["nav"]
        positions = account["positions"]

        quant_signals = self.stage2_quant_screen()
        research_outputs = self.stage3_research(quant_signals)
        approved = self.stage4_critic(quant_signals, research_outputs)
        sized = self.stage5_sizing(approved, nav)
        final_orders = self.stage6_risk_guard(sized, positions, nav)
        execution_results = self.stage7_execute(final_orders, dry_run=dry_run)

        summary = {
            "nav": nav,
            "positions_before": len(positions),
            "tickers_screened": len(self.tickers),
            "quant_signals": len(quant_signals),
            "research_outputs": len(research_outputs),
            "approved_signals": len(approved),
            "sized_orders": len(sized),
            "final_orders": len(final_orders),
            "orders_submitted": len(execution_results),
        }
        logger.info("=" * 70)
        logger.info("  PIPELINE COMPLETE — {}", summary)
        logger.info("=" * 70)

        if monitor_loop and not dry_run:
            self._monitor_loop()
        return summary

    # Helpers -----------------------------------------------------------

    @staticmethod
    def _get_account_safe() -> dict[str, Any]:
        try:
            client = _get_client()
            acct = client.get_account()
            nav = float(acct.equity)
            raw = client.get_all_positions()
            positions = []
            for p in raw:
                positions.append({
                    "ticker": p.symbol,
                    "qty": int(float(p.qty)),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price or 0),
                    "unrealized_pl": float(p.unrealized_pl or 0),
                    "unrealized_pl_pct": float(p.unrealized_plpc or 0),
                })
            return {"nav": nav, "positions": positions}
        except Exception as e:
            logger.warning(f"[PIPELINE] Account fetch failed: {e} — using defaults")
            return {"nav": 100_000.0, "positions": []}

    @staticmethod
    def _merge_signals(
        quant_signals: list[dict[str, Any]],
        research_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        research_by_ticker = {r["ticker"]: r for r in research_outputs}
        merged = []
        for qs in quant_signals:
            ticker = qs["ticker"]
            ro = research_by_ticker.get(ticker, {})
            merged.append({
                "ticker": ticker,
                "sentiment": ro.get("sentiment", "neutral"),
                "confidence_score": ro.get("confidence_score", 0.0),
                "thesis": ro.get("thesis", ""),
                "macro_alignment": ro.get("macro_alignment", "neutral"),
                "vwap_deviation": qs.get("vwap_deviation", 0),
                "rvol": qs.get("rvol", 1.0),
                "rsi": qs.get("rsi", 50.0),
                "composite_score": qs.get("composite_score", 0),
            })
        return merged

    @staticmethod
    def _enrich_with_prices(
        signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tickers = [s["ticker"] for s in signals]
        try:
            snapshots = get_snapshots(tickers)
        except Exception as e:
            logger.warning(f"[PIPELINE] Snapshot fetch failed: {e} — using $100 default")
            snapshots = {}
        enriched = []
        for s in signals:
            ticker = s["ticker"]
            price = 100.0
            snap = snapshots.get(ticker, {})
            daily = snap.get("latest_daily_bar", {}) or {}
            minute = snap.get("latest_minute_bar", {}) or {}
            if daily.get("close"):
                price = float(daily["close"])
            elif minute.get("close"):
                price = float(minute["close"])
            s = dict(s)
            s["entry_price"] = price
            enriched.append(s)
        return enriched

    def _monitor_loop(self) -> None:
        iteration = 0
        logger.info(
            "[PIPELINE] Monitor loop started — polling every {} min",
            self.poll_interval // 60,
        )
        try:
            while True:
                iteration += 1
                time.sleep(self.poll_interval)
                positions = monitor_positions()
                if not positions:
                    logger.info("[PIPELINE] Monitor: 0 positions")
                    continue
                total_pl = sum(p.get("unrealized_pl", 0) for p in positions)
                logger.info(
                    "[PIPELINE] Monitor itr={}: {} positions | P&L: ${:,.2f}",
                    iteration, len(positions), total_pl,
                )
                for p in positions:
                    logger.info(
                        "  {}: {} sh @ ${:.2f} | P&L: ${:,.2f} ({:.2%})",
                        p["ticker"], p["qty"], p["current_price"],
                        p["unrealized_pl"], p["unrealized_pl_pct"],
                    )
        except KeyboardInterrupt:
            logger.info("[PIPELINE] Monitor loop stopped by user")