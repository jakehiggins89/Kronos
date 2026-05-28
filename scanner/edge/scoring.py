from __future__ import annotations

import math
from statistics import median
from typing import Any

import numpy as np


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _analog_summary(analogs: list[dict]) -> dict[str, float]:
    if not analogs:
        return {
            "count": 0,
            "win_rate": 0.0,
            "average_return_pct": 0.0,
            "median_return_pct": 0.0,
            "average_r_multiple": 0.0,
            "average_mae_pct": 0.0,
            "average_mfe_pct": 0.0,
            "return_std_pct": 0.0,
        }
    returns = [_finite_float(a.get("outcome_return_pct")) for a in analogs]
    r_mult = [_finite_float(a.get("r_multiple")) for a in analogs]
    mae = [_finite_float(a.get("mae_pct")) for a in analogs]
    mfe = [_finite_float(a.get("mfe_pct")) for a in analogs]
    wins = [1.0 if a.get("outcome_label") == "win" or _finite_float(a.get("outcome_return_pct")) > 0 else 0.0 for a in analogs]
    return {
        "count": len(analogs),
        "win_rate": float(np.mean(wins)),
        "average_return_pct": float(np.mean(returns)),
        "median_return_pct": float(median(returns)),
        "average_r_multiple": float(np.mean(r_mult)),
        "average_mae_pct": float(np.mean(mae)),
        "average_mfe_pct": float(np.mean(mfe)),
        "return_std_pct": float(np.std(returns)),
    }


def score_edge_candidate(features: dict, analogs: list[dict], min_analogs: int = 5) -> dict:
    """Score a candidate with transparent components and conservative promotion rules."""
    summary = _analog_summary(analogs)
    research_score = _finite_float(features.get("research_score"))
    rr_ratio = _finite_float(features.get("rr_ratio"))
    empty_space_score = _finite_float(features.get("empty_space_score"))
    potter_passed = bool(features.get("potter_passed"))
    empty_space_passed = bool(features.get("empty_space_passed")) or empty_space_score > 0.0
    setup_gate_passed = potter_passed or empty_space_passed
    kronos_agreement = _finite_float(features.get("kronos_directional_agreement"), 0.5)
    kronos_median = _finite_float(features.get("kronos_median_forecast_return_pct"))
    data_quality = _finite_float(features.get("data_quality_score"), 1.0)
    feed_confidence = _finite_float(features.get("feed_confidence"), 0.5)
    options_spread = _finite_float(features.get("options_spread_pct"))

    scorecard = {
        "base": 30.0,
        "setup_quality": _clamp((research_score * 0.15) + (5.0 if potter_passed else 0.0) + (empty_space_score * 2.0), 0.0, 24.0),
        "setup_gate": 0.0 if setup_gate_passed else -25.0,
        "reward_risk": _clamp(rr_ratio * 4.0, 0.0, 12.0),
        "analog_expectancy": _clamp((summary["average_r_multiple"] * 25.0) + ((summary["win_rate"] - 0.5) * 20.0), -30.0, 35.0),
        "kronos": _clamp(((kronos_agreement - 0.5) * 20.0) + _clamp(kronos_median, -5.0, 5.0), -12.0, 12.0),
        "uncertainty": -_clamp(summary["return_std_pct"], 0.0, 12.0),
        "sample_penalty": -_clamp(max(min_analogs - summary["count"], 0) * 5.0, 0.0, 20.0),
        "data_quality": _clamp(((data_quality - 1.0) * 15.0) + ((feed_confidence - 0.5) * 10.0), -18.0, 6.0),
        "options_liquidity": -_clamp(max(options_spread - 0.12, 0.0) * 100.0, 0.0, 10.0),
    }
    raw_score = sum(scorecard.values())
    edge_score = round(_clamp(raw_score, 0.0, 100.0), 2)
    if not setup_gate_passed:
        edge_score = min(edge_score, 44.0)

    if (
        edge_score >= 65.0
        and setup_gate_passed
        and summary["count"] >= min_analogs
        and summary["average_r_multiple"] > 0.0
        and data_quality >= 0.5
        and feed_confidence >= 0.35
    ):
        recommendation = "promote"
    elif edge_score >= 45.0 and setup_gate_passed:
        recommendation = "research"
    else:
        recommendation = "reject"

    return {
        "edge_score": edge_score,
        "recommendation": recommendation,
        "scorecard": {key: round(float(value), 4) for key, value in scorecard.items()},
        "analog_summary": summary,
    }
