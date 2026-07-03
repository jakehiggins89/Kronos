"""Within-direction expected-R meta-model (bullish P(win) ranker).

The composite edge score is a fail-closed evidence accumulator, not a
ranker: gate caps and flat penalties collapse most walk-forward scores onto
a handful of tied values (51% of bullish rows score exactly 0), so its
within-direction rank IC is structurally ~0. Post-hoc calibration of that
score cannot help - calibration is monotone and preserves rank order.

This module is the literature's answer (meta-labeling: Lopez de Prado 2018,
Joubert et al. JFDS 2022-2023): a SECONDARY model that predicts P(win) for
setups the primary system already surfaced, trained on the walk-forward
index, used only to RANK within a direction. It sits strictly downstream of
every gate - it can never create or promote a signal - so fail-closed
semantics are preserved by construction.

Model class is fixed at heavily regularized logistic regression: at
n_eff << n~6000 (overlapping 5-bar outcomes), events-per-parameter
arithmetic supports ~10 features and nothing fancier. Everything here is
numpy-only (the venv has no sklearn/scipy) and deterministic.

PRE-REGISTRATION (2026-07-02, per docs in trial_registry kind=calibration_trial):
one model class, one feature set, one acceptance rule - chosen BEFORE
seeing out-of-fold results, to keep the trial count honest:
  features   = META_FEATURE_KEYS (literature-backed, orthogonal to gates)
  model      = L2 logistic, lambda=1.0, IRLS, winsorize 1/99 + standardize
  train      = expanding window, refit every 21 calendar days, purge 9 days
  acceptance = OOF within-bullish rank IC >= 0.07 with day-clustered
               p <= 0.05, n >= 300, tercile spread CI low > 0, tail
               retention >= pro-rata, and OOF Brier < base-rate Brier
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .stats import spearman_rank_ic, tail_retention, tercile_lift

# Scale-free setup/context features present on every historical index record
# (feature_version=3). Chosen for literature support (relative volume and
# participation are the strongest published conditioners of short-horizon
# breakout outcomes; volatility regime and trend context next), NOT for
# in-sample performance. rr_ratio is deliberately excluded: degenerate
# cost-basis rows push it to astronomical values and its geometry is already
# spanned by box/breakout features.
META_FEATURE_KEYS: tuple[str, ...] = (
    "volume_expansion",
    "volume_percentile",
    "breakout_strength_pct",
    "close_position_in_box",
    "box_width_pct",
    "range_compression_ratio",
    "realized_volatility_pct",
    "no_trend_score",
    "doctrine_v2_score",
    "recent_return_pct",
)

META_L2_LAMBDA = 1.0
META_REFIT_EVERY_DAYS = 21
META_PURGE_DAYS = 9  # matches EDGE_EMBARGO_DAYS: outcome must be resolved
META_MIN_TRAIN = 300
META_ACCEPT_MIN_IC = 0.07
META_ACCEPT_MAX_P_DAY = 0.05
META_ACCEPT_MIN_N = 300
META_MODEL_VERSION = 1


def _finite(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def _feature_matrix(feature_dicts: list[dict], keys: tuple[str, ...]) -> np.ndarray:
    matrix = np.full((len(feature_dicts), len(keys)), np.nan, dtype=float)
    for row, features in enumerate(feature_dicts):
        if not isinstance(features, dict):
            continue
        for col, key in enumerate(keys):
            matrix[row, col] = _finite(features.get(key))
    return matrix


def fit_win_probability_model(
    feature_dicts: list[dict],
    r_multiples: list[float],
    l2_lambda: float = META_L2_LAMBDA,
    max_iter: int = 50,
) -> dict | None:
    """Fit the L2 logistic P(R > 0) model. Returns a JSON-safe model dict."""
    raw = _feature_matrix(feature_dicts, META_FEATURE_KEYS)
    r_values = np.array([_finite(r) for r in r_multiples], dtype=float)
    usable = np.isfinite(r_values)
    raw = raw[usable]
    r_values = r_values[usable]
    n = len(r_values)
    if n < META_MIN_TRAIN:
        return None
    y = (r_values > 0.0).astype(float)
    if y.sum() < 25 or (n - y.sum()) < 25:
        return None

    # Winsorize at train 1/99 percentiles, impute missing with train median,
    # then standardize - all parameters frozen into the model dict so live
    # prediction replays the exact transform.
    lo = np.nanpercentile(raw, 1, axis=0)
    hi = np.nanpercentile(raw, 99, axis=0)
    medians = np.nanmedian(raw, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    filled = np.where(np.isfinite(raw), raw, medians)
    clipped = np.clip(filled, lo, hi)
    mean = clipped.mean(axis=0)
    std = clipped.std(axis=0)
    std = np.where(std > 1e-12, std, 1.0)
    x = (clipped - mean) / std

    design = np.hstack([np.ones((n, 1)), x])
    weights = np.zeros(design.shape[1])
    penalty = np.full(design.shape[1], float(l2_lambda))
    penalty[0] = 0.0  # never shrink the intercept toward 0

    for _ in range(max_iter):
        p = _sigmoid(design @ weights)
        w_diag = np.maximum(p * (1.0 - p), 1e-9)
        gradient = design.T @ (y - p) - penalty * weights
        hessian = (design.T * w_diag) @ design + np.diag(penalty + 1e-9)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        weights = weights + step
        if float(np.max(np.abs(step))) < 1e-8:
            break

    wins = r_values[r_values > 0.0]
    losses = r_values[r_values <= 0.0]
    return {
        "version": META_MODEL_VERSION,
        "feature_keys": list(META_FEATURE_KEYS),
        "l2_lambda": float(l2_lambda),
        "intercept": float(weights[0]),
        "coefficients": [float(w) for w in weights[1:]],
        "winsor_low": [float(v) if math.isfinite(v) else 0.0 for v in lo],
        "winsor_high": [float(v) if math.isfinite(v) else 0.0 for v in hi],
        "medians": [float(v) for v in medians],
        "means": [float(v) for v in mean],
        "stds": [float(v) for v in std],
        "n_train": int(n),
        "base_rate": float(y.mean()),
        "e_r_win": float(wins.mean()) if wins.size else 0.0,
        "e_r_loss": float(losses.mean()) if losses.size else 0.0,
    }


def predict_win_probability(model: dict, features: dict) -> float | None:
    if not isinstance(model, dict) or not isinstance(features, dict):
        return None
    keys = model.get("feature_keys") or []
    required = ("medians", "winsor_low", "winsor_high", "means", "stds", "coefficients", "intercept")
    if not keys or any(model.get(field) is None for field in required):
        return None
    if any(len(model[field]) != len(keys) for field in required[:-1]):
        return None
    values = np.array([_finite(features.get(key)) for key in keys], dtype=float)
    medians = np.array(model["medians"], dtype=float)
    filled = np.where(np.isfinite(values), values, medians)
    clipped = np.clip(filled, np.array(model["winsor_low"]), np.array(model["winsor_high"]))
    x = (clipped - np.array(model["means"])) / np.array(model["stds"])
    z = float(model["intercept"]) + float(np.dot(np.array(model["coefficients"]), x))
    return float(_sigmoid(np.array([z]))[0])


def predict_expected_r(model: dict, features: dict) -> float | None:
    """E[R] = p*E[R|win] + (1-p)*E[R|loss], conditionals pooled from training.

    The conditional means are exit-geometry properties, not score
    properties, so expected_r is a monotone transform of p - ranking by
    either is equivalent; expected_r is reported because R units are what
    the audit gates speak.
    """
    p = predict_win_probability(model, features)
    if p is None:
        return None
    return float(p * float(model.get("e_r_win", 0.0)) + (1.0 - p) * float(model.get("e_r_loss", 0.0)))


def _brier(probabilities: list[float], labels: list[int]) -> float:
    pairs = [(p, y) for p, y in zip(probabilities, labels, strict=False) if p is not None]
    if not pairs:
        return 1.0
    return float(np.mean([(p - y) ** 2 for p, y in pairs]))


def walk_forward_calibration(
    records: Iterable[Any],
    direction: str = "bullish",
    refit_every_days: int = META_REFIT_EVERY_DAYS,
    purge_days: int = META_PURGE_DAYS,
) -> dict:
    """Expanding-window out-of-fold evaluation of the meta-model.

    Each record is predicted by a model trained ONLY on records whose entry
    is at least `purge_days` calendar days older (their 5-bar outcomes are
    resolved before the prediction time), refit on a fixed calendar cadence.
    Returns OOF metrics, the pre-registered acceptance verdict, and the
    final model fit on all data (for live advisory scoring).
    """
    import pandas as pd

    rows = []
    for record in records:
        rec_direction = getattr(record, "direction", None) or (record.get("direction") if isinstance(record, dict) else None)
        if str(rec_direction) != direction:
            continue
        features = getattr(record, "features", None) if not isinstance(record, dict) else record.get("features")
        timestamp = getattr(record, "timestamp", None) if not isinstance(record, dict) else record.get("timestamp")
        r_multiple = getattr(record, "r_multiple", None) if not isinstance(record, dict) else record.get("r_multiple")
        ticker = getattr(record, "ticker", "") if not isinstance(record, dict) else record.get("ticker", "")
        ts = pd.to_datetime(timestamp, errors="coerce", utc=True)
        r_value = _finite(r_multiple)
        if pd.isna(ts) or not isinstance(features, dict) or not math.isfinite(r_value):
            continue
        rows.append({"ts": ts, "ticker": str(ticker), "timestamp": str(timestamp), "features": features, "r": r_value})

    rows.sort(key=lambda row: row["ts"])
    result: dict[str, Any] = {
        "direction": direction,
        "model_class": "l2_logistic_irls",
        "model_version": META_MODEL_VERSION,
        "feature_keys": list(META_FEATURE_KEYS),
        "config": {
            "l2_lambda": META_L2_LAMBDA,
            "refit_every_days": refit_every_days,
            "purge_days": purge_days,
            "min_train": META_MIN_TRAIN,
        },
        "n_records": len(rows),
        "n_evaluated": 0,
        "predictions": {},
        "final_model": None,
    }
    if len(rows) < META_MIN_TRAIN + 50:
        result["metrics"] = {"insufficient": True}
        result["acceptance"] = {"passed": False, "reason": "insufficient_records"}
        return result

    purge = pd.Timedelta(days=purge_days)
    refit_interval = pd.Timedelta(days=refit_every_days)
    model = None
    model_fit_ts = None
    predictions: list[float] = []
    outcomes: list[float] = []
    labels: list[int] = []
    day_keys: list[str] = []
    row_ids: list[str] = []
    prediction_map: dict[str, float] = {}

    for idx, row in enumerate(rows):
        needs_refit = model_fit_ts is None or (row["ts"] - model_fit_ts) >= refit_interval
        if needs_refit:
            train = [r for r in rows if r["ts"] <= row["ts"] - purge]
            if len(train) >= META_MIN_TRAIN:
                candidate_model = fit_win_probability_model(
                    [r["features"] for r in train], [r["r"] for r in train]
                )
                if candidate_model is not None:
                    model = candidate_model
                    model_fit_ts = row["ts"]
        if model is None:
            continue
        p_win = predict_win_probability(model, row["features"])
        if p_win is None:
            continue
        predictions.append(p_win)
        outcomes.append(row["r"])
        labels.append(1 if row["r"] > 0 else 0)
        day_keys.append(row["ts"].strftime("%Y-%m-%d"))
        row_id = f"{row['ticker']}|{row['timestamp']}"
        row_ids.append(row_id)
        prediction_map[row_id] = p_win

    n_eval = len(predictions)
    result["n_evaluated"] = n_eval
    result["predictions"] = prediction_map
    if n_eval < META_ACCEPT_MIN_N:
        result["metrics"] = {"insufficient": True, "n_evaluated": n_eval}
        result["acceptance"] = {"passed": False, "reason": "insufficient_out_of_fold_predictions"}
        return result

    ic = spearman_rank_ic(predictions, outcomes, day_keys=day_keys)
    lift = tercile_lift(predictions, outcomes, day_keys, row_ids=row_ids)
    tail = tail_retention(predictions, outcomes, row_ids=row_ids)
    oof_brier = _brier(predictions, labels)
    base_rate = float(np.mean(labels))
    base_brier = float(np.mean([(base_rate - y) ** 2 for y in labels]))

    metrics = {
        "insufficient": False,
        "n_evaluated": n_eval,
        "rank_ic_r": ic,
        "tercile_lift": lift,
        "tail_retention": tail,
        "oof_brier": round(oof_brier, 6),
        "base_rate_brier": round(base_brier, 6),
        "beats_naive_brier": oof_brier < base_brier,
        "mean_p_win": round(float(np.mean(predictions)), 4),
        "realized_win_rate": round(base_rate, 4),
    }
    result["metrics"] = metrics

    criteria = {
        "ic_at_least_0.07": float(ic.get("ic", 0.0)) >= META_ACCEPT_MIN_IC,
        "day_clustered_p_at_most_0.05": float(ic.get("p_value_day_clustered", 1.0)) <= META_ACCEPT_MAX_P_DAY,
        "n_at_least_300": n_eval >= META_ACCEPT_MIN_N,
        "tercile_spread_ci_low_positive": bool(
            not lift.get("insufficient") and lift.get("spread_ci_low") is not None and lift["spread_ci_low"] > 0
        ),
        "tail_retention_at_least_pro_rata": bool(
            tail.get("insufficient")
            or tail.get("observed_share") is None
            or tail["observed_share"] >= tail["expected_share"]
        ),
        "beats_naive_brier": oof_brier < base_brier,
    }
    result["acceptance"] = {"passed": all(criteria.values()), "criteria": criteria}

    result["final_model"] = fit_win_probability_model(
        [row["features"] for row in rows], [row["r"] for row in rows]
    )
    return result
