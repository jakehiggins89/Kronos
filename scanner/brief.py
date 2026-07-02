"""Operator daily brief: one command, plain English, verdict first.

Reads the latest report artifacts (no network, no model loads) and renders
what changed, how far each evidence gate is from unlocking, and the single
highest-leverage next action.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import REPORT_DIR

# Plain-English translations for the audit's blocker/warning codes, with the
# concrete fix so the brief always ends in an action, not a mood.
_ISSUE_GUIDE = {
    "validation_threshold_55_unsupported": (
        "The absolute score-55 gate has no supporting signals",
        "expected while scores stay compressed; the ranking gate is the realistic path",
    ),
    "ranking_evidence_unsupported": (
        "The score does not yet rank outcomes strongly enough out-of-sample",
        "keep daily research_ops running so walk-forward samples accumulate",
    ),
    "options_data_not_execution_grade": (
        "Options quotes are indicative (free Alpaca feed), never execution-grade",
        "open a free Tradier brokerage account (real-time OPRA + open interest) or pay for Alpaca Algo Trader Plus",
    ),
    "options_liquidity_missing": (
        "Open interest / volume / spread fields are missing on some candidates",
        "same fix as execution-grade options data",
    ),
    "low_feed_confidence": (
        "Equity bars come from the free IEX-only feed",
        "acceptable for research; full-SIP data (Alpaca ATP or Polygon Starter) clears it",
    ),
    "no_current_actionable_candidates": (
        "Nothing on the watchlist is near a qualifying setup today",
        "normal; the scanner is supposed to be quiet most days",
    ),
    "bearish_edge_negative": (
        "Bearish setups have negative expectancy in validation",
        "bearish promotion stays blocked until bearish evidence turns positive",
    ),
    "bullish_edge_negative": (
        "Bullish setups have negative expectancy in validation",
        "bullish promotion stays blocked until bullish evidence turns positive",
    ),
    "promoted_candidates_direction_blocked": (
        "Promotions exist only in a direction whose validated edge is negative",
        "treated as research-only until that direction proves itself",
    ),
}

_READINESS_LINE = {
    "blocked": "NOT live-ready. Evidence gates are failing; live alerting stays off.",
    "watch_only": "Evidence gates pass but nothing is actionable today. Watch only.",
    "research_only": "Evidence gates pass; research candidates only. No live alerts.",
    "paper_trade_only": "Evidence supports PAPER trading the promoted candidates. Still not real money.",
}


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _fmt(value: Any, digits: int = 2, missing: str = "n/a") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    return f"{number:.{digits}f}"


def _gate_progress(audit: dict, validation: dict) -> list[str]:
    lines = []
    ranking = audit.get("checks", {}).get("ranking_evidence", {})
    value = ranking.get("value", {}) if isinstance(ranking.get("value"), dict) else {}
    status = "PASS" if ranking.get("passed") else "not yet"
    lines.append(
        f"- Ranking gate ({status}): rank IC {_fmt(value.get('rank_ic'), 3)} "
        f"(need >= {_fmt(value.get('min_rank_ic'), 2)}, p {_fmt(value.get('rank_ic_p_value'), 3)}), "
        f"top-decile signals {int(value.get('top_decile_signals', 0))}/{int(value.get('min_signals', 20))}, "
        f"avg R {_fmt(value.get('top_decile_average_r'))}, t {_fmt(value.get('top_decile_t_stat'))}, "
        f"Wilson-LB precision {_fmt(value.get('top_decile_wilson_lb_precision'))} (need >= 0.45)"
    )
    legacy = audit.get("checks", {}).get("validation_threshold", {})
    legacy_value = legacy.get("value", {}) if isinstance(legacy.get("value"), dict) else {}
    lines.append(
        f"- Legacy threshold-{legacy_value.get('threshold', 55)} gate "
        f"({'PASS' if legacy.get('passed') else 'not yet'}): "
        f"{int(legacy_value.get('signal_count', 0))}/{int(legacy_value.get('min_signals', 20))} signals"
    )
    directions = validation.get("by_direction", {})
    if isinstance(directions, dict) and directions:
        parts = []
        blocked = set(audit.get("summary", {}).get("blocked_directions", []))
        for name in ("bullish", "bearish"):
            block = directions.get(name)
            if not isinstance(block, dict):
                continue
            tag = " BLOCKED" if name in blocked else ""
            parts.append(
                f"{name} n={int(block.get('signal_count', 0))} "
                f"avgR {_fmt(block.get('average_r_multiple'))}{tag}"
            )
        if parts:
            lines.append(f"- Directions: {'; '.join(parts)}")
    return lines


def _scan_summary(scan: dict) -> list[str]:
    candidates = [row for row in scan.get("candidates", []) if isinstance(row, dict)]
    if not candidates:
        return ["- No scan data yet; run research_ops or edge_scan."]
    counts: dict[str, int] = {}
    for row in candidates:
        key = str(row.get("recommendation") or row.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    ordered = ", ".join(f"{count} {name}" for name, count in sorted(counts.items(), key=lambda kv: -kv[1]))
    lines = [f"- {len(candidates)} tickers scanned: {ordered}"]
    scored = [row for row in candidates if row.get("edge_score") is not None]
    for row in scored[:3]:
        blockers = row.get("blocking_reasons") or []
        suffix = f" -- blocked by {', '.join(blockers[:3])}" if blockers else ""
        lines.append(
            f"- {row.get('ticker')}: {row.get('direction', '?')} edge {_fmt(row.get('edge_score'))}{suffix}"
        )
    return lines


def _learning_summary(policy: dict, diagnostic: dict) -> list[str]:
    lines = []
    research = policy.get("research_candidates", {})
    lines.append(
        f"- Journal: {int(research.get('resolved', 0))} resolved research candidates "
        f"({int(research.get('resolved_outcomes', {}).get('win', 0))}W/"
        f"{int(research.get('resolved_outcomes', {}).get('loss', 0))}L, "
        f"{_fmt(float(research.get('resolved_win_rate', 0.0)) * 100, 1)}% WR), "
        f"{int(diagnostic.get('research_candidates', {}).get('pending', 0))} pending"
    )
    recommendation = policy.get("recommendation", {})
    lines.append(
        f"- Policy: {recommendation.get('status', 'unknown')} "
        f"(threshold {research.get('current_threshold', '?')}) -- {recommendation.get('reason', '')}"
    )
    lift = policy.get("kronos_lift", {})
    if int(lift.get("rows_with_kronos", 0)) > 0:
        agree = lift.get("agree", {})
        disagree = lift.get("disagree", {})
        lines.append(
            f"- Kronos lift: {int(lift.get('rows_with_kronos', 0))} scored -- agree "
            f"{_fmt(float(agree.get('win_rate', 0.0)) * 100, 0)}% WR (n={int(agree.get('signal_count', 0))}) vs "
            f"disagree {_fmt(float(disagree.get('win_rate', 0.0)) * 100, 0)}% WR (n={int(disagree.get('signal_count', 0))})"
        )
    else:
        lines.append("- Kronos lift: no scored research candidates yet (accumulating from today forward)")
    doctrine = policy.get("doctrine_v2", {})
    if int(doctrine.get("resolved", 0)) > 0:
        current = doctrine.get("current_threshold", {})
        lines.append(
            f"- Doctrine v2: {int(doctrine.get('resolved', 0))} resolved, baseline cohort "
            f"{int(current.get('wins', 0))}W/{int(current.get('losses', 0))}L avg {_fmt(current.get('average_return_pct'))}%"
        )
    return lines


def _issues(audit: dict) -> list[str]:
    lines = []
    for code in list(audit.get("blockers", [])) + list(audit.get("warnings", [])):
        explanation, fix = _ISSUE_GUIDE.get(str(code), (str(code), "see scanner/README.md"))
        lines.append(f"- {code}: {explanation}. Fix: {fix}.")
    return lines or ["- None. All gates green."]


def _next_action(audit: dict, policy: dict) -> str:
    warnings = set(audit.get("warnings", []))
    blockers = set(audit.get("blockers", []))
    recommendation = policy.get("recommendation", {})
    if recommendation.get("status") == "loosen_research_threshold":
        return (
            "Confirm the pending research-threshold loosening on tomorrow's research_ops run "
            "so the journal starts refilling."
        )
    if "options_data_not_execution_grade" in warnings:
        return (
            "Data decision: open a free Tradier brokerage account (real-time OPRA options + open interest, $0) "
            "or upgrade Alpaca to Algo Trader Plus ($99/mo). This is the only blocker code cannot fix."
        )
    if blockers:
        return "Keep the daily research_ops cadence; evidence gates need more resolved samples."
    return "Review promoted candidates and paper-trade them per the audit."


def build_daily_brief(report_dir: Path | None = None) -> tuple[str, dict]:
    base = Path(report_dir) if report_dir is not None else REPORT_DIR
    audit = _read_json(base / "edge_audit_report.json")
    validation = _read_json(base / "edge_validation_report.json")
    policy = _read_json(base / "adaptive_policy_report.json")
    diagnostic = _read_json(base / "zero_result_diagnostic.json")
    scan = _read_json(base / "edge_scan_report.json")

    readiness = str(audit.get("readiness", "unknown"))
    today = pd.Timestamp.now(tz="America/New_York").date().isoformat()

    lines = [
        f"# Kronos Daily Brief -- {today}",
        "",
        "## Verdict",
        f"**{readiness}** -- {_READINESS_LINE.get(readiness, 'No audit found; run research_ops first.')}",
        "",
        "## Evidence progress",
        *_gate_progress(audit, validation),
        "",
        "## Today's scan",
        *_scan_summary(scan),
        "",
        "## Learning loop",
        *_learning_summary(policy, diagnostic),
        "",
        "## Open issues",
        *_issues(audit),
        "",
        "## Next action",
        f"{_next_action(audit, policy)}",
        "",
    ]
    markdown = "\n".join(lines)
    payload = {
        "mode": "brief",
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "readiness": readiness,
        "next_action": _next_action(audit, policy),
    }
    return markdown, payload


def run_brief(logger, report_dir: Path | None = None) -> dict:
    base = Path(report_dir) if report_dir is not None else REPORT_DIR
    markdown, payload = build_daily_brief(base)
    base.mkdir(parents=True, exist_ok=True)
    output_path = base / "daily_brief.md"
    output_path.write_text(markdown, encoding="utf-8")
    payload["path"] = str(output_path.resolve())
    print(markdown)
    if logger is not None:
        logger.info("DAILY_BRIEF_SAVED: %s", payload["path"])
    return payload
