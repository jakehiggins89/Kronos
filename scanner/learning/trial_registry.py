"""Append-only registry of every tuning trial the system evaluates or applies.

Every threshold change is one more draw from the multiple-testing urn; the
deflated-Sharpe haircut needs the true trial count, so it is recorded as a
fact instead of reconstructed from memory.
"""

from __future__ import annotations

import json

import pandas as pd

from ..config import REPORT_DIR

TRIAL_REGISTRY_PATH = REPORT_DIR / "trial_registry.jsonl"


def record_trial(kind: str, payload: dict) -> None:
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        row = {"recorded_at": pd.Timestamp.utcnow().isoformat(), "kind": kind, **payload}
        with TRIAL_REGISTRY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # The registry is telemetry; never let it break a tuning run.
        pass
