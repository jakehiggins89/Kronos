"""Shared small-sample statistics for edge evidence and adaptive policy."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def wilson_lower_bound(wins: int, total: int, z: float = 1.28) -> float:
    """Conservative lower bound on a binomial proportion."""
    if total <= 0:
        return 0.0
    p_hat = wins / total
    z2 = z * z
    denominator = 1.0 + (z2 / total)
    center = p_hat + (z2 / (2.0 * total))
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + (z2 / (4.0 * total))) / total)
    return max(0.0, (center - margin) / denominator)


def t_statistic(values: list[float]) -> float:
    """One-sample t statistic against zero mean."""
    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    n = len(finite)
    if n < 2:
        return 0.0
    mean = float(np.mean(finite))
    sd = float(np.std(finite, ddof=1))
    if sd <= 1e-12:
        return 0.0
    return mean / (sd / math.sqrt(n))


def _one_sided_p_from_t(t: float) -> float:
    # Normal approximation; adequate at the sample sizes gating decisions here.
    return 0.5 * (1.0 - math.erf(t / math.sqrt(2.0)))


def spearman_rank_ic(scores: list[float], outcomes: list[float]) -> dict:
    """Spearman rank correlation of score vs outcome with a one-sided p-value.

    Uses every sample, so it detects ranking skill long before any absolute
    threshold accumulates enough signals (rho >= ~0.07 is detectable at
    n=600; a threshold gate needs 20+ signals it may never produce).
    """
    pairs = [
        (float(s), float(o))
        for s, o in zip(scores, outcomes, strict=False)
        if isinstance(s, (int, float))
        and isinstance(o, (int, float))
        and math.isfinite(float(s))
        and math.isfinite(float(o))
    ]
    n = len(pairs)
    if n < 3:
        return {"ic": 0.0, "p_value": 1.0, "n": n}

    score_ranks = pd.Series([p[0] for p in pairs]).rank(method="average")
    outcome_ranks = pd.Series([p[1] for p in pairs]).rank(method="average")
    if score_ranks.std(ddof=0) <= 1e-12 or outcome_ranks.std(ddof=0) <= 1e-12:
        return {"ic": 0.0, "p_value": 1.0, "n": n}

    ic = float(np.corrcoef(score_ranks, outcome_ranks)[0, 1])
    if not math.isfinite(ic):
        return {"ic": 0.0, "p_value": 1.0, "n": n}
    bounded = min(max(ic, -0.999999), 0.999999)
    t = bounded * math.sqrt((n - 2) / (1.0 - bounded * bounded))
    return {"ic": round(ic, 4), "p_value": round(_one_sided_p_from_t(t), 6), "n": n}
