from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import OUTCOME_MIN_AGE_DAYS, OUTCOME_REVIEW_MAX_RECORDS, PRED_DAYS, REPORT_DIR, TIMEZONE
from ..data.market_data import fetch_intraday_bars
from ..data.synthetic_sessions import build_synthetic_sessions


def _evaluate_result(direction: str, entry: float, future_close: float) -> tuple[str, float]:
    if direction == "bullish":
        ret = ((future_close - entry) / entry) * 100.0
    else:
        ret = ((entry - future_close) / entry) * 100.0
    label = "win" if ret > 0 else "loss"
    return label, float(ret)


def review_pending_outcomes(records: list[dict], logger) -> tuple[list[dict], dict]:
    now = pd.Timestamp.now(tz=TIMEZONE)
    updated = 0
    skipped = 0
    resolved_live = 0
    resolved_counterfactual = 0

    pending = [r for r in records if r.get("outcome_status") == "pending"]
    pending = pending[:OUTCOME_REVIEW_MAX_RECORDS]

    for rec in pending:
        try:
            if not rec.get("direction") or rec.get("entry_price") is None:
                rec["outcome_status"] = "not_applicable"
                skipped += 1
                continue

            created = pd.Timestamp(rec.get("decision_ts"))
            if created.tzinfo is None:
                created = created.tz_localize(TIMEZONE)
            else:
                created = created.tz_convert(TIMEZONE)

            if (now - created).days < OUTCOME_MIN_AGE_DAYS:
                continue

            intraday = fetch_intraday_bars(rec["ticker"])
            synthetic, _ = build_synthetic_sessions(intraday, rec.get("anchor_hour", 20), rec.get("anchor_minute", 0), "30m", True)
            if synthetic.empty:
                continue

            base_idx = synthetic.index.get_indexer([created], method="nearest")
            if len(base_idx) == 0 or base_idx[0] < 0:
                continue
            start_pos = int(base_idx[0])
            target_pos = start_pos + PRED_DAYS
            if target_pos >= len(synthetic):
                continue

            future_close = float(synthetic.iloc[target_pos]["Close"])
            outcome, ret5 = _evaluate_result(rec["direction"], float(rec["entry_price"]), future_close)

            rec["outcome_status"] = "resolved"
            rec["outcome_label"] = outcome
            rec["outcome_ret_5bar_pct"] = ret5
            rec["outcome_resolved_at"] = pd.Timestamp.utcnow().isoformat()
            updated += 1
            if rec.get("counterfactual"):
                resolved_counterfactual += 1
            else:
                resolved_live += 1
        except Exception as exc:
            rec["outcome_error"] = str(exc)

    summary = {
        "pending_reviewed": len(pending),
        "resolved_now": updated,
        "resolved_live": resolved_live,
        "resolved_counterfactual": resolved_counterfactual,
        "marked_not_applicable": skipped,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "outcome_review_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("OUTCOME_REVIEW_SUMMARY: %s", json.dumps(summary))
    return records, summary
