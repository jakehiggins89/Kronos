from __future__ import annotations

import math
from typing import Any


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _threshold_block(validation_report: dict, threshold: int) -> dict:
    thresholds = validation_report.get("thresholds", {})
    block = thresholds.get(str(threshold), {})
    return block if isinstance(block, dict) else {}


def _candidate_features(candidate: dict) -> dict:
    features = candidate.get("features", {})
    return features if isinstance(features, dict) else {}


def _check(name: str, passed: bool, detail: str, value: Any = None) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "value": value,
    }


def compute_edge_audit_report(
    validation_report: dict,
    scan_report: dict,
    *,
    validation_threshold: int = 55,
    min_validation_signals: int = 20,
    min_precision: float = 0.55,
    min_average_r_multiple: float = 0.0,
) -> dict:
    """Summarize whether current edge evidence is research-ready or blocked."""
    candidates = [row for row in scan_report.get("candidates", []) if isinstance(row, dict)]
    active_candidates = [row for row in candidates if row.get("status") == "candidate"]
    research_candidates = [row for row in active_candidates if row.get("recommendation") == "research"]
    promoted_candidates = [row for row in active_candidates if row.get("recommendation") == "promote"]
    threshold = _threshold_block(validation_report, validation_threshold)

    validation_method = validation_report.get("validation_method")
    future_analogs_allowed = bool(validation_report.get("future_analogs_allowed", True))
    signal_count = int(_finite_float(threshold.get("signal_count")))
    precision = _finite_float(threshold.get("precision"))
    average_r = _finite_float(threshold.get("average_r_multiple"))

    checks = {
        "purged_walk_forward": _check(
            "purged_walk_forward",
            validation_method == "purged_walk_forward",
            "Historical validation must use walk-forward records only.",
            validation_method,
        ),
        "future_analogs_blocked": _check(
            "future_analogs_blocked",
            not future_analogs_allowed,
            "Validation must not score past candidates with future analogs.",
            future_analogs_allowed,
        ),
        "validation_threshold": _check(
            "validation_threshold",
            signal_count >= min_validation_signals and precision >= min_precision and average_r > min_average_r_multiple,
            f"Threshold {validation_threshold} needs enough positive out-of-sample evidence.",
            {
                "threshold": validation_threshold,
                "signal_count": signal_count,
                "min_signals": min_validation_signals,
                "precision": precision,
                "min_precision": min_precision,
                "average_r_multiple": average_r,
            },
        ),
    }

    blockers: list[str] = []
    if not checks["purged_walk_forward"]["passed"]:
        blockers.append("validation_not_walk_forward")
    if not checks["future_analogs_blocked"]["passed"]:
        blockers.append("future_analogs_allowed")
    if not checks["validation_threshold"]["passed"]:
        blockers.append(f"validation_threshold_{validation_threshold}_unsupported")

    warnings: list[str] = []
    low_feed_candidates = []
    missing_liquidity_candidates = []
    non_execution_options_candidates = []
    for row in active_candidates:
        features = _candidate_features(row)
        if _finite_float(features.get("feed_confidence"), 0.5) < 0.75:
            low_feed_candidates.append(row.get("ticker", "unknown"))
        open_interest = _finite_float(features.get("options_open_interest"))
        option_volume = _finite_float(features.get("options_volume"))
        spread = _finite_float(features.get("options_spread_pct"))
        if open_interest <= 0 or option_volume <= 0 or spread <= 0:
            missing_liquidity_candidates.append(row.get("ticker", "unknown"))
        if _finite_float(features.get("options_data_quality"), 0.45) < 0.75:
            non_execution_options_candidates.append(row.get("ticker", "unknown"))

    if low_feed_candidates:
        warnings.append("low_feed_confidence")
    if missing_liquidity_candidates:
        warnings.append("options_liquidity_missing")
    if non_execution_options_candidates:
        warnings.append("options_data_not_execution_grade")
    if not research_candidates and not promoted_candidates:
        warnings.append("no_current_actionable_candidates")

    if blockers:
        readiness = "blocked"
    elif promoted_candidates:
        readiness = "paper_trade_only"
    elif research_candidates:
        readiness = "research_only"
    else:
        readiness = "watch_only"

    return {
        "mode": "audit_edge",
        "readiness": readiness,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "summary": {
            "candidate_count": len(candidates),
            "active_candidates": len(active_candidates),
            "research_candidates": len(research_candidates),
            "promoted_candidates": len(promoted_candidates),
            "low_feed_confidence_candidates": low_feed_candidates,
            "missing_options_liquidity_candidates": missing_liquidity_candidates,
            "non_execution_grade_options_candidates": non_execution_options_candidates,
        },
    }
