"""Performance and fills figures for a spec. Rerun after any change and commit the PNGs."""

from __future__ import annotations

import argparse
import copy
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
WIN, LOSS = "#1baf7a", "#e34948"  # fill outcome markers, distinct from the series lines
# Underlying lines in the fills figure. Green and red are reserved there for trade outcome, so these
# five avoid both hues. Validated against the light surface: all pairs clear CVD and normal-vision
# separation, worst adjacent dE 14.4 (deutan). Never cycled: more underlyings than slots is refused.
SERIES_FILLS = ["#2a78d6", "#eb6834", "#7b52ab", "#00a3b4", "#a8761f"]
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


def equity_panel(ax, curves: dict[str, pd.Series], palette: list[str] | None = None):
    palette = palette or SERIES
    for i, (name, eq) in enumerate(curves.items()):
        r = eq / eq.iloc[0] - 1
        ax.plot(r.index, r.values, color=palette[i % len(palette)], label=name, zorder=3)
        ax.annotate(f" {name} {r.iloc[-1]:+.1%}", (r.index[-1], r.iloc[-1]), color=palette[i % len(palette)],
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


def _dates(idx) -> pd.DatetimeIndex:
    return pd.to_datetime(pd.Series(list(idx)))


def fills_panel(ax, series: dict[str, pd.Series], trades: dict[str, pd.DataFrame], normalise: bool) -> None:
    """Underlying price with an entry marker per trade and an exit marker coloured by outcome."""
    if len(series) > len(SERIES_FILLS):
        raise ValueError(f"{len(series)} underlyings but only {len(SERIES_FILLS)} distinct hues; "
                         "cycling would make two of them identical")
    for i, (name, spot) in enumerate(series.items()):
        colour = SERIES_FILLS[i]
        y = spot / spot.iloc[0] * 100 if normalise else spot
        ax.plot(_dates(y.index), y.values, color=colour, linewidth=1.6, zorder=2,
                label=f"{name} (rebased)" if normalise else name)
        tr = trades.get(name)
        if tr is None or tr.empty:
            continue
        lookup = pd.Series(y.values, index=pd.to_datetime(pd.Series(list(y.index))).values)
        for col, marker, size in (("entry", "o", 16), ("exit", "v", 26)):
            when = pd.to_datetime(tr[col])
            price = lookup.reindex(when.values).values
            if col == "entry":
                ax.scatter(when, price, s=size, marker=marker, facecolors="none",
                           edgecolors=INK_2, linewidths=0.8, zorder=4)
            else:
                won = tr["pnl"].values > 0
                ax.scatter(when[won], price[won], s=size, marker=marker, color=WIN, zorder=5,
                           linewidths=0.5, edgecolors=SURFACE)
                ax.scatter(when[~won], price[~won], s=size, marker=marker, color=LOSS, zorder=6,
                           linewidths=0.5, edgecolors=SURFACE)
    _mark_splits(ax, series)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_axisbelow(True)


def _mark_splits(ax, series: dict[str, pd.Series]) -> None:
    """Flag stock splits. Kaggle chains are not split adjusted, so the price line steps and a reader
    would otherwise take a 4:1 split for a 75% crash."""
    from synthetix_alpha.data import yf

    for name, spot in series.items():
        idx = list(spot.index)
        try:
            ratios = yf.splits(name)
        except Exception:
            continue
        for when, ratio in ratios.items():
            if not (idx[0] <= when <= idx[-1]):
                continue
            ax.axvline(pd.Timestamp(when), color=MUTED, linewidth=0.9, linestyle=(0, (4, 3)), zorder=1)
            ax.annotate(f"{name} {ratio:g}:1 split", (pd.Timestamp(when), 0.97), xycoords=("data", "axes fraction"),
                        color=MUTED, fontsize=7.5, ha="right", va="top", rotation=90,
                        xytext=(-3, 0), textcoords="offset points")


def strategy_figure(spec: Spec, out_dir: Path = OUT, source: str = "kaggle") -> Path | None:
    """One PNG per strategy: the underlying with fills on top, the equity it produced underneath."""
    from synthetix_alpha.strategy import EngineData
    from synthetix_alpha.strategy.engine import run

    spots, trades, curves = {}, {}, {}
    for u in spec.underlyings:
        try:
            data = EngineData.load(u, dte_max=spec.dte_max + 1, source=source)
            out = run(spec, data, 100_000.0)
        except Exception:
            continue
        tr = pd.DataFrame(out.trades)
        if tr.empty:
            continue
        spots[u], trades[u], curves[u] = data.features["spot"].dropna(), tr, out.equity
    if not spots:
        return None

    n_trades = sum(len(t) for t in trades.values())
    wins = sum(int((t["pnl"] > 0).sum()) for t in trades.values())
    with mpl.rc_context(STYLE):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7.4), sharex=True,
                                       gridspec_kw={"height_ratios": [1.15, 1], "hspace": 0.28})
        multi = len(spots) > 1
        fills_panel(ax1, spots, trades, normalise=multi)
        _finish(ax1, f"{spec.name} — underlying and fills",
                f"{n_trades} trades, {wins/max(n_trades,1):.0%} profitable. Hollow circle is the entry; "
                f"triangle is the exit, green for a profit and red for a loss.", pct_y=False)
        ax1.set_ylabel("rebased to 100" if multi else "price ($)")
        if multi:
            ax1.legend(loc="upper left", ncols=min(len(spots), 4))

        equity_panel(ax2, curves, palette=SERIES_FILLS)
        ax2.set_ylabel("return")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{spec.name}_fills.png"
        fig.savefig(path)
        plt.close(fig)
    return path


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


def build(spec: Spec, out_dir: Path = OUT) -> list[Path]:
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

    return written


def _deployed_gate(spec: Spec) -> float | None:
    r = spec.signal.get("iv_rv_ratio")
    return r[0] if r else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="omit with --fills-all to do every strategy")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--fills", action="store_true", help="underlying-with-fills figure instead of performance")
    ap.add_argument("--fills-all", action="store_true", help="the fills figure for every spec in strategies/")
    a = ap.parse_args()
    out = Path(a.out)
    if a.fills_all:
        for f in sorted(Path("strategies").glob("*.json")):
            if f.name == "portfolio.json":
                continue
            try:
                path = strategy_figure(Spec.load(f), out)
            except Exception as e:
                print(f"{f.name}: {type(e).__name__}: {e}")
                continue
            print(path or f"{f.name}: no trades")
        return
    if not a.spec:
        ap.error("spec is required unless --fills-all")
    if a.fills:
        print(strategy_figure(Spec.load(a.spec), out))
        return
    for p in build(Spec.load(a.spec), out):
        print(p)


if __name__ == "__main__":
    main()
