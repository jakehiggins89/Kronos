from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import REPORT_DIR

DECISIONS_PATH = REPORT_DIR / "scan_decisions.jsonl"


def decision_fingerprint(record: dict) -> str:
    decision_ts = str(record.get("decision_ts") or record.get("created_at") or "")
    decision_day = decision_ts[:10]
    try:
        entry_price = round(float(record.get("entry_price") or 0.0), 4)
    except (TypeError, ValueError):
        entry_price = 0.0
    parts = (
        str(record.get("ticker") or "").upper(),
        str(record.get("mode") or ""),
        str(record.get("direction") or ""),
        f"{entry_price:.4f}",
        str(record.get("stage_failed") or "passed_all"),
        decision_day,
    )
    return "|".join(parts)


def _record_rank(record: dict) -> tuple[int, int]:
    status_rank = {"resolved": 3, "pending": 2, "not_applicable": 1}
    populated = sum(value is not None and value != "" for value in record.values())
    return status_rank.get(str(record.get("outcome_status")), 0), populated


def _is_missing(value) -> bool:
    return value is None or value == "" or value == {} or value == []


def _merge_enrichment(existing: dict, incoming: dict) -> tuple[dict, bool]:
    merged = dict(existing)
    changed = False
    for key, value in incoming.items():
        if key in {"created_at", "decision_ts"}:
            continue
        if _is_missing(value):
            continue
        if key not in merged or _is_missing(merged.get(key)):
            merged[key] = value
            changed = True
            continue
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            nested = dict(merged[key])
            for nested_key, nested_value in value.items():
                if not _is_missing(nested_value) and (nested_key not in nested or _is_missing(nested.get(nested_key))):
                    nested[nested_key] = nested_value
                    changed = True
            merged[key] = nested
    return merged, changed


def deduplicate_decisions(records: Iterable[dict]) -> tuple[list[dict], dict]:
    rows = list(records)
    selected: dict[str, tuple[int, dict]] = {}
    for index, record in enumerate(rows):
        payload = dict(record)
        fingerprint = decision_fingerprint(payload)
        existing = selected.get(fingerprint)
        if existing is None or _record_rank(payload) > _record_rank(existing[1]):
            selected[fingerprint] = (index, payload)
    clean = [payload for _index, payload in sorted(selected.values(), key=lambda item: item[0])]
    return clean, {
        "input_records": len(rows),
        "unique_records": len(clean),
        "duplicates_removed": max(0, len(rows) - len(clean)),
    }


def append_decision(record: dict) -> bool:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("created_at", pd.Timestamp.utcnow().isoformat())
    fingerprint = decision_fingerprint(payload)
    rows = load_decisions()
    for idx, existing in enumerate(rows):
        if decision_fingerprint(existing) != fingerprint:
            continue
        merged, changed = _merge_enrichment(existing, payload)
        if changed:
            rows[idx] = merged
            save_decisions(rows)
        return False
    with DECISIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return True


def load_decisions() -> list[dict]:
    if not DECISIONS_PATH.exists():
        return []
    rows = []
    with DECISIONS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def save_decisions(records: Iterable[dict]):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with DECISIONS_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
