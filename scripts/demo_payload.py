"""Demo script — shows exact order payload without submitting anything."""
from execution.alpaca_client import build_bracket_payload, preview_order, submit_bracket_order
import json


def show_order(label, order):
    print("=" * 60)
    print(f"  {label}")
    print("=" * 60)
    print(preview_order(order))
    payload = build_bracket_payload(order)
    display = dict(payload)
    display["side"] = str(display["side"])
    display["time_in_force"] = str(display["time_in_force"])
    display["order_class"] = str(display["order_class"])
    print("  EXACT ALPACA BRACKET PAYLOAD (JSON):")
    print(json.dumps(display, indent=4, default=str))
    print()


# BUY example
buy_order = {
    "ticker": "AAPL",
    "side": "buy",
    "qty": 95,
    "entry_price": 100.0,
    "take_profit_pct": 0.05,
    "stop_loss_pct": 0.03,
    "time_stop_min": 120,
    "estimated_notional": 9500.00,
    "client_order_id": "AAPL-buy-1693000000123",
    "confidence_score": 0.82,
}
show_order("BULLISH AAPL — BUY BRACKET", buy_order)

# SELL example
sell_order = {
    "ticker": "AAPL",
    "side": "sell",
    "qty": 50,
    "entry_price": 100.0,
    "take_profit_pct": 0.05,
    "stop_loss_pct": 0.03,
    "time_stop_min": 120,
    "estimated_notional": 5000.00,
    "client_order_id": "AAPL-sell-1693000000456",
    "confidence_score": 0.65,
}
show_order("BEARISH AAPL — SELL BRACKET", sell_order)

print("=" * 60)
print("  DRY RUN CHECK:")
print("=" * 60)
result = submit_bracket_order(buy_order, dry_run=True)
print(f"  submit_bracket_order(dry_run=True) → {result}")
print(f"  (None = NO network call was made)")
print()
print("  ✅ Ready for your approval before any real paper submission.")