import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.live import risk
from synthetix_alpha.live.execution import (
    already_submitted, build_order, client_order_id, find_missing_brackets, submit, track_order,
)
from synthetix_alpha.strategy.data import technicals

LEGS = [{"symbol": "SPY260930P00760000", "side": "short", "ratio": 1},
        {"symbol": "SPY260930P00740000", "side": "long", "ratio": 1}]
RULES = risk.Rules(max_single_position_pct=0.10, max_open_positions=3, max_premium_at_risk_pct=0.02)


def order(symbol="SPY", max_loss=1000.0, defined_risk=True):
    return {"symbol": symbol, "max_loss": max_loss, "defined_risk": defined_risk}


def test_rules_load_from_yaml():
    r = risk.Rules.load()
    assert r.defined_risk_only is True and 0 < r.max_premium_at_risk_pct <= 0.05 and r.max_leverage >= 1.0


def test_risk_approves_within_caps():
    d = risk.apply([order(), order("QQQ")], [], 100_000.0, RULES)
    assert len(d.approved) == 2 and not d.halted


def test_risk_blocks_undefined_and_oversized():
    d = risk.apply([order(max_loss=5_000), order("QQQ", defined_risk=False), order("IWM", 900)], [], 100_000.0, RULES)
    assert [o["symbol"] for o in d.approved] == ["IWM"]
    assert any("defined-risk" in h for h in d.halts) and any("2.0% of NAV" in h for h in d.halts)


def test_risk_halts_all_on_drawdown():
    positions = [{"symbol": "SPY", "qty": 1, "avg_entry_price": 100.0, "unrealized_pl": -21_000.0}]
    d = risk.apply([order()], positions, 100_000.0, RULES)
    assert not d.approved and "total drawdown" in d.halts[0]
    d2 = risk.apply([order()], [], 100_000.0, RULES, day_pnl=-6_000.0)
    assert not d2.approved and "daily drawdown" in d2.halts[0]


def test_risk_respects_position_slots():
    positions = [{"symbol": s, "qty": 1, "avg_entry_price": 10.0, "unrealized_pl": 0.0} for s in ("A", "B")]
    d = risk.apply([order("C", 500), order("D", 500)], positions, 100_000.0, RULES)
    assert len(d.approved) == 1 and any("no position slots" in h for h in d.halts)
    full = positions + [{"symbol": "C", "qty": 1, "avg_entry_price": 10.0, "unrealized_pl": 0.0}]
    assert not risk.apply([order("D")], full, 100_000.0, RULES).approved


def test_client_order_id_is_deterministic_and_order_independent():
    a = client_order_id(LEGS, dt.date(2026, 9, 1))
    assert a == client_order_id(list(reversed(LEGS)), dt.date(2026, 9, 1))
    assert a != client_order_id(LEGS, dt.date(2026, 9, 2))


def test_build_mleg_order():
    o = build_order(LEGS, 3, -1.85)
    assert o["order_class"] == "mleg" and o["qty"] == 3 and o["limit_price"] == 1.85
    assert [(l["side"], l["position_intent"]) for l in o["legs"]] == [
        ("sell", "sell_to_open"), ("buy", "buy_to_open")]
    single = build_order(LEGS[:1], 1, 2.0)
    assert single["order_class"] == "simple" and single["legs"][0]["symbol"] == LEGS[0]["symbol"]
    with pytest.raises(ValueError):
        build_order(LEGS * 3, 1, 1.0)
    with pytest.raises(ValueError):
        build_order([{**LEGS[0], "ratio": 2}, {**LEGS[1], "ratio": 4}], 1, 1.0)  # gcd != 1


def test_submit_is_dry_run_by_default_and_idempotent(tmp_path):
    store = tmp_path / "orders.json"
    r = submit(LEGS, 2, -1.5, store=store)
    assert r["status"] == "dry_run" and r["net"] == "credit" and not store.exists()
    track_order(r["client_order_id"], r, store)
    assert already_submitted(r["client_order_id"], store)
    assert submit(LEGS, 2, -1.5, store=store)["status"] == "duplicate"


def test_find_missing_brackets():
    pos = [{"symbol": s, "qty": 1, "unrealized_pl": 0.0, "asset_class": "us_option"} for s in ("A", "B")]
    missing = find_missing_brackets(pos, [{"symbol": "A", "legs": None}])
    assert [m["symbol"] for m in missing] == ["B"]


def test_find_missing_brackets_reads_mleg_legs():
    pos = [{"symbol": "A", "qty": 1, "asset_class": "us_option"}]
    assert find_missing_brackets(pos, [{"legs": [{"symbol": "A"}]}]) == []


def test_gs_quant_technicals():
    spot = pd.Series(range(100, 200), index=pd.bdate_range("2021-01-01", periods=100), dtype=float)
    t = technicals(spot)
    assert list(t.columns) == ["rsi", "bollinger_pos", "macd"]
    assert t["rsi"].dropna().between(0, 100).all() and t["rsi"].iloc[-1] > 90  # monotone rise -> overbought


def test_screen_filters_regime_and_universe(monkeypatch):
    import pandas as pd
    from synthetix_alpha.live import screen

    # the IV/RV gate is applied in SQL, so the fake returns only rows that already passed it
    raw = pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"], "date": ["2026-08-27"] * 3,
                        "iv": [0.6, 0.4, 0.5], "hv": [0.3, 0.3, 0.25],
                        "iv_rv": [2.0, 1.33, 2.0], "iv_rank": [0.9, 0.5, 0.8]})
    seen = {}
    def fake_query(sql, db=None):
        seen["sql"] = sql
        return raw
    monkeypatch.setattr(screen.dolt, "query", fake_query)
    u = {"min_price": 5.0, "avg_dollar_volume_floor": 5e7, "ticker_denylist": ["CCC"]}
    out = screen.scan(universe=u)
    assert list(out.index) == ["AAA", "BBB"]        # denylist drops CCC, rank orders the rest
    assert "BETWEEN 1.25 AND 2.0" in seen["sql"]    # event-risk cap is in the query
    assert list(screen.scan(universe={**u, "ticker_allowlist": ["BBB"]}).index) == ["BBB"]


def test_liquidity_floors():
    import pandas as pd
    from synthetix_alpha.live import screen

    idx = pd.to_datetime([f"2026-08-{d:02d}" for d in (24, 25, 26)], utc=True).rename("timestamp")
    bars = pd.DataFrame({"symbol": ["AAA"] * 3 + ["PENNY"] * 3,
                         "close": [100.0, 101.0, 102.0, 2.0, 2.1, 2.2],
                         "volume": [1e6, 1e6, 1e6, 1e6, 1e6, 1e6]},
                        index=idx.append(idx))

    class C:
        def stock_bars(self, *a, **k):
            return bars

    out = screen.liquidity(["AAA", "PENNY"], u={"min_price": 5.0, "avg_dollar_volume_floor": 5e7}, client=C())
    assert bool(out.loc["AAA", "liquid"]) and not bool(out.loc["PENNY", "liquid"])
