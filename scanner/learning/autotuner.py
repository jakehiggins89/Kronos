from __future__ import annotations

import json

from ..config import (
    ATR_COMPRESSION,
    ATR_COMPRESSION_BOUNDS,
    AUTOTUNE_EMPTY_SPACE_STEP,
    AUTOTUNE_MIN_SAMPLES,
    AUTOTUNE_STEP_SIZE,
    MAX_ATM_BID_ASK_SPREAD_PCT,
    MAX_ATM_BID_ASK_SPREAD_PCT_BOUNDS,
    MIN_ATM_OPEN_INTEREST,
    MIN_ATM_OPEN_INTEREST_BOUNDS,
    MIN_EMPTY_SPACE_SCORE,
    MIN_EMPTY_SPACE_SCORE_BOUNDS,
    MIN_KRONOS_AGREEMENT,
    MIN_KRONOS_AGREEMENT_BOUNDS,
    MIN_RR,
    MIN_RR_BOUNDS,
    NO_TREND_SLOPE_ABS_MAX,
    NO_TREND_SLOPE_ABS_MAX_BOUNDS,
    OVERRIDES_PATH,
    RANGE_COMPRESSION,
    RANGE_COMPRESSION_BOUNDS,
    RESEARCH_CANDIDATE_MIN_SCORE,
    RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS,
    TUNING_DIR,
)
from .outcome_store import deduplicate_decisions


def _clamp(value, bounds):
    return max(bounds[0], min(bounds[1], value))


def propose_overrides(records: list[dict]) -> dict:
    unique_records, dedupe_report = deduplicate_decisions(records)
    resolved = [r for r in unique_records if r.get("outcome_status") == "resolved"]
    duplicate_records_ignored = dedupe_report["duplicates_removed"]
    if len(resolved) < AUTOTUNE_MIN_SAMPLES:
        return {
            "status": "insufficient_samples",
            "samples": len(resolved),
            "duplicate_records_ignored": duplicate_records_ignored,
            "overrides": {},
        }

    missed_winners = [r for r in resolved if not r.get("final_pass") and r.get("outcome_label") == "win"]
    correct_skips = [r for r in resolved if not r.get("final_pass") and r.get("outcome_label") == "loss"]
    false_pos = [r for r in resolved if r.get("final_pass") and r.get("outcome_label") == "loss"]
    true_pos = [r for r in resolved if r.get("final_pass") and r.get("outcome_label") == "win"]
    false_neg_by_stage: dict[str, int] = {}
    false_pos_by_stage: dict[str, int] = {}
    for r in missed_winners:
        k = str(r.get("stage_failed") or "unknown")
        false_neg_by_stage[k] = false_neg_by_stage.get(k, 0) + 1
    for r in false_pos:
        k = str(r.get("stage_failed") or "final_pass")
        false_pos_by_stage[k] = false_pos_by_stage.get(k, 0) + 1

    rr = MIN_RR
    kronos = MIN_KRONOS_AGREEMENT
    es = MIN_EMPTY_SPACE_SCORE
    spread = MAX_ATM_BID_ASK_SPREAD_PCT
    oi = MIN_ATM_OPEN_INTEREST
    atr = ATR_COMPRESSION
    rng = RANGE_COMPRESSION
    slope = NO_TREND_SLOPE_ABS_MAX
    research_score = RESEARCH_CANDIDATE_MIN_SCORE

    missed_total = len(missed_winners) + len(correct_skips)
    missed_win_rate = len(missed_winners) / max(missed_total, 1)
    pass_total = len(true_pos) + len(false_pos)
    pass_loss_rate = len(false_pos) / max(pass_total, 1)

    if missed_total and missed_win_rate <= 0.55 and len(false_pos) == 0:
        return {
            "status": "hold_no_edge",
            "samples": len(resolved),
            "duplicate_records_ignored": duplicate_records_ignored,
            "missed_winners": len(missed_winners),
            "correct_skips": len(correct_skips),
            "missed_win_rate": round(float(missed_win_rate), 4),
            "false_pos_losses": len(false_pos),
            "true_pos_wins": len(true_pos),
            "false_neg_by_stage": false_neg_by_stage,
            "false_pos_by_stage": false_pos_by_stage,
            "overrides": {},
            "recommendation": "collect higher-quality research_scan candidates before loosening live gates",
        }

    if missed_win_rate > 0.55 and len(missed_winners) > len(false_pos):
        rr = _clamp(rr - AUTOTUNE_STEP_SIZE, MIN_RR_BOUNDS)
        kronos = _clamp(kronos - AUTOTUNE_STEP_SIZE, MIN_KRONOS_AGREEMENT_BOUNDS)
        es = int(_clamp(es - AUTOTUNE_EMPTY_SPACE_STEP, MIN_EMPTY_SPACE_SCORE_BOUNDS))
        spread = _clamp(spread + AUTOTUNE_STEP_SIZE, MAX_ATM_BID_ASK_SPREAD_PCT_BOUNDS)
        oi = int(_clamp(oi - 100, MIN_ATM_OPEN_INTEREST_BOUNDS))
        research_score = int(_clamp(research_score - 5, RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS))
        if false_neg_by_stage.get("potter_box", 0) or false_neg_by_stage.get("potter_box_research", 0):
            atr = _clamp(atr + AUTOTUNE_STEP_SIZE, ATR_COMPRESSION_BOUNDS)
            rng = _clamp(rng + AUTOTUNE_STEP_SIZE, RANGE_COMPRESSION_BOUNDS)
            slope = _clamp(slope + 0.00025, NO_TREND_SLOPE_ABS_MAX_BOUNDS)
    elif pass_loss_rate > 0.45 and len(false_pos) >= len(true_pos):
        rr = _clamp(rr + AUTOTUNE_STEP_SIZE, MIN_RR_BOUNDS)
        kronos = _clamp(kronos + AUTOTUNE_STEP_SIZE, MIN_KRONOS_AGREEMENT_BOUNDS)
        es = int(_clamp(es + AUTOTUNE_EMPTY_SPACE_STEP, MIN_EMPTY_SPACE_SCORE_BOUNDS))
        spread = _clamp(spread - AUTOTUNE_STEP_SIZE, MAX_ATM_BID_ASK_SPREAD_PCT_BOUNDS)
        oi = int(_clamp(oi + 100, MIN_ATM_OPEN_INTEREST_BOUNDS))
        research_score = int(_clamp(research_score + 5, RESEARCH_CANDIDATE_MIN_SCORE_BOUNDS))

    overrides = {
        "MIN_RR": round(float(rr), 4),
        "MIN_KRONOS_AGREEMENT": round(float(kronos), 4),
        "MIN_EMPTY_SPACE_SCORE": int(es),
        "MAX_ATM_BID_ASK_SPREAD_PCT": round(float(spread), 4),
        "MIN_ATM_OPEN_INTEREST": int(oi),
        "ATR_COMPRESSION": round(float(atr), 4),
        "RANGE_COMPRESSION": round(float(rng), 4),
        "NO_TREND_SLOPE_ABS_MAX": round(float(slope), 6),
        "RESEARCH_CANDIDATE_MIN_SCORE": int(research_score),
    }
    return {
        "status": "ok",
        "samples": len(resolved),
        "duplicate_records_ignored": duplicate_records_ignored,
        "missed_winners": len(missed_winners),
        "correct_skips": len(correct_skips),
        "missed_win_rate": round(float(missed_win_rate), 4),
        "false_pos_losses": len(false_pos),
        "true_pos_wins": len(true_pos),
        "pass_loss_rate": round(float(pass_loss_rate), 4),
        "false_neg_by_stage": false_neg_by_stage,
        "false_pos_by_stage": false_pos_by_stage,
        "overrides": overrides,
    }


def apply_overrides(payload: dict, logger) -> dict:
    overrides = payload.get("overrides", {})
    if not overrides:
        return {"status": "no_overrides_applied"}
    TUNING_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    logger.info("AUTOTUNE_OVERRIDES_APPLIED: %s", json.dumps(overrides))
    return {"status": "applied", "path": str(OVERRIDES_PATH), "overrides": overrides}
