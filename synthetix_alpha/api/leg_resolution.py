"""Resolve strategy legs to tradable Alpaca OCC option symbols."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

import pandas as pd

from synthetix_alpha.data.occ import build_occ_symbol, parse_occ_symbol

logger = logging.getLogger(__name__)


def is_placeholder_symbol(symbol: str) -> bool:
    s = str(symbol or "")
    return (
        not s
        or "OCC_PLACEHOLDER" in s
        or "OCC_RESOLVED" in s
        or s.endswith("_PLACEHOLDER")
    )


def is_valid_occ_symbol(symbol: str) -> bool:
    try:
        parse_occ_symbol(symbol)
        return True
    except ValueError:
        return False


def legs_are_executable(legs: list[dict] | None) -> bool:
    """True only when every option leg is a real OCC symbol (not a placeholder)."""
    if not legs:
        return False
    for leg in legs:
        if not isinstance(leg, dict):
            return False
        if leg.get("type") == "stock":
            continue
        symbol = str(leg.get("symbol", ""))
        if is_placeholder_symbol(symbol) or not is_valid_occ_symbol(symbol):
            return False
        if leg.get("resolved") is False:
            return False
    return True


def _spot_from_candidates(ticker: str, candidates: pd.DataFrame) -> Optional[float]:
    if candidates is None or not isinstance(candidates, pd.DataFrame) or candidates.empty:
        return None
    if ticker not in candidates.index:
        return None
    for col in ("price", "underlying_price", "close"):
        if col in candidates.columns:
            try:
                value = float(candidates.at[ticker, col])
                if value == value and value > 0:
                    return value
            except (TypeError, ValueError):
                continue
    return None


def _dte_window(spec: object) -> tuple[dt.date, dt.date, int]:
    today = dt.date.today()
    dte_min = int(getattr(spec, "dte_min", 30))
    dte_max = int(getattr(spec, "dte_max", 60))
    dte_target = int(getattr(spec, "dte_target", 45))
    return today + dt.timedelta(days=dte_min), today + dt.timedelta(days=dte_max), dte_target


def _pick_expiration(expirations: list[dt.date], target_dte: int) -> Optional[dt.date]:
    if not expirations:
        return None
    today = dt.date.today()
    return min(expirations, key=lambda exp: abs((exp - today).days - target_dte))


def _nearest_by_delta(rows: pd.DataFrame, target_delta: float) -> Optional[pd.Series]:
    if rows.empty or "delta" not in rows.columns:
        return None
    work = rows.dropna(subset=["delta"]).copy()
    if work.empty:
        return None
    work["dist"] = (work["delta"].abs() - abs(target_delta)).abs()
    return work.nsmallest(1, "dist").iloc[0]


def _nearest_by_strike(rows: pd.DataFrame, strike: float) -> Optional[pd.Series]:
    if rows.empty:
        return None
    work = rows.copy()
    strike_col = "strike" if "strike" in work.columns else "strike_price"
    work["dist"] = (pd.to_numeric(work[strike_col], errors="coerce") - strike).abs()
    work = work.dropna(subset=["dist"])
    if work.empty:
        return None
    return work.nsmallest(1, "dist").iloc[0]


def _leg_dict_from_row(
    row: pd.Series,
    *,
    side: str,
    ratio: int,
    leg_type: str,
    delta: Optional[float] = None,
    dte_offset: int = 0,
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "")
    if not symbol and "expiration" in row and "strike" in row:
        symbol = build_occ_symbol(
            str(row.get("underlying") or row.get("underlying_symbol") or ""),
            row["expiration"],
            leg_type,
            float(row["strike"]),
        )
    strike = row.get("strike", row.get("strike_price"))
    return {
        "symbol": symbol,
        "side": side,
        "ratio": ratio,
        "type": leg_type,
        "strike": float(strike) if strike is not None else None,
        "delta": float(delta) if delta is not None else (
            float(row["delta"]) if "delta" in row and pd.notna(row.get("delta")) else None
        ),
        "dte_offset": dte_offset,
        "expiration": str(row.get("expiration") or row.get("expiration_date") or ""),
        "resolved": True,
    }


def resolve_via_alpaca_chain(spec: object, ticker: str, candidates: pd.DataFrame) -> list[dict]:
    """Resolve legs using live Alpaca option chain snapshots (greeks + OCC symbols)."""
    from synthetix_alpha.data.alpaca import AlpacaClient

    exp_gte, exp_lte, target_dte = _dte_window(spec)
    client = AlpacaClient(paper=True)
    chain = client.option_chain(
        ticker,
        expiration_date_gte=exp_gte.isoformat(),
        expiration_date_lte=exp_lte.isoformat(),
    )
    if chain is None or chain.empty:
        return []

    work = chain.reset_index()
    if "expiration" not in work.columns:
        return []
    work["expiration"] = pd.to_datetime(work["expiration"]).dt.date
    expiration = _pick_expiration(sorted(work["expiration"].dropna().unique().tolist()), target_dte)
    if expiration is None:
        return []
    surface = work[work["expiration"] == expiration]
    if surface.empty:
        return []

    resolved: list[dict] = []
    for leg in spec.legs:
        if leg.type == "stock":
            resolved.append({
                "symbol": ticker,
                "side": leg.side,
                "ratio": leg.ratio,
                "type": "stock",
                "resolved": True,
            })
            continue

        opts = surface[surface["type"] == leg.type]
        row = None
        if leg.delta is not None:
            row = _nearest_by_delta(opts, float(leg.delta))
        elif leg.moneyness is not None:
            spot = _spot_from_candidates(ticker, candidates)
            if spot is None and "underlying_price" in surface.columns:
                spot = float(surface["underlying_price"].dropna().iloc[0]) if surface["underlying_price"].notna().any() else None
            if spot is not None:
                row = _nearest_by_strike(opts, spot * (1 + float(leg.moneyness)))
        elif leg.width is not None and resolved:
            prev = resolved[-1].get("strike")
            if prev is not None:
                row = _nearest_by_strike(opts, float(prev) + float(leg.width))

        if row is None:
            return []
        symbol = str(row.get("symbol") or "")
        if not is_valid_occ_symbol(symbol):
            return []
        resolved.append(
            _leg_dict_from_row(
                row,
                side=leg.side,
                ratio=leg.ratio,
                leg_type=leg.type,
                delta=leg.delta,
                dte_offset=leg.dte_offset,
            )
        )

    return resolved if legs_are_executable(resolved) else []


def resolve_via_alpaca_contracts(spec: object, ticker: str, candidates: pd.DataFrame) -> list[dict]:
    """Fallback: tradable contracts via Alpaca CLI, strike selection by moneyness heuristic."""
    from synthetix_alpha.live import cli

    spot = _spot_from_candidates(ticker, candidates)
    if spot is None or spot <= 0:
        return []

    exp_gte, exp_lte, target_dte = _dte_window(spec)
    kind = "put"
    for leg in spec.legs:
        if getattr(leg, "type", None) in ("put", "call"):
            kind = leg.type
            break

    try:
        contracts = cli.contracts(
            ticker,
            kind=kind,
            exp_gte=exp_gte.isoformat(),
            exp_lte=exp_lte.isoformat(),
            limit=500,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Alpaca contracts unavailable for %s: %s", ticker, exc)
        return []

    if not contracts:
        return []

    rows = []
    for c in contracts:
        if not c.get("tradable", True):
            continue
        try:
            exp = dt.date.fromisoformat(str(c["expiration_date"])[:10])
            strike = float(c["strike_price"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({
            "symbol": c["symbol"],
            "expiration": exp,
            "strike": strike,
            "type": str(c.get("type") or kind).lower(),
            "underlying_symbol": ticker,
        })
    if not rows:
        return []

    frame = pd.DataFrame(rows)
    expiration = _pick_expiration(sorted(frame["expiration"].unique().tolist()), target_dte)
    if expiration is None:
        return []
    surface = frame[frame["expiration"] == expiration]
    resolved: list[dict] = []

    for leg in spec.legs:
        if leg.type == "stock":
            resolved.append({
                "symbol": ticker,
                "side": leg.side,
                "ratio": leg.ratio,
                "type": "stock",
                "resolved": True,
            })
            continue

        opts = surface[surface["type"] == leg.type]
        # Approximate delta targets with OTM moneyness when greeks are absent.
        if leg.delta is not None:
            otm = min(0.12, max(0.02, abs(float(leg.delta)) * 0.25))
            target = spot * (1 - otm) if leg.type == "put" else spot * (1 + otm)
            if leg.side == "long" and leg.type == "put":
                # Long put further OTM than short for credit spreads.
                target = spot * (1 - min(0.18, otm + 0.05))
            row = _nearest_by_strike(opts, target)
        elif leg.moneyness is not None:
            row = _nearest_by_strike(opts, spot * (1 + float(leg.moneyness)))
        elif leg.width is not None and resolved:
            prev = resolved[-1].get("strike")
            if prev is None:
                return []
            row = _nearest_by_strike(opts, float(prev) + float(leg.width))
        else:
            return []

        if row is None or not is_valid_occ_symbol(str(row.get("symbol", ""))):
            return []
        resolved.append(
            _leg_dict_from_row(
                row,
                side=leg.side,
                ratio=leg.ratio,
                leg_type=leg.type,
                delta=leg.delta,
                dte_offset=leg.dte_offset,
            )
        )

    return resolved if legs_are_executable(resolved) else []


def resolve_via_dolt(spec: object, ticker: str, candidates: pd.DataFrame) -> list[dict]:
    """Resolve via historical dolt chain, emitting real OCC symbols when strikes/exp exist."""
    try:
        from synthetix_alpha.strategy.data import build as build_chain

        chains, _features = build_chain(ticker, source="dolt")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Dolt chain unavailable for %s: %s", ticker, exc)
        return []

    if chains is None or chains.empty:
        return []

    chains_df = chains.reset_index()
    if "expiration" not in chains_df.columns or "date" not in chains_df.columns:
        return []

    chains_df["expiration"] = pd.to_datetime(chains_df["expiration"]).dt.date
    chains_df["date"] = pd.to_datetime(chains_df["date"]).dt.date
    chains_df["dte"] = (pd.to_datetime(chains_df["expiration"]) - pd.to_datetime(chains_df["date"])).dt.days
    target_dte = int(getattr(spec, "dte_target", 45))
    near = chains_df[chains_df["dte"].between(target_dte - 10, target_dte + 10)]
    if near.empty:
        return []

    latest_date = near["date"].max()
    latest = near[near["date"] == latest_date]
    spot = float(latest["underlying_price"].iloc[0]) if "underlying_price" in latest.columns else _spot_from_candidates(ticker, candidates)
    if spot is None:
        return []

    # Prefer a still-future expiration closest to target DTE from today.
    today = dt.date.today()
    future = latest[latest["expiration"] >= today]
    surface = future if not future.empty else latest
    expiration = _pick_expiration(sorted(surface["expiration"].dropna().unique().tolist()), target_dte)
    if expiration is None:
        return []
    surface = surface[surface["expiration"] == expiration]

    resolved: list[dict] = []
    for leg in spec.legs:
        if leg.type == "stock":
            resolved.append({
                "symbol": ticker,
                "side": leg.side,
                "ratio": leg.ratio,
                "type": "stock",
                "resolved": True,
            })
            continue

        opts = surface[surface["type"] == leg.type].copy()
        strike = None
        row = None
        if leg.delta is not None:
            row = _nearest_by_delta(opts, float(leg.delta))
            if row is not None:
                strike = float(row["strike"])
        elif leg.moneyness is not None:
            strike = spot * (1 + float(leg.moneyness))
            row = _nearest_by_strike(opts, strike)
            if row is not None:
                strike = float(row["strike"])
        elif leg.width is not None and resolved:
            prev = resolved[-1].get("strike", spot)
            strike = float(prev) + float(leg.width)
            row = _nearest_by_strike(opts, strike)
            if row is not None:
                strike = float(row["strike"])

        if strike is None or expiration is None:
            return []

        symbol = build_occ_symbol(ticker, expiration, leg.type, strike)
        resolved.append({
            "symbol": symbol,
            "side": leg.side,
            "ratio": leg.ratio,
            "type": leg.type,
            "strike": strike,
            "delta": leg.delta,
            "dte_offset": leg.dte_offset,
            "expiration": expiration.isoformat(),
            "resolved": True,
        })

    return resolved if legs_are_executable(resolved) else []


def abstract_placeholder_legs(spec: object, ticker: str) -> list[dict]:
    legs: list[dict] = []
    for leg in spec.legs:
        if leg.type == "stock":
            legs.append({
                "symbol": ticker,
                "side": leg.side,
                "ratio": leg.ratio,
                "type": "stock",
                "resolved": False,
            })
        else:
            legs.append({
                "symbol": f"{ticker}_OCC_PLACEHOLDER",
                "side": leg.side,
                "ratio": leg.ratio,
                "type": leg.type,
                "delta": leg.delta,
                "moneyness": leg.moneyness,
                "width": leg.width,
                "dte_offset": leg.dte_offset,
                "resolved": False,
            })
    return legs


def resolve_legs(spec: object, ticker: str, candidates: pd.DataFrame) -> list[dict]:
    """Resolve abstract strategy legs to executable OCC symbols when possible."""
    for resolver in (resolve_via_alpaca_chain, resolve_via_alpaca_contracts, resolve_via_dolt):
        try:
            resolved = resolver(spec, ticker, candidates)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Leg resolver %s failed for %s: %s", resolver.__name__, ticker, exc)
            continue
        if resolved:
            logger.info("Resolved %s legs via %s", ticker, resolver.__name__)
            return resolved
    logger.info("No executable legs for %s — using placeholders", ticker)
    return abstract_placeholder_legs(spec, ticker)


def estimate_credit_and_max_loss(legs: list[dict], contracts: int = 1) -> tuple[float, float]:
    """Estimate net credit (negative limit) and dollar max loss for a vertical."""
    option_legs = [leg for leg in legs if leg.get("type") != "stock"]
    strikes = [float(leg["strike"]) for leg in option_legs if leg.get("strike") is not None]
    if len(strikes) < 2:
        return -0.15, 2000.0 * contracts
    width = abs(max(strikes) - min(strikes))
    credit = max(0.05, round(width * 0.25, 2))
    max_loss = max(0.0, (width - credit) * 100.0 * contracts)
    return -credit, max_loss
