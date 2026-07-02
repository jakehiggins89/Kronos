"""Path-aware (triple-barrier) trade outcome evaluation.

Single source of truth for both the edge lab (historical index records) and
the journal outcome reviewer, so automatic policy changes learn from the same
outcome definition the validation evidence uses.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def resolve_trade_risk_pct(risk_pct: float, atr_value: float, entry: float) -> float:
    """Risk (stop distance, %) with a defined fallback so R-multiples stay sane.

    Empty-space risk can be missing or near zero, which previously produced
    unbounded R values. Fallback: one ATR, else 2%. Clamped to [0.25, 15].
    """
    risk = _finite_float(risk_pct)
    if risk <= 0.05:
        atr_pct = (_finite_float(atr_value) / entry) * 100.0 if entry > 0 else 0.0
        risk = atr_pct if atr_pct > 0.05 else 2.0
    return float(min(max(risk, 0.25), 15.0))


def walk_triple_barrier(
    path: pd.DataFrame,
    direction: str,
    entry: float,
    risk_pct: float,
    target_pct: float,
) -> dict[str, Any]:
    """Evaluate a stop/target/time trade plan against an OHLC path.

    `path` holds the bars AFTER entry, in order, through the time horizon.
    Stops honor gaps: if a bar opens beyond the stop, the fill is the open,
    not the stop price - flooring gap losses at -1R systematically flattered
    the expectancy that gates promotion. Target fills stay capped at the
    target price (the conservative side of a favorable gap). Same-bar
    stop+target is unknowable from OHLC and resolves to the stop.
    """
    result = {
        "return_pct": 0.0,
        "label": "loss",
        "r_multiple": 0.0,
        "mae_pct": 0.0,
        "mfe_pct": 0.0,
        "exit_reason": "no_data",
        "risk_pct_used": 0.0,
        "method": "triple_barrier",
    }
    if path is None or path.empty or entry <= 0 or direction not in {"bullish", "bearish"}:
        return result

    risk = _finite_float(risk_pct)
    if risk <= 0.0:
        return result
    target = _finite_float(target_pct)
    if target <= 0.05:
        target = 2.0 * risk

    sign = 1.0 if direction == "bullish" else -1.0
    stop_price = entry * (1.0 - sign * risk / 100.0)
    target_price = entry * (1.0 + sign * target / 100.0)
    has_open = "Open" in path.columns

    exit_reason = "horizon"
    exit_idx = len(path) - 1
    ret_pct = sign * ((_finite_float(path["Close"].iloc[-1]) - entry) / entry) * 100.0
    for pos in range(len(path)):
        low = _finite_float(path["Low"].iloc[pos])
        high = _finite_float(path["High"].iloc[pos])
        stop_touched = low <= stop_price if direction == "bullish" else high >= stop_price
        target_touched = high >= target_price if direction == "bullish" else low <= target_price
        if stop_touched:
            exit_price = stop_price
            if has_open:
                open_price = _finite_float(path["Open"].iloc[pos])
                gapped_through = open_price <= stop_price if direction == "bullish" else open_price >= stop_price
                if open_price > 0 and gapped_through:
                    exit_price = open_price
            exit_reason = "stop"
            exit_idx = pos
            ret_pct = sign * ((exit_price - entry) / entry) * 100.0
            break
        if target_touched:
            exit_reason = "target"
            exit_idx = pos
            ret_pct = target
            break

    window = path.iloc[: exit_idx + 1]
    if direction == "bullish":
        mae_pct = ((_finite_float(window["Low"].min()) - entry) / entry) * 100.0
        mfe_pct = ((_finite_float(window["High"].max()) - entry) / entry) * 100.0
    else:
        mae_pct = ((entry - _finite_float(window["High"].max())) / entry) * 100.0
        mfe_pct = ((entry - _finite_float(window["Low"].min())) / entry) * 100.0

    r_multiple = min(max(ret_pct / risk, -10.0), 10.0)
    label = "win" if (exit_reason == "target" or (exit_reason == "horizon" and ret_pct > 0)) else "loss"
    return {
        "return_pct": float(ret_pct),
        "label": label,
        "r_multiple": float(r_multiple),
        "mae_pct": float(mae_pct),
        "mfe_pct": float(mfe_pct),
        "exit_reason": exit_reason,
        "risk_pct_used": float(risk),
        "method": "triple_barrier",
    }
