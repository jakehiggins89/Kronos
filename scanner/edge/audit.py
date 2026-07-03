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
    min_rank_ic: float = 0.07,
    max_rank_ic_p_value: float = 0.05,
    min_top_decile_t_stat: float = 2.0,
    min_top_decile_wilson_lb: float = 0.45,
    min_direction_samples: int = 15,
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

    rank_ic = validation_report.get("rank_ic_r", {})
    rank_ic = rank_ic if isinstance(rank_ic, dict) else {}
    percentiles = validation_report.get("percentiles", {})
    percentiles = percentiles if isinstance(percentiles, dict) else {}
    top_decile = percentiles.get("top_10_pct", {})
    top_decile = top_decile if isinstance(top_decile, dict) else {}

    # Pooled IC can pass on direction separation alone (a positive bullish
    # cohort vs a negative bearish one) while the score ranks nothing INSIDE
    # either direction. Ranking evidence therefore also requires at least one
    # direction whose within-direction IC clears the bar, judged with the
    # day-clustered p-value (overlapping outcomes make the raw n
    # anti-conservative). Missing per-direction blocks fail closed.
    report_directions = validation_report.get("by_direction", {})
    report_directions = report_directions if isinstance(report_directions, dict) else {}
    within_direction_ic: dict[str, dict] = {}
    within_direction_passed = False
    for direction in ("bullish", "bearish"):
        block = report_directions.get(direction)
        if not isinstance(block, dict):
            continue
        direction_ic = block.get("rank_ic_r")
        if not isinstance(direction_ic, dict):
            continue
        ic_value = _finite_float(direction_ic.get("ic"))
        p_clustered = _finite_float(direction_ic.get("p_value_day_clustered", direction_ic.get("p_value")), 1.0)
        within_direction_ic[direction] = {
            "ic": ic_value,
            "p_value_day_clustered": p_clustered,
            "n": int(_finite_float(direction_ic.get("n"))),
        }
        if ic_value >= min_rank_ic and p_clustered <= max_rank_ic_p_value:
            within_direction_passed = True

    ranking_passed = (
        _finite_float(rank_ic.get("ic")) >= min_rank_ic
        and _finite_float(rank_ic.get("p_value"), 1.0) <= max_rank_ic_p_value
        and within_direction_passed
        and int(_finite_float(top_decile.get("signal_count"))) >= min_validation_signals
        and _finite_float(top_decile.get("average_r_multiple")) > 0.0
        and _finite_float(top_decile.get("t_stat_r_multiple")) >= min_top_decile_t_stat
        and _finite_float(top_decile.get("wilson_lb_precision")) >= min_top_decile_wilson_lb
    )

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
        "ranking_evidence": _check(
            "ranking_evidence",
            ranking_passed,
            "Score must rank outcomes across all samples AND within at least one direction, and the top decile must be profitable with enough signals.",
            {
                "rank_ic": _finite_float(rank_ic.get("ic")),
                "rank_ic_p_value": _finite_float(rank_ic.get("p_value"), 1.0),
                "min_rank_ic": min_rank_ic,
                "within_direction_ic": within_direction_ic,
                "within_direction_passed": within_direction_passed,
                "top_decile_signals": int(_finite_float(top_decile.get("signal_count"))),
                "min_signals": min_validation_signals,
                "top_decile_average_r": _finite_float(top_decile.get("average_r_multiple")),
                "top_decile_t_stat": _finite_float(top_decile.get("t_stat_r_multiple")),
                "top_decile_wilson_lb_precision": _finite_float(top_decile.get("wilson_lb_precision")),
            },
        ),
    }

    # Either evidence route is acceptable: the absolute-threshold gate is kept
    # for continuity, but score compression can leave it permanently starved
    # of signals, so ranking skill over all samples is an equal path.
    evidence_supported = checks["validation_threshold"]["passed"] or checks["ranking_evidence"]["passed"]

    # Promotion needs a direction PROVEN positive; under-sampled or absent
    # direction evidence is "unproven", not "safe" - failing open here would
    # let a thin cohort promote exactly when the data is weakest.
    blocked_directions: list[str] = []
    promotable_directions: list[str] = []
    by_direction = validation_report.get("by_direction", {})
    if isinstance(by_direction, dict):
        for direction, block in sorted(by_direction.items()):
            if not isinstance(block, dict) or direction not in {"bullish", "bearish"}:
                continue
            direction_samples = int(_finite_float(block.get("signal_count")))
            direction_avg_r = _finite_float(block.get("average_r_multiple"))
            if direction_samples >= min_direction_samples and direction_avg_r < 0.0:
                blocked_directions.append(direction)
            elif direction_samples >= min_direction_samples and direction_avg_r > 0.0:
                promotable_directions.append(direction)

    blockers: list[str] = []
    if not checks["purged_walk_forward"]["passed"]:
        blockers.append("validation_not_walk_forward")
    if not checks["future_analogs_blocked"]["passed"]:
        blockers.append("future_analogs_allowed")
    if not evidence_supported:
        if not checks["validation_threshold"]["passed"]:
            blockers.append(f"validation_threshold_{validation_threshold}_unsupported")
        if not checks["ranking_evidence"]["passed"]:
            blockers.append("ranking_evidence_unsupported")

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
    for direction in blocked_directions:
        warnings.append(f"{direction}_edge_negative")

    eligible_promoted = [row for row in promoted_candidates if str(row.get("direction")) in promotable_directions]
    if promoted_candidates and not eligible_promoted:
        warnings.append("promoted_candidates_direction_blocked")

    if blockers:
        readiness = "blocked"
    elif eligible_promoted:
        readiness = "paper_trade_only"
    elif research_candidates or promoted_candidates:
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
            "blocked_directions": blocked_directions,
            "promotable_directions": promotable_directions,
            "low_feed_confidence_candidates": low_feed_candidates,
            "missing_options_liquidity_candidates": missing_liquidity_candidates,
            "non_execution_grade_options_candidates": non_execution_options_candidates,
        },
    }
