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


def _is_numeric_feature(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _record_payload(record: EdgeRecord) -> dict[str, Any]:
    return asdict(record)


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
    allow_future: bool = True,
) -> list[dict[str, Any]]:
    if isinstance(records, EdgeAnalogIndex):
        return records.find_analogs(query_features, k=k, embargo_days=embargo_days, allow_future=allow_future)

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
        if not allow_future and query_ts is not None and candidate_ts is not None and candidate_ts >= query_ts:
            continue
        dist = _distance(query_features, record.features)
        if not math.isfinite(dist):
            continue
        payload = _record_payload(record)
        payload["distance"] = dist
        scored.append(payload)

    scored.sort(key=lambda row: row["distance"])
    return scored[:k]


class EdgeAnalogIndex:
    """Vectorized in-memory analog search over EdgeRecord feature dictionaries."""

    _excluded_keys = {"feature_version", "bar_count"}

    def __init__(self, records: Iterable[EdgeRecord | dict]):
        self.records = [raw if isinstance(raw, EdgeRecord) else EdgeRecord(**raw) for raw in records]
        self._tickers = [record.ticker.upper() for record in self.records]
        self._timestamps = [_parse_ts(record.timestamp) for record in self.records]
        self._payloads: list[dict[str, Any] | None] = [None] * len(self.records)
        self._keys = self._feature_keys(self.records)
        self._matrix = self._feature_matrix(self.records, self._keys)

    def find_analogs(
        self,
        query_features: dict,
        k: int = 7,
        embargo_days: int = 5,
        allow_future: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.records or k <= 0:
            return []

        distances = self._distances(query_features)
        self._apply_time_filters(distances, query_features, embargo_days, allow_future)
        finite_idx = np.flatnonzero(np.isfinite(distances))
        if finite_idx.size == 0:
            return []

        limit = min(k, finite_idx.size)
        if finite_idx.size > limit:
            candidate_idx = finite_idx[np.argpartition(distances[finite_idx], limit - 1)[:limit]]
        else:
            candidate_idx = finite_idx
        ordered_idx = candidate_idx[np.argsort(distances[candidate_idx], kind="stable")]
        return [self._payload_with_distance(int(idx), float(distances[idx])) for idx in ordered_idx]

    def _distances(self, query_features: dict) -> np.ndarray:
        distances = np.full(len(self.records), np.inf, dtype=float)
        if not self._keys:
            return distances

        query_vector = np.full(len(self._keys), np.nan, dtype=float)
        for idx, key in enumerate(self._keys):
            value = query_features.get(key)
            if _is_numeric_feature(value):
                query_vector[idx] = float(value)
        if not np.isfinite(query_vector).any():
            return distances

        valid = np.isfinite(self._matrix) & np.isfinite(query_vector)
        counts = valid.sum(axis=1)
        usable = counts > 0
        if not usable.any():
            return distances

        scale = np.maximum.reduce([np.abs(self._matrix), np.broadcast_to(np.abs(query_vector), self._matrix.shape), np.ones_like(self._matrix)])
        pieces = np.where(valid, ((self._matrix - query_vector) / scale) ** 2, 0.0)
        distances[usable] = np.sqrt(pieces[usable].sum(axis=1) / counts[usable])
        return distances

    def _apply_time_filters(
        self,
        distances: np.ndarray,
        query_features: dict,
        embargo_days: int,
        allow_future: bool,
    ) -> None:
        query_ticker = str(query_features.get("ticker", "")).upper()
        query_ts = _parse_ts(query_features.get("timestamp"))
        if query_ts is None:
            return
        for idx, (ticker, candidate_ts) in enumerate(zip(self._tickers, self._timestamps, strict=False)):
            if candidate_ts is None:
                continue
            if not allow_future and candidate_ts >= query_ts:
                distances[idx] = np.inf
                continue
            if query_ticker and ticker == query_ticker and abs((query_ts - candidate_ts).days) < embargo_days:
                distances[idx] = np.inf

    def _payload_with_distance(self, idx: int, distance: float) -> dict[str, Any]:
        payload = self._payloads[idx]
        if payload is None:
            payload = _record_payload(self.records[idx])
            self._payloads[idx] = payload
        out = dict(payload)
        out["distance"] = distance
        return out

    @classmethod
    def _feature_keys(cls, records: list[EdgeRecord]) -> list[str]:
        keys: set[str] = set()
        for record in records:
            for key, value in record.features.items():
                if key not in cls._excluded_keys and _is_numeric_feature(value):
                    keys.add(key)
        return sorted(keys)

    @staticmethod
    def _feature_matrix(records: list[EdgeRecord], keys: list[str]) -> np.ndarray:
        matrix = np.full((len(records), len(keys)), np.nan, dtype=float)
        for row_idx, record in enumerate(records):
            for col_idx, key in enumerate(keys):
                value = record.features.get(key)
                if _is_numeric_feature(value):
                    matrix[row_idx, col_idx] = float(value)
        return matrix


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
