"""
test_alpaca_client.py — Unit tests for the Alpaca execution layer.

Tests order preview, OCO bracket construction, unique client_order_id,
and dry-run guard.
"""
from __future__ import annotations

import pytest

from execution.alpaca_client import build_bracket_payload, preview_order


def _make_order(**overrides) -> dict:
    order = {
        "ticker": "AAPL",
        "side": "buy",
        "qty": 95,
        "entry_price": 100.0,
        "take_profit_pct": 0.05,
        "stop_loss_pct": 0.03,
        "time_stop_min": 120,
        "estimated_notional": 9500.0,
        "client_order_id": "AAPL-buy-test123",
        "confidence_score": 0.82,
    }
    order.update(overrides)
    return order


class TestAlpacaClient:
    """Tests for execution/alpaca_client.py."""

    def test_preview_order_returns_string(self) -> None:
        preview = preview_order(_make_order())
        assert isinstance(preview, str)
        assert "AAPL" in preview
        assert "PAPER TRADING" in preview
        assert "BUY" in preview
        assert "95 shares" in preview or "95 share" in preview
        assert "$9,500.00" in preview
        assert "0.82" in preview
        assert "AAPL-buy-test123" in preview

    def test_submit_bracket_order_dry_run(self) -> None:
        from execution.alpaca_client import submit_bracket_order

        result = submit_bracket_order(_make_order(), dry_run=True)
        assert result is None

    def test_monitor_positions_returns_list(self) -> None:
        from execution.alpaca_client import monitor_positions

        positions = monitor_positions()
        assert isinstance(positions, list)

    def test_client_order_id_uniqueness(self) -> None:
        from utils.helpers import generate_client_order_id

        ids = {generate_client_order_id() for _ in range(100)}
        assert len(ids) == 100, "Generated IDs are not unique"

    # ---- build_bracket_payload tests ----

    def test_payload_buy_side(self) -> None:
        payload = build_bracket_payload(_make_order(side="buy", entry_price=100.0))
        assert payload["symbol"] == "AAPL"
        assert payload["qty"] == 95
        assert payload["order_class"].value == "bracket"
        assert payload["take_profit"]["limit_price"] == 105.00
        assert payload["stop_loss"]["stop_price"] == 97.00

    def test_payload_sell_side(self) -> None:
        payload = build_bracket_payload(_make_order(side="sell", entry_price=100.0))
        # Sell: TP below entry, SL above entry
        assert payload["take_profit"]["limit_price"] == 95.00
        assert payload["stop_loss"]["stop_price"] == 103.00

    def test_payload_custom_percentages(self) -> None:
        payload = build_bracket_payload(
            _make_order(entry_price=200.0, take_profit_pct=0.10, stop_loss_pct=0.02)
        )
        assert payload["take_profit"]["limit_price"] == 220.00
        assert payload["stop_loss"]["stop_price"] == 196.00

    def test_payload_carries_client_order_id(self) -> None:
        payload = build_bracket_payload(_make_order(client_order_id="my-id-001"))
        assert payload["client_order_id"] == "my-id-001"

    def test_preview_includes_tp_sl_targets(self) -> None:
        preview = preview_order(_make_order(side="buy", entry_price=150.0))
        assert "$157.50" in preview  # 150 * 1.05
        assert "$145.50" in preview  # 150 * 0.97