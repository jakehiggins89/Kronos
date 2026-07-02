from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

from .. import config as scanner_config
from ..config import (
    DOCTRINE_V2_SCORE_BASELINE_BOUNDS,
    OVERRIDES_PATH,
    RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS,
    TUNING_DIR,
)
from .outcome_store import deduplicate_decisions


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _is_research_candidate(record: dict) -> bool:
    diagnostics = record.get("research_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    return bool(diagnostics.get("passed")) or record.get("skip_reason") == "research_candidate"


def _wilson_lower_bound(wins: int, total: int, z: float = 1.28) -> float:
    if total <= 0:
        return 0.0
    p_hat = wins / total
    z2 = z * z
    denominator = 1.0 + (z2 / total)
    center = p_hat + (z2 / (2.0 * total))
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + (z2 / (4.0 * total))) / total)
    return max(0.0, (center - margin) / denominator)


def _threshold_grid(current_research_score: int) -> list[int]:
    low, high = RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS
    candidates = set(range(int(low), int(high) + 1, 5))
    candidates.add(int(current_research_score))
    return sorted(score for score in candidates if int(low) <= score <= int(high))


def _generic_threshold_grid(current_score: int, bounds: tuple[int, int]) -> list[int]:
    low, high = bounds
    candidates = set(range(int(low), int(high) + 1, 5))
    candidates.add(int(current_score))
    return sorted(score for score in candidates if int(low) <= score <= int(high))


def _metric_block(rows: list[dict]) -> dict:
    wins = sum(1 for row in rows if row.get("outcome_label") == "win")
    losses = sum(1 for row in rows if row.get("outcome_label") == "loss")
    returns = [_finite_float(row.get("outcome_ret_5bar_pct")) for row in rows]
    total = wins + losses
    return {
        "signal_count": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "wilson_lower_win_rate": round(_wilson_lower_bound(wins, total), 4) if total else 0.0,
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
    }


def _state_metric_blocks(rows: list[dict], field: str) -> dict[str, dict]:
    states = sorted({str(row.get(field) or "unknown") for row in rows})
    return {state: _metric_block([row for row in rows if str(row.get(field) or "unknown") == state]) for state in states}


def _doctrine_risk_flag_counts(rows: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        flags = row.get("doctrine_v2_risk_flags")
        if isinstance(flags, list):
            counts.update(str(flag) for flag in flags)
    return dict(counts)


def _build_doctrine_v2_policy(
    rows: list[dict],
    *,
    current_doctrine_score_baseline: int,
    min_doctrine_samples: int,
    min_wilson_win_rate: float,
    min_average_return_pct: float,
) -> dict:
    doctrine_rows = [row for row in rows if row.get("doctrine_v2_score") is not None]
    threshold_candidates = []
    for threshold in _generic_threshold_grid(current_doctrine_score_baseline, DOCTRINE_V2_SCORE_BASELINE_BOUNDS):
        selected = [row for row in doctrine_rows if _finite_float(row.get("doctrine_v2_score"), -1.0) >= threshold]
        threshold_candidates.append({"threshold": threshold, **_metric_block(selected)})

    supported = [
        row
        for row in threshold_candidates
        if row["signal_count"] >= min_doctrine_samples
        and row["wilson_lower_win_rate"] >= min_wilson_win_rate
        and row["average_return_pct"] >= min_average_return_pct
    ]
    supported.sort(
        key=lambda row: (
            row["signal_count"],
            row["threshold"],
            row["wilson_lower_win_rate"],
            row["average_return_pct"],
            row["win_rate"],
        ),
        reverse=True,
    )

    current_block = _metric_block(
        [row for row in doctrine_rows if _finite_float(row.get("doctrine_v2_score"), -1.0) >= current_doctrine_score_baseline]
    )
    recommendation = {
        "status": "insufficient_doctrine_v2_samples",
        "reason": "not enough resolved doctrine v2 candidates to adapt safely",
        "selected_threshold": None,
        "auto_apply_safe": False,
        "proposed_overrides": {},
    }
    if len(doctrine_rows) >= min_doctrine_samples:
        if supported:
            selected = supported[0]
            recommendation = {
                "status": "improve_doctrine_v2_baseline",
                "reason": "higher doctrine v2 score cohort has positive conservative evidence",
                "selected_threshold": selected["threshold"],
                "auto_apply_safe": selected["threshold"] >= current_doctrine_score_baseline,
                "proposed_overrides": {"DOCTRINE_V2_SCORE_BASELINE": int(selected["threshold"])},
            }
        elif current_block["signal_count"] < min_doctrine_samples:
            recommendation = {
                "status": "hold_doctrine_v2_baseline_pending_samples",
                "reason": "current doctrine v2 baseline needs more resolved samples before another tightening",
                "selected_threshold": None,
                "auto_apply_safe": False,
                "proposed_overrides": {},
            }
        elif current_block["losses"] > current_block["wins"] and current_block["average_return_pct"] < 0:
            tightened = min(
                int(DOCTRINE_V2_SCORE_BASELINE_BOUNDS[1]),
                int(current_doctrine_score_baseline) + 5,
            )
            recommendation = {
                "status": "tighten_doctrine_v2_baseline",
                "reason": "current doctrine v2 cohort is loss-heavy with negative average return",
                "selected_threshold": tightened,
                "auto_apply_safe": tightened > current_doctrine_score_baseline,
                "proposed_overrides": {"DOCTRINE_V2_SCORE_BASELINE": tightened},
            }
        else:
            recommendation = {
                "status": "hold_doctrine_v2_no_edge",
                "reason": "no doctrine v2 threshold has enough conservative evidence to improve win rate",
                "selected_threshold": None,
                "auto_apply_safe": False,
                "proposed_overrides": {},
            }

    return {
        "resolved": len(doctrine_rows),
        "current_baseline": int(current_doctrine_score_baseline),
        "current_threshold": current_block,
        "threshold_candidates": threshold_candidates,
        "punchback_states": _state_metric_blocks(doctrine_rows, "doctrine_v2_punchback_state"),
        "cost_basis_states": _state_metric_blocks(doctrine_rows, "doctrine_v2_cost_basis_state"),
        "risk_flag_counts": _doctrine_risk_flag_counts(doctrine_rows),
        "recommendation": recommendation,
    }


def build_adaptive_policy_report(
    records: list[dict],
    *,
    current_research_score: int | None = None,
    current_doctrine_score_baseline: int | None = None,
    min_research_samples: int = 8,
    min_doctrine_samples: int = 8,
    min_wilson_win_rate: float = 0.55,
    min_average_return_pct: float = 0.25,
) -> dict:
    """Evaluate whether resolved research outcomes justify a safe tuning change."""
    if current_research_score is None:
        current_research_score = scanner_config.RESEARCH_CANDIDATE_MIN_SCORE
    if current_doctrine_score_baseline is None:
        current_doctrine_score_baseline = scanner_config.DOCTRINE_V2_SCORE_BASELINE
    unique_records, dedupe_report = deduplicate_decisions(records)
    resolved = [row for row in unique_records if row.get("outcome_status") == "resolved"]
    research_rows = [row for row in resolved if _is_research_candidate(row)]
    research_rows = [row for row in research_rows if row.get("outcome_label") in {"win", "loss"}]
    research_labels = Counter(row.get("outcome_label") for row in research_rows)

    threshold_candidates = []
    for threshold in _threshold_grid(current_research_score):
        selected = [row for row in research_rows if _finite_float(row.get("research_score"), -1.0) >= threshold]
        block = _metric_block(selected)
        threshold_candidates.append({"threshold": threshold, **block})

    supported = [
        row
        for row in threshold_candidates
        if row["signal_count"] >= min_research_samples
        and row["wilson_lower_win_rate"] >= min_wilson_win_rate
        and row["average_return_pct"] >= min_average_return_pct
    ]
    supported.sort(
        key=lambda row: (
            row["signal_count"],
            row["threshold"],
            row["wilson_lower_win_rate"],
            row["average_return_pct"],
            row["win_rate"],
        ),
        reverse=True,
    )

    current_block = _metric_block(
        [row for row in research_rows if _finite_float(row.get("research_score"), -1.0) >= current_research_score]
    )
    recommendation = {
        "status": "insufficient_research_samples",
        "reason": "not enough resolved research candidates to adapt safely",
        "selected_threshold": None,
        "auto_apply_safe": False,
        "proposed_overrides": {},
    }
    if len(research_rows) >= min_research_samples:
        if supported:
            selected = supported[0]
            recommendation = {
                "status": "improve_research_threshold",
                "reason": "higher-score research cohort has positive conservative evidence",
                "selected_threshold": selected["threshold"],
                "auto_apply_safe": selected["threshold"] >= current_research_score,
                "proposed_overrides": {"RESEARCH_CANDIDATE_MIN_SCORE": int(selected["threshold"])},
            }
        elif current_block["signal_count"] < min_research_samples:
            recommendation = {
                "status": "hold_current_threshold_pending_samples",
                "reason": "current threshold needs more resolved samples before another automatic tightening",
                "selected_threshold": None,
                "auto_apply_safe": False,
                "proposed_overrides": {},
            }
        elif current_block["losses"] > current_block["wins"] and current_block["average_return_pct"] < 0:
            tightened = min(int(RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS[1]), int(current_research_score) + 5)
            recommendation = {
                "status": "tighten_research_threshold",
                "reason": "current research cohort is loss-heavy with negative average return",
                "selected_threshold": tightened,
                "auto_apply_safe": tightened > current_research_score,
                "proposed_overrides": {"RESEARCH_CANDIDATE_MIN_SCORE": tightened},
            }
        else:
            recommendation = {
                "status": "hold_no_edge",
                "reason": "no threshold has enough conservative evidence to improve win rate",
                "selected_threshold": None,
                "auto_apply_safe": False,
                "proposed_overrides": {},
            }

    doctrine_v2 = _build_doctrine_v2_policy(
        research_rows,
        current_doctrine_score_baseline=current_doctrine_score_baseline,
        min_doctrine_samples=min_doctrine_samples,
        min_wilson_win_rate=min_wilson_win_rate,
        min_average_return_pct=min_average_return_pct,
    )
    doctrine_recommendation = doctrine_v2["recommendation"]
    if doctrine_recommendation.get("auto_apply_safe") and doctrine_recommendation.get("proposed_overrides"):
        if recommendation.get("auto_apply_safe") and recommendation.get("proposed_overrides"):
            merged = {**recommendation["proposed_overrides"], **doctrine_recommendation["proposed_overrides"]}
            recommendation = {
                **recommendation,
                "status": "combined_safe_adaptive_update",
                "reason": f"{recommendation['reason']}; {doctrine_recommendation['reason']}",
                "proposed_overrides": merged,
            }
        elif not recommendation.get("auto_apply_safe"):
            recommendation = doctrine_recommendation

    resolved_count = len(research_rows)
    return {
        "mode": "adaptive_policy",
        "samples": len(resolved),
        "duplicate_records_ignored": dedupe_report["duplicates_removed"],
        "research_candidates": {
            "resolved": resolved_count,
            "resolved_outcomes": dict(research_labels),
            "resolved_win_rate": round(research_labels.get("win", 0) / resolved_count, 4) if resolved_count else 0.0,
            "current_threshold": int(current_research_score),
            **current_block,
        },
        "threshold_candidates": threshold_candidates,
        "doctrine_v2": doctrine_v2,
        "recommendation": recommendation,
    }


def apply_adaptive_overrides(report: dict, logger) -> dict:
    recommendation = report.get("recommendation", {}) if isinstance(report, dict) else {}
    overrides = recommendation.get("proposed_overrides", {})
    if not recommendation.get("auto_apply_safe") or not overrides:
        return {"status": "no_overrides_applied"}

    existing = {}
    if OVERRIDES_PATH.exists():
        try:
            existing_payload = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
            if isinstance(existing_payload, dict):
                existing = existing_payload
        except Exception:
            existing = {}
    merged = {**existing, **overrides}
    TUNING_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    scanner_config.reload_overrides()
    if logger is not None:
        logger.info("ADAPTIVE_POLICY_OVERRIDES_APPLIED: %s", json.dumps(overrides))
    return {"status": "applied", "path": str(OVERRIDES_PATH), "overrides": overrides, "merged_overrides": merged}
