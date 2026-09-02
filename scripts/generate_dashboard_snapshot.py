"""One-time generator for docs/dashboard/put_vertical_ivrv_snapshot.json.

Uses existing backtest, verify, and gate_sweep primitives. Not called by the API.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from synthetix_alpha import config
from synthetix_alpha.strategy.engine import metrics, run
from synthetix_alpha.strategy.data import EngineData
from synthetix_alpha.strategy.plots import _deployed_gate, gate_sweep
from synthetix_alpha.strategy.run import backtest
from synthetix_alpha.strategy.spec import Spec
from synthetix_alpha.strategy.verify import score, verify

SPEC_PATH = config.ROOT / "strategies" / "put_vertical_ivrv.json"
OUT_PATH = config.ROOT / "docs" / "dashboard" / "put_vertical_ivrv_snapshot.json"
TRADES_DIR = config.ROOT / "datasets" / "research" / "plot_runs"
COMPARISON_SPECS = (
    "strategies/put_diagonal_ivrv_robust.json",
    "strategies/index_condor_trend.json",
)
TRADE_PNL_BUCKETS = (
    (-float("inf"), -1000, "< −$1.0k"),
    (-1000, -500, "−$1.0k–−$0.5k"),
    (-500, 0, "−$0.5k–0"),
    (0, 500, "0–$0.5k"),
    (500, 1000, "$0.5k–$1.0k"),
    (1000, float("inf"), "> $1.0k"),
)


def _blend_equity(spec: Spec, source: str = "kaggle", equity0: float = 100_000.0) -> tuple[pd.Series, pd.DataFrame]:
    legs = []
    trades = []
    for underlying in spec.underlyings:
        data = EngineData.load(
            underlying,
            dte_max=spec.dte_max + max(leg.dte_offset for leg in spec.legs) + 1,
            source=source,
        )
        result = run(spec, data, equity0)
        legs.append(result.equity.pct_change())
        trades.append(result.trades)
    returns = pd.concat(legs, axis=1).mean(axis=1)
    curve = equity0 * (1 + returns.fillna(0.0)).cumprod()
    return curve, pd.concat(trades, ignore_index=True)


def _equity_points(curve: pd.Series) -> list[dict]:
    drawdown = curve / curve.cummax() - 1
    points = []
    for date, equity in curve.items():
        points.append(
            {
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "equity": round(float(equity), 2),
                "drawdown": round(float(drawdown.loc[date]), 6),
            }
        )
    return points


def _annual_returns(curve: pd.Series) -> list[dict]:
    yearly = curve.groupby(pd.to_datetime(curve.index).year).agg(["first", "last"])
    return [
        {"year": str(int(year)), "value": round(float(row["last"] / row["first"] - 1), 6)}
        for year, row in yearly.iterrows()
    ]


def _trade_pnl_buckets(trades: pd.DataFrame) -> list[dict]:
    if trades.empty or "pnl" not in trades.columns:
        return []
    pnl = trades["pnl"].dropna()
    out = []
    for lo, hi, label in TRADE_PNL_BUCKETS:
        count = int(((pnl > lo) & (pnl <= hi)).sum())
        out.append({"bucket": label, "count": count})
    return out


def _comparison_rows(spec_paths: tuple[str, ...]) -> list[dict]:
    rows = []
    for path in spec_paths:
        try:
            spec = Spec.load(config.ROOT / path)
            summary = backtest(spec)["summary"]
            rows.append(
                {
                    "name": spec.name,
                    "sharpe": round(summary["mean_sharpe"], 3),
                    "maxDrawdown": round(summary["worst_drawdown"], 6),
                    "trades": int(summary["total_trades"]),
                }
            )
        except Exception:
            continue
    return rows


def _gate_sweep_rows(spec: Spec) -> list[dict]:
    deployed = _deployed_gate(spec)
    rows = []
    for row in gate_sweep(spec):
        gate = row["gate"]
        label = "None" if gate is None else f"{gate:.2f}".rstrip("0").rstrip(".")
        rows.append(
            {
                "gate": label,
                "score": float(row["score"]),
                "deployed": deployed is not None and gate is not None and abs(float(gate) - float(deployed)) < 1e-6,
            }
        )
    return rows


def _fragility_rows(report: dict) -> list[dict]:
    labels = {
        "delta_short-0.05": "Short Δ −.05",
        "delta_short+0.05": "Short Δ +.05",
        "delta_long-0.05": "Long Δ −.05",
        "delta_long+0.05": "Long Δ +.05",
        "dte-10": "DTE −10",
        "dte+10": "DTE +10",
        "profit_target-0.25": "Profit target",
        "profit_target+0.25": "Profit target +",
        "stop_loss-0.25": "Stop loss",
        "stop_loss+0.25": "Stop loss +",
        "slippage+0.5": "Slippage",
    }
    rows = []
    for key, value in sorted(report.get("fragility", {}).items()):
        if not isinstance(value, (int, float)):
            continue
        rows.append({"parameter": labels.get(key, key), "score": float(value)})
    return rows


def _sample_comparisons(
    in_sample: dict,
    verify_report: dict | None,
) -> list[dict]:
    rows = [
        {
            "sample": "in_sample",
            "label": "In sample · Kaggle SPY/QQQ 2020–2022",
            "sharpe": round(float(in_sample["sharpe"]), 3),
            "maxDrawdown": round(float(in_sample["max_drawdown"]), 6),
            "trades": int(in_sample["n_trades"]),
            "detail": "Historical research after liquidity floor. Not live performance.",
        }
    ]
    if not verify_report:
        return rows

    dolt = verify_report.get("oos", {}).get("SPY@dolt")
    if isinstance(dolt, dict) and dolt.get("mean_sharpe") is not None and int(dolt.get("total_trades", 0)) > 0:
        rows.append(
            {
                "sample": "out_of_sample",
                "label": "Out of sample · Dolt SPY 2019–2026",
                "sharpe": round(float(dolt["mean_sharpe"]), 3),
                "maxDrawdown": round(float(dolt.get("worst_drawdown", 0.0)), 6),
                "trades": int(dolt.get("total_trades", 0)),
                "detail": "Independent vendor / unseen years. Expect the lower figure live.",
            }
        )

    aapl = verify_report.get("oos", {}).get("AAPL")
    if (
        isinstance(aapl, dict)
        and aapl.get("mean_sharpe") is not None
        and int(aapl.get("total_trades", 0)) > 0
        and float(aapl.get("score", -9.0)) > -9.0
    ):
        rows.append(
            {
                "sample": "out_of_sample",
                "label": "Out of sample · AAPL 2016–2023",
                "sharpe": round(float(aapl["mean_sharpe"]), 3),
                "maxDrawdown": round(float(aapl.get("worst_drawdown", 0.0)), 6),
                "trades": int(aapl.get("total_trades", 0)),
                "detail": "Unseen underlying. Not used to fit the deployed rule.",
            }
        )
    return rows


def build_snapshot() -> dict:
    spec = Spec.load(SPEC_PATH)
    TRADES_DIR.mkdir(parents=True, exist_ok=True)

    base = backtest(spec, trades_dir=TRADES_DIR)
    curve, trades = _blend_equity(spec)
    blended = metrics(curve, trades, 100_000.0)
    blended["n_trades"] = int(base["summary"]["total_trades"])

    verify_report = None
    try:
        verify_report = verify(spec, oos=("AAPL",), dolt=("SPY",), out_dir=TRADES_DIR.parent / "verify")
    except Exception:
        verify_report = None

    oos_sharpe = None
    fragility_median = None
    if verify_report:
        dolt = verify_report.get("oos", {}).get("SPY@dolt")
        if isinstance(dolt, dict):
            oos_sharpe = round(float(dolt.get("mean_sharpe", 0.0)), 3)
        summary = verify_report.get("fragility_summary") or {}
        if summary.get("median") is not None:
            fragility_median = float(summary["median"])

    deployed_gate = _deployed_gate(spec)
    comparisons = [
        {
            "name": spec.name,
            "sharpe": round(float(base["summary"]["mean_sharpe"]), 3),
            "maxDrawdown": round(float(base["summary"]["worst_drawdown"]), 6),
            "trades": int(base["summary"]["total_trades"]),
        },
        *_comparison_rows(COMPARISON_SPECS),
    ]

    profit_factor = blended.get("profit_factor", 0.0)
    if profit_factor == float("inf"):
        profit_factor = 0.0

    return {
        "name": spec.name,
        "source": "historical",
        "period": "Kaggle EOD chains · SPY + QQQ · 2020–2022",
        "sharpe": round(float(base["summary"]["mean_sharpe"]), 3),
        "maxDrawdown": round(float(base["summary"]["worst_drawdown"]), 6),
        "winRate": round(float(blended.get("win_rate", 0.0)), 4),
        "trades": int(base["summary"]["total_trades"]),
        "profitFactor": round(float(profit_factor), 3) if profit_factor else 0.0,
        "oosSharpe": oos_sharpe,
        "fragilityMedian": fragility_median,
        "equity": _equity_points(curve),
        "annualReturns": _annual_returns(curve),
        "gateSweep": _gate_sweep_rows(spec),
        "fragility": _fragility_rows(verify_report or {}),
        "comparisons": comparisons,
        "tradePnL": _trade_pnl_buckets(trades),
        "sampleComparisons": _sample_comparisons(blended, verify_report),
    }


def main() -> None:
    snapshot = build_snapshot()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    print(
        json.dumps(
            {
                "sharpe": snapshot["sharpe"],
                "maxDrawdown": snapshot["maxDrawdown"],
                "trades": snapshot["trades"],
                "equityPoints": len(snapshot["equity"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
