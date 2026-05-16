from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _is_win(candidate: dict) -> bool:
    if candidate.get("outcome_label") in {"win", "loss"}:
        return candidate.get("outcome_label") == "win"
    return _finite_float(candidate.get("outcome_return_pct")) > 0


def _metric_block(candidates: list[dict], selected: list[dict], total_wins: int, slippage_pct: float) -> dict:
    signal_count = len(selected)
    wins = sum(1 for row in selected if _is_win(row))
    losses = signal_count - wins
    false_negatives = max(total_wins - wins, 0)
    returns = [_finite_float(row.get("outcome_return_pct")) for row in selected]
    adjusted_returns = [ret - abs(slippage_pct) for ret in returns]
    r_mult = [_finite_float(row.get("r_multiple")) for row in selected]
    mae = [_finite_float(row.get("mae_pct")) for row in selected if row.get("mae_pct") is not None]
    mfe = [_finite_float(row.get("mfe_pct")) for row in selected if row.get("mfe_pct") is not None]

    return {
        "signal_count": signal_count,
        "wins": wins,
        "losses": losses,
        "precision": wins / signal_count if signal_count else 0.0,
        "recall": wins / total_wins if total_wins else 0.0,
        "false_negative_rate": false_negatives / total_wins if total_wins else 0.0,
        "average_return_pct": float(np.mean(returns)) if returns else 0.0,
        "median_return_pct": float(np.median(returns)) if returns else 0.0,
        "average_return_pct_after_slippage": float(np.mean(adjusted_returns)) if adjusted_returns else 0.0,
        "average_r_multiple": float(np.mean(r_mult)) if r_mult else 0.0,
        "max_adverse_excursion": float(np.min(mae)) if mae else 0.0,
        "max_favorable_excursion": float(np.max(mfe)) if mfe else 0.0,
    }


def compute_edge_validation_report(
    candidates: Iterable[dict],
    thresholds: tuple[int, ...] = (45, 55, 65),
    top_k: int = 5,
    slippage_pct: float = 0.0,
) -> dict:
    rows = [dict(row) for row in candidates]
    rows.sort(key=lambda row: _finite_float(row.get("edge_score")), reverse=True)
    total_wins = sum(1 for row in rows if _is_win(row))

    threshold_blocks = {}
    for threshold in thresholds:
        selected = [row for row in rows if _finite_float(row.get("edge_score")) >= float(threshold)]
        threshold_blocks[str(threshold)] = _metric_block(rows, selected, total_wins, slippage_pct)

    top_rows = rows[: max(top_k, 0)]
    top_block = _metric_block(rows, top_rows, total_wins, slippage_pct)
    top_block["k"] = top_k

    by_direction: dict[str, dict] = {}
    for direction in sorted({str(row.get("direction", "unknown")) for row in rows}):
        subset = [row for row in rows if str(row.get("direction", "unknown")) == direction]
        by_direction[direction] = _metric_block(subset, subset, sum(1 for row in subset if _is_win(row)), slippage_pct)

    return {
        "samples": len(rows),
        "wins": total_wins,
        "losses": len(rows) - total_wins,
        "thresholds": threshold_blocks,
        "top_k": top_block,
        "by_direction": by_direction,
    }
