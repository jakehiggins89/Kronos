from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import REPORT_DIR

DECISIONS_PATH = REPORT_DIR / "scan_decisions.jsonl"


def append_decision(record: dict):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("created_at", pd.Timestamp.utcnow().isoformat())
    with DECISIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
