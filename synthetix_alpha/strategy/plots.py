"""Performance and research figures for a spec. Rerun after any change and commit the PNGs."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from synthetix_alpha.strategy.run import backtest  # noqa: E402
from synthetix_alpha.strategy.spec import Spec  # noqa: E402
from synthetix_alpha.strategy.verify import score  # noqa: E402

SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # validated adjacent + all-pairs (light)
POS, NEG = "#2a78d6", "#e34948"  # diverging poles, gray midpoint at zero
OUT = Path("docs/img")

STYLE = {
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 9, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2, "axes.labelsize": 9,
    "axes.titlesize": 11, "axes.titleweight": "semibold", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "axes.titlepad": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-", "grid.alpha": 1.0,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "xtick.major.size": 0, "ytick.major.size": 0, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
    "legend.frameon": False, "legend.fontsize": 8.5, "legend.labelcolor": INK_2,
    "lines.linewidth": 2.0, "lines.solid_capstyle": "round",
    "figure.dpi": 130, "savefig.dpi": 190, "savefig.bbox": "tight", "savefig.pad_inches": 0.3,
}
PCT = PercentFormatter(xmax=1, decimals=0)


def _finish(ax, title, subtitle=None, pct_y=True):
    ax.set_title(title if not subtitle else f"{title}\n", loc="left")
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8.5, color=MUTED, va="bottom")
    if pct_y:
        ax.yaxis.set_major_formatter(PCT)
    ax.set_axisbelow(True)


def equity_panel(ax, curves: dict[str, pd.Series]):
    for i, (name, eq) in enumerate(curves.items()):
        r = eq / eq.iloc[0] - 1
        ax.plot(r.index, r.values, color=SERIES[i % len(SERIES)], label=name, zorder=3)
        ax.annotate(f" {name} {r.iloc[-1]:+.1%}", (r.index[-1], r.iloc[-1]), color=SERIES[i % len(SERIES)],
                    fontsize=8.5, fontweight="semibold", va="center", zorder=4)
    ax.axhline(0, color=AXIS, lw=0.8, zorder=1)
    ax.margins(x=0.16)
    _finish(ax, "Cumulative return", "each underlying traded on its own $100k")
    ax.legend(loc="upper left", ncols=len(curves))


def drawdown_panel(ax, curves: dict[str, pd.Series]):
    worst = 0.0
    for i, (name, eq) in enumerate(curves.items()):
        dd = eq / eq.cummax() - 1
        worst = min(worst, dd.min())
        ax.fill_between(dd.index, dd.values, 0, color=SERIES[i % len(SERIES)], alpha=0.16, lw=0, zorder=2)
        ax.plot(dd.index, dd.values, color=SERIES[i % len(SERIES)], lw=1.4, label=name, zorder=3)
    ax.axhline(0, color=AXIS, lw=0.8, zorder=1)
    _finish(ax, "Drawdown", f"worst {worst:.1%}", pct_y=False)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=1))
    ax.margins(y=0.12)
    ax.legend(loc="lower left", ncols=len(curves))


def yearly_panel(ax, results: dict[str, dict]):
    years = sorted({y for m in results.values() for y in m["yearly"]})
    names = list(results)
    width = 0.8 / max(len(names), 1)
    for i, name in enumerate(names):
        vals = [results[name]["yearly"].get(y, np.nan) for y in years]
        x = np.arange(len(years)) + (i - (len(names) - 1) / 2) * width
        ax.bar(x, vals, width * 0.88, color=[POS if (v or 0) >= 0 else NEG for v in vals],
               label=name, zorder=3, linewidth=0)
        for xi, v in zip(x, vals):
            if v is None or np.isnan(v):
                continue
            ax.annotate(f"{v:+.1%}", (xi, v), ha="center", va="bottom" if v >= 0 else "top",
                        fontsize=7, color=INK_2, xytext=(0, 3 if v >= 0 else -3), textcoords="offset points")
            if len(names) > 1:  # colour carries sign, so name each bar explicitly
                ax.annotate(name, (xi, 0), ha="center", va="top", fontsize=7, color=MUTED,
                            xytext=(0, -4), textcoords="offset points", annotation_clip=False)
    ax.set_xticks(np.arange(len(years)), [str(y) for y in years])
    ax.tick_params(axis="x", pad=14 if len(names) > 1 else 3)
    ax.axhline(0, color=AXIS, lw=0.8, zorder=4)
    ax.margins(y=0.22)
    _finish(ax, "Return by year", "blue = positive, red = negative")


def trades_panel(ax, trades: pd.DataFrame):
    pnl = trades["pnl"].dropna()
    pad = (pnl.max() - pnl.min()) * 0.04 or 1.0
    bins = np.linspace(pnl.min() - pad, pnl.max() + pad, 41)
    ax.hist(pnl[pnl >= 0], bins=bins, color=POS, zorder=3, linewidth=0)
    ax.hist(pnl[pnl < 0], bins=bins, color=NEG, zorder=3, linewidth=0)
    ax.axvline(0, color=AXIS, lw=0.8, zorder=4)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(axis="x", visible=False)
    win = (pnl > 0).mean()
    _finish(ax, "Trade P&L", f"{len(pnl)} trades · {win:.0%} winners · median ${pnl.median():,.0f}", pct_y=False)
    ax.set_ylabel("trades")


def gate_panel(ax, sweep: list[dict], deployed: float | None):
    gates = ["none" if r["gate"] is None else f"{r['gate']:.2f}" for r in sweep]
    vals = [r["score"] for r in sweep]
    on = [deployed is not None and r["gate"] is not None and abs(r["gate"] - deployed) < 1e-9 for r in sweep]
    ax.bar(gates, vals, 0.62, color=[SERIES[0] if o else "#c9d6e8" for o in on], zorder=3, linewidth=0)
    for x, (v, o) in enumerate(zip(vals, on)):
        ax.annotate(f"{v:+.2f}", (x, v), ha="center", va="bottom" if v >= 0 else "top", fontsize=7.5,
                    fontweight="semibold" if o else "normal", color=INK if o else INK_2,
                    xytext=(0, 3 if v >= 0 else -3), textcoords="offset points")
    ax.axhline(0, color=AXIS, lw=0.8, zorder=4)
    ax.margins(y=0.2)
    _finish(ax, "The gate is the edge", "selection score vs minimum IV/RV to enter; deployed value highlighted", pct_y=False)
    ax.set_xlabel("IV / RV entry gate")


def fragility_panel(ax, fragility: dict, base: float):
    items = sorted(((k, v) for k, v in fragility.items() if isinstance(v, (int, float))), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    vals = [max(v, -1.0) for _, v in items]  # clip the -9 "too few trades" sentinel
    ax.barh(labels, vals, 0.62, color=[NEG if v < 0.5 * base else SERIES[0] for v in vals], zorder=3, linewidth=0)
    ax.axvline(base, color=INK_2, lw=1.2, zorder=4)
    ax.annotate(f"base {base:.2f}", (base, len(labels) - 0.35), color=INK_2, fontsize=8,
                xytext=(-2, 0), textcoords="offset points", va="center", ha="right", fontweight="semibold")
    ax.axvline(0.5 * base, color=MUTED, lw=1.0, zorder=4)
    ax.annotate("half base", (0.5 * base, -0.45), color=MUTED, fontsize=7.5, ha="center",
                xytext=(0, -2), textcoords="offset points", va="top", annotation_clip=False)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    med = float(np.median(vals))
    _finish(ax, "Parameter fragility", f"score under one-at-a-time perturbation · median {med:.2f}", pct_y=False)
    ax.set_xlabel("selection score (clipped at −1)")


def gate_sweep(spec: Spec, gates=(None, 1.0, 1.1, 1.15, 1.2, 1.25, 1.3)) -> list[dict]:
    deployed = _deployed_gate(spec)
    levels = sorted({g for g in gates if g is not None} | ({deployed} if deployed else set()))
    out = []
    for g in [None, *levels]:
        s = copy.deepcopy(spec)
        s.name = f"{spec.name}__gate{g}"
        s.signal = {k: v for k, v in s.signal.items() if k != "iv_rv_ratio"}
        if g is not None:
            s.signal["iv_rv_ratio"] = [g, None]
        sm = backtest(s)["summary"]
        out.append({"gate": g, "score": round(score(sm), 3), "trades": sm["total_trades"]})
    return out


def build(spec: Spec, out_dir: Path = OUT, sweep: bool = True, verify_json: Path | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path("datasets/research/plot_runs")
    res = backtest(spec, trades_dir=tmp)
    curves, trades = {}, []
    for u in res["results"]:
        eq = pd.read_csv(tmp / f"{spec.name}_{u}_kaggle_equity.csv", index_col=0, parse_dates=[0]).squeeze("columns")
        curves[u] = eq
        trades.append(pd.read_csv(tmp / f"{spec.name}_{u}_kaggle.csv"))
    trades = pd.concat(trades, ignore_index=True)
    written = []

    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.6))
        fig.suptitle(f"{spec.name} — {', '.join(res['results'])}", x=0.007, ha="left", fontsize=13,
                     fontweight="bold", color=INK)
        s = res["summary"]
        fig.text(0.007, 0.945, f"mean Sharpe {s['mean_sharpe']:.2f} · worst year {s['worst_year']:+.1%} · "
                               f"max drawdown {s['worst_drawdown']:.1%} · {s['total_trades']} trades",
                 ha="left", fontsize=9, color=MUTED)
        equity_panel(axes[0, 0], curves)
        drawdown_panel(axes[0, 1], curves)
        yearly_panel(axes[1, 0], res["results"])
        trades_panel(axes[1, 1], trades)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        p = out_dir / f"{spec.name}_performance.png"
        fig.savefig(p)
        plt.close(fig)
        written.append(p)

        panels = []
        if sweep:
            panels.append(("gate", gate_sweep(spec)))
        if verify_json and Path(verify_json).exists():
            v = json.loads(Path(verify_json).read_text())
            panels.append(("fragility", (v["fragility"], v["base_score"])))
        if panels:
            fig, axes = plt.subplots(1, len(panels), figsize=(6.2 * len(panels), 4.6))
            axes = np.atleast_1d(axes)
            for ax, (kind, data) in zip(axes, panels):
                gate_panel(ax, data, _deployed_gate(spec)) if kind == "gate" else fragility_panel(ax, *data)
            fig.tight_layout()
            p = out_dir / f"{spec.name}_research.png"
            fig.savefig(p)
            plt.close(fig)
            written.append(p)
    return written


def _deployed_gate(spec: Spec) -> float | None:
    r = spec.signal.get("iv_rv_ratio")
    return r[0] if r else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--verify", help="verify.py JSON, adds the fragility panel")
    ap.add_argument("--no-sweep", action="store_true")
    a = ap.parse_args()
    for p in build(Spec.load(a.spec), Path(a.out), not a.no_sweep, a.verify):
        print(p)


if __name__ == "__main__":
    main()
