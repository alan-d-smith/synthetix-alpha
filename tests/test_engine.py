import datetime as dt

import pandas as pd
import pytest

from synthetix_alpha.strategy import EngineData, Spec, run
from synthetix_alpha.strategy.engine import max_loss, select

D0 = dt.date(2021, 3, 1)
EXP = dt.date(2021, 4, 16)  # 46 DTE from D0


def chain_row(date, typ, strike, mid, delta, spot):
    return {"date": date, "symbol": f"SPY{EXP:%y%m%d}{typ[0].upper()}{int(strike * 1000):08d}", "expiration": EXP, "type": typ,
            "strike": strike, "bid": mid - 0.05, "ask": mid + 0.05, "mid": mid, "iv": 0.2, "delta": delta,
            "underlying_price": spot, "dte": (EXP - date).days}


def make_data(spots):
    """Put chain at 400/390/380 whose mids decay linearly to intrinsic at expiry."""
    rows = []
    dates = [D0 + dt.timedelta(days=i) for i in range(len(spots))]
    for date, spot in zip(dates, spots):
        t = (EXP - date).days / (EXP - D0).days
        for strike, mid0, delta in ((400.0, 8.0, -0.45), (390.0, 5.0, -0.30), (380.0, 3.0, -0.16)):
            mid = max(mid0 * t, max(strike - spot, 0.0)) if t > 0 else max(strike - spot, 0.0)
            rows.append(chain_row(date, "put", strike, mid, delta, spot))
            rows.append(chain_row(date, "call", strike, 1.0, 0.5, spot))
    chains = pd.DataFrame(rows).set_index("date")
    feats = pd.DataFrame({"spot": spots, "iv_rank": [0.8] * len(spots)}, index=dates)
    return EngineData("SPY", chains, feats)


def spread():
    return Spec("put_spread", legs=[{"type": "put", "side": "short", "delta": 0.30}, {"type": "put", "side": "long", "width": -10}],
                dte_target=45, dte_min=30, dte_max=60, max_positions=1, profit_target=None, stop_loss=None, dte_exit=None, risk_fraction=0.1, commission=1.0, slippage=1.0)


def test_select_and_max_loss():
    data = make_data([410.0])
    legs = select(spread(), data.chain(D0), 410.0)
    assert [(l.strike, l.side) for l in legs] == [(390.0, -1), (380.0, 1)]
    assert max_loss(legs, entry_value=-2.0, spot=410.0) == pytest.approx(8.0)  # width 10 - credit 2


def test_credit_spread_expires_worthless():
    data = make_data([410.0] * 47)  # held through expiry, spot flat
    r = run(spread(), data, equity0=100_000)
    t = r.trades.iloc[0]
    # credit 2.00 mid, slippage 1.0 x half-spread 0.05 on each leg => 1.90 net; risk 8.10/share => floor(10000/810)=12 contracts
    assert t["contracts"] == 12 and t["entry_value"] == pytest.approx(-1.90) and t["reason"] == "expiry"
    assert t["pnl"] == pytest.approx(1.90 * 100 * 12 - 2 * 12 * 1.0 - 2 * 12 * 1.0)  # premium - entry/exit commissions
    assert r.equity.iloc[-1] == pytest.approx(100_000 + t["pnl"]) and r.metrics["n_trades"] == 1 and r.metrics["win_rate"] == 1.0


def test_stop_loss_and_signal_gate():
    spec = spread()
    spec.stop_loss = 1.0
    data = make_data([410.0, 410.0, 395.0, 380.0, 380.0])  # crash: short 390 put goes deep ITM
    r = run(spec, data)
    assert r.trades.iloc[0]["reason"] == "stop" and r.trades.iloc[0]["pnl"] < 0
    spec.signal = {"iv_rank": [0.9, None]}
    assert run(spec, data).metrics["n_trades"] == 0


def test_spec_validation_and_roundtrip(tmp_path):
    s = spread()
    s.save(tmp_path / "s.json")
    assert Spec.load(tmp_path / "s.json") == s
    with pytest.raises(ValueError):
        Spec("bad", legs=[{"type": "put", "side": "short", "delta": 0.3, "width": -5}])
    with pytest.raises(ValueError):
        Spec("bad", legs=[{"type": "put", "side": "short", "delta": 0.3}], signal={"nope": [0, 1]})


def test_min_credit_filter():
    spec = spread()
    spec.min_credit = 0.3  # credit 1.90 vs max loss 8.10 = 0.23 -> rejected
    assert run(spec, make_data([410.0] * 5)).metrics["n_trades"] == 0
    spec.min_credit = 0.2
    assert run(spec, make_data([410.0] * 5)).metrics["n_trades"] == 1


def test_days_since_shock_is_lookahead_free():
    import numpy as np
    import pandas as pd
    from synthetix_alpha.strategy.data import days_since_shock
    idx = pd.date_range("2021-01-01", periods=10, freq="D")
    spot = pd.Series([100, 100, 100, 100, 90, 91, 92, 93, 94, 95], index=idx, dtype=float)
    rv = pd.Series(0.16, index=idx)  # ~1% daily sigma, so the -10% day is a shock
    d = days_since_shock(spot, rv, k=3.0)
    assert d.iloc[4] == 0 and d.iloc[5] == 1 and d.iloc[7] == 3
    assert np.isnan(d.iloc[0])  # nothing before the first shock


def test_backtest_combo_blends_returns_not_capital(monkeypatch):
    import pandas as pd
    import synthetix_alpha.strategy.engine as eng
    import synthetix_alpha.strategy.run as runmod

    idx = pd.date_range("2021-01-01", periods=60, freq="D")
    curves = {"A": pd.Series((100_000 * 1.001 ** pd.Series(range(60))).to_numpy(), index=idx),
              "B": pd.Series((100_000 * 1.002 ** pd.Series(range(60))).to_numpy(), index=idx)}
    seen = []

    class FakeResult:
        def __init__(self, eq):
            self.equity, self.metrics = eq, {"n_trades": 10}

    def fake_run(spec, data, equity0):
        seen.append(equity0)
        return FakeResult(curves[spec.name])

    monkeypatch.setattr(eng, "run", fake_run)
    monkeypatch.setattr(runmod.EngineData, "load", staticmethod(lambda *a, **k: object()))
    a = Spec("A", legs=[{"type": "put", "side": "short", "delta": 0.3}], underlyings=["X"])
    b = Spec("B", legs=[{"type": "put", "side": "short", "delta": 0.3}], underlyings=["X"])
    out = runmod.backtest_combo([a, b], weights=[0.5, 0.5], equity0=100_000.0)
    assert seen == [100_000.0, 100_000.0]  # each sleeve keeps full capital, so contract rounding is unchanged
    assert out["summary"]["total_trades"] == 20 and out["combined"]["total_return"] > 0


def test_split_adjustment_preserves_position_value():
    """A 4:1 split must leave the position worth the same: four contracts at a quarter the strike."""
    import datetime as dt

    from synthetix_alpha.strategy.engine import OpenLeg, Position, _apply_split
    legs = [OpenLeg("AAPL201016P00435000", "put", -1, 1, 435.0, dt.date(2020, 10, 16), 11.095),
            OpenLeg("AAPL201016P00395000", "put", 1, 1, 395.0, dt.date(2020, 10, 16), 4.820)]
    pos = Position(legs=legs, contracts=1, entry_date=dt.date(2020, 8, 28),
                   entry_value=-6.275, expiration=dt.date(2020, 10, 16))
    before = pos.value() * pos.contracts
    assert _apply_split(pos, 4.0)
    assert pos.contracts == 4
    assert pos.legs[0].strike == 435.0 / 4 and pos.legs[1].strike == 395.0 / 4
    assert pos.legs[0].symbol == "AAPL201016P00108750"
    assert pos.legs[1].symbol == "AAPL201016P00098750"
    assert abs(pos.value() * pos.contracts - before) < 1e-9, "a split must not create or destroy value"
    assert abs(pos.entry_value - (-6.275 / 4)) < 1e-9, "per-share entry must scale with the strike"


def test_split_adjustment_refuses_fractional_ratios():
    """A 3:2 split cannot keep contract counts whole, so it must be declined rather than silently rounded."""
    import datetime as dt

    from synthetix_alpha.strategy.engine import OpenLeg, Position, _apply_split
    pos = Position(legs=[OpenLeg("X201016P00100000", "put", -1, 1, 100.0, dt.date(2020, 10, 16), 1.0)],
                   contracts=1, entry_date=dt.date(2020, 8, 28), entry_value=-1.0,
                   expiration=dt.date(2020, 10, 16))
    assert not _apply_split(pos, 1.5)
    assert pos.contracts == 1 and pos.legs[0].strike == 100.0


def test_engine_data_exposes_split_dates():
    from synthetix_alpha.strategy.data import EngineData
    assert EngineData._load_splits("SPY") == {}, "SPY has never split"
    aapl = EngineData._load_splits("AAPL")
    assert aapl.get(__import__("datetime").date(2020, 8, 31)) == 4.0
