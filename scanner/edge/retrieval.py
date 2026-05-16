from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..edge.features import extract_edge_features
from ..strategy.empty_space import score_empty_space
from ..strategy.potter_box import detect_potter_box, score_potter_research_candidate


@dataclass
class EdgeRecord:
    ticker: str
    timestamp: str
    direction: str
    features: dict[str, Any]
    outcome_return_pct: float
    outcome_label: str
    r_multiple: float
    mae_pct: float
    mfe_pct: float


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts


def _numeric_feature_keys(query_features: dict, candidate_features: dict) -> list[str]:
    keys = []
    excluded = {"feature_version", "bar_count"}
    for key in sorted(set(query_features).intersection(candidate_features)):
        if key in excluded:
            continue
        qv = query_features.get(key)
        cv = candidate_features.get(key)
        if isinstance(qv, bool) or isinstance(cv, bool):
            continue
        if isinstance(qv, (int, float)) and isinstance(cv, (int, float)):
            if math.isfinite(float(qv)) and math.isfinite(float(cv)):
                keys.append(key)
    return keys


def _distance(query_features: dict, candidate_features: dict) -> float:
    keys = _numeric_feature_keys(query_features, candidate_features)
    if not keys:
        return float("inf")
    pieces = []
    for key in keys:
        qv = float(query_features[key])
        cv = float(candidate_features[key])
        scale = max(abs(qv), abs(cv), 1.0)
        pieces.append(((qv - cv) / scale) ** 2)
    return float(np.sqrt(np.mean(pieces)))


def _future_outcome(
    bars: pd.DataFrame,
    idx: int,
    horizon: int,
    direction: str,
    entry: float,
    risk_pct: float,
) -> tuple[float, str, float, float, float]:
    future = bars.iloc[idx + 1 : idx + 1 + horizon]
    if future.empty or entry <= 0:
        return 0.0, "loss", 0.0, 0.0, 0.0

    final_close = _finite_float(future["Close"].iloc[-1])
    if direction == "bullish":
        ret_pct = ((final_close - entry) / entry) * 100.0
        mae_pct = ((_finite_float(future["Low"].min()) - entry) / entry) * 100.0
        mfe_pct = ((_finite_float(future["High"].max()) - entry) / entry) * 100.0
    else:
        ret_pct = ((entry - final_close) / entry) * 100.0
        mae_pct = ((entry - _finite_float(future["High"].max())) / entry) * 100.0
        mfe_pct = ((entry - _finite_float(future["Low"].min())) / entry) * 100.0

    r_multiple = ret_pct / max(abs(risk_pct), 0.01)
    return float(ret_pct), "win" if ret_pct > 0 else "loss", float(r_multiple), float(mae_pct), float(mfe_pct)


def build_edge_records_from_bars(
    ticker: str,
    bars: pd.DataFrame,
    horizon: int = 5,
    min_history: int = 35,
) -> list[EdgeRecord]:
    if bars is None or len(bars) <= min_history + horizon:
        return []
    clean = bars.sort_index().copy()
    records: list[EdgeRecord] = []

    for idx in range(min_history, len(clean) - horizon):
        window = clean.iloc[: idx + 1]
        pb = detect_potter_box(ticker, window)
        direction = pb.direction
        research = score_potter_research_candidate(pb, window)
        if direction not in {"bullish", "bearish"}:
            direction = research.get("direction")
        if direction not in {"bullish", "bearish"}:
            continue

        entry = _finite_float(pb.breakout_close)
        if entry <= 0:
            continue
        es = score_empty_space(window, direction, entry, pb.cost_basis or entry)
        features = extract_edge_features(ticker, window, pb, es)
        features["direction"] = direction
        features["research_score"] = _finite_float(research.get("score"))
        features["research_passed"] = 1.0 if research.get("passed") else 0.0
        risk_pct = _finite_float(features.get("risk_pct"))
        ret_pct, label, r_multiple, mae_pct, mfe_pct = _future_outcome(clean, idx, horizon, direction, entry, risk_pct)
        records.append(
            EdgeRecord(
                ticker=ticker,
                timestamp=str(features.get("timestamp") or pd.Timestamp(clean.index[idx]).isoformat()),
                direction=direction,
                features=features,
                outcome_return_pct=ret_pct,
                outcome_label=label,
                r_multiple=r_multiple,
                mae_pct=mae_pct,
                mfe_pct=mfe_pct,
            )
        )
    return records


def find_analogs(
    query_features: dict,
    records: Iterable[EdgeRecord | dict],
    k: int = 7,
    embargo_days: int = 5,
) -> list[dict[str, Any]]:
    query_ticker = str(query_features.get("ticker", "")).upper()
    query_ts = _parse_ts(query_features.get("timestamp"))
    scored = []

    for raw in records:
        record = raw if isinstance(raw, EdgeRecord) else EdgeRecord(**raw)
        candidate_ts = _parse_ts(record.timestamp)
        if (
            query_ticker
            and record.ticker.upper() == query_ticker
            and query_ts is not None
            and candidate_ts is not None
            and abs((query_ts - candidate_ts).days) < embargo_days
        ):
            continue
        dist = _distance(query_features, record.features)
        if not math.isfinite(dist):
            continue
        payload = asdict(record)
        payload["distance"] = dist
        scored.append(payload)

    scored.sort(key=lambda row: row["distance"])
    return scored[:k]


def save_edge_index(records: Iterable[EdgeRecord], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(record) for record in records], indent=2), encoding="utf-8")
    return output_path


def load_edge_index(path: str | Path) -> list[EdgeRecord]:
    input_path = Path(path)
    if not input_path.exists():
        return []
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [EdgeRecord(**row) for row in payload if isinstance(row, dict)]
