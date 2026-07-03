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


def day_clustered_t(values: list[float], day_keys: list[str]) -> dict:
    """One-sample t against zero computed on per-day means.

    Trades entered the same day share the market factor and (with 5-bar
    horizons) most of their outcome window; the per-trade t treats them as
    independent and overstates confidence. Clustering by entry day is the
    cheapest honest correction: n becomes the number of distinct days.
    """
    buckets: dict[str, list[float]] = {}
    for value, day in zip(values, day_keys, strict=False):
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and day:
            buckets.setdefault(str(day), []).append(float(value))
    day_means = [float(np.mean(vals)) for vals in buckets.values()]
    return {
        "t_stat": round(t_statistic(day_means), 4),
        "n_days": len(day_means),
        "mean_of_day_means": round(float(np.mean(day_means)), 4) if day_means else 0.0,
    }


def _tie_break_key(row_id: str) -> int:
    # Deterministic pseudo-random tie order: with mass score ties (gate caps
    # collapse most scores onto a few values), stable sort would hand bucket
    # membership to input order - i.e. recency - biasing tercile/decile stats.
    import hashlib

    return int(hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:12], 16)


def tercile_lift(
    scores: list[float],
    outcomes: list[float],
    day_keys: list[str],
    row_ids: list[str] | None = None,
    n_boot: int = 400,
    seed: int = 7,
) -> dict:
    """Mean R per score tercile with a day-block bootstrap CI on the spread.

    Terciles (not deciles) because at n~900 each decile's SE (~0.12-0.15R)
    makes decile bar charts noise generators; ~300-trade buckets resolve the
    spreads this dataset can actually support.
    """
    rows = []
    for idx, (score, outcome) in enumerate(zip(scores, outcomes, strict=False)):
        if (
            isinstance(score, (int, float))
            and isinstance(outcome, (int, float))
            and math.isfinite(float(score))
            and math.isfinite(float(outcome))
        ):
            day = str(day_keys[idx]) if idx < len(day_keys) and day_keys[idx] else ""
            row_id = str(row_ids[idx]) if row_ids and idx < len(row_ids) else str(idx)
            rows.append((float(score), float(outcome), day, row_id))

    n = len(rows)
    if n < 30:
        return {"n": n, "insufficient": True}

    def bucket_means(sample: list[tuple[float, float, str, str]]) -> tuple[float, float, float]:
        ordered = sorted(sample, key=lambda r: (-r[0], _tie_break_key(r[3])))
        size = max(len(ordered) // 3, 1)  # guard: ordered[-0:] is the whole list
        top = [r[1] for r in ordered[:size]]
        bottom = [r[1] for r in ordered[-size:]]
        middle = [r[1] for r in ordered[size : len(ordered) - size]]
        return (
            float(np.mean(top)) if top else 0.0,
            float(np.mean(middle)) if middle else 0.0,
            float(np.mean(bottom)) if bottom else 0.0,
        )

    top_mean, mid_mean, bottom_mean = bucket_means(rows)
    spread = top_mean - bottom_mean

    by_day: dict[str, list[tuple[float, float, str, str]]] = {}
    for row in rows:
        by_day.setdefault(row[2], []).append(row)
    days = sorted(by_day)

    ci_low = ci_high = None
    if len(days) >= 6 and n_boot > 0:
        rng = np.random.default_rng(seed)
        spreads = []
        for _ in range(n_boot):
            drawn = rng.choice(len(days), size=len(days), replace=True)
            sample: list[tuple[float, float, str, str]] = []
            for day_idx in drawn:
                sample.extend(by_day[days[int(day_idx)]])
            if len(sample) < 9:
                continue
            boot_top, _, boot_bottom = bucket_means(sample)
            spreads.append(boot_top - boot_bottom)
        if spreads:
            ci_low = float(np.percentile(spreads, 2.5))
            ci_high = float(np.percentile(spreads, 97.5))

    return {
        "n": n,
        "insufficient": False,
        "top_mean_r": round(top_mean, 4),
        "middle_mean_r": round(mid_mean, 4),
        "bottom_mean_r": round(bottom_mean, 4),
        "spread_r": round(spread, 4),
        "spread_ci_low": round(ci_low, 4) if ci_low is not None else None,
        "spread_ci_high": round(ci_high, 4) if ci_high is not None else None,
        "distinct_days": len(days),
    }


def tail_retention(scores: list[float], outcomes: list[float], row_ids: list[str] | None = None, tail_r: float = 2.0) -> dict:
    """Share of right-tail (>= tail_r) trades captured by the top score tercile.

    Long-breakout edges live in <10% of trades (the exit-geometry sweep
    proved this one is right-tail driven). Any ranking/filtering layer that
    lifts mean R while under-capturing the tail is silently repeating what
    profit targets did - this is the veto diagnostic.
    """
    rows = []
    for idx, (score, outcome) in enumerate(zip(scores, outcomes, strict=False)):
        if (
            isinstance(score, (int, float))
            and isinstance(outcome, (int, float))
            and math.isfinite(float(score))
            and math.isfinite(float(outcome))
        ):
            row_id = str(row_ids[idx]) if row_ids and idx < len(row_ids) else str(idx)
            rows.append((float(score), float(outcome), row_id))

    n = len(rows)
    if n < 30:
        return {"n": n, "insufficient": True}

    ordered = sorted(rows, key=lambda r: (-r[0], _tie_break_key(r[2])))
    size = max(n // 3, 1)
    top_ids = {r[2] for r in ordered[:size]}
    tail = [r for r in rows if r[1] >= tail_r]
    tail_in_top = sum(1 for r in tail if r[2] in top_ids)
    expected_share = size / n if n else 0.0
    return {
        "n": n,
        "insufficient": False,
        "tail_r_threshold": tail_r,
        "tail_count": len(tail),
        "tail_in_top_tercile": tail_in_top,
        "expected_share": round(expected_share, 4),
        "observed_share": round(tail_in_top / len(tail), 4) if tail else None,
    }


def spearman_rank_ic(scores: list[float], outcomes: list[float], day_keys: list[str] | None = None) -> dict:
    """Spearman rank correlation of score vs outcome with a one-sided p-value.

    Uses every sample, so it detects ranking skill long before any absolute
    threshold accumulates enough signals (rho >= ~0.07 is detectable at
    n=600; a threshold gate needs 20+ signals it may never produce).

    When day_keys are provided, also reports a p-value computed against the
    number of distinct entry days: overlapping 5-bar outcomes and same-day
    cross-ticker correlation make the raw n anti-conservative.
    """
    pairs = []
    pair_days = []
    for idx, (s, o) in enumerate(zip(scores, outcomes, strict=False)):
        if (
            isinstance(s, (int, float))
            and isinstance(o, (int, float))
            and math.isfinite(float(s))
            and math.isfinite(float(o))
        ):
            pairs.append((float(s), float(o)))
            if day_keys is not None and idx < len(day_keys):
                pair_days.append(str(day_keys[idx]))
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
    result = {"ic": round(ic, 4), "p_value": round(_one_sided_p_from_t(t), 6), "n": n}

    if day_keys is not None:
        n_days = len({d for d in pair_days if d})
        result["n_days"] = n_days
        if n_days >= 3:
            n_eff = min(n, n_days)
            t_eff = bounded * math.sqrt((n_eff - 2) / (1.0 - bounded * bounded))
            result["p_value_day_clustered"] = round(_one_sided_p_from_t(t_eff), 6)
        else:
            result["p_value_day_clustered"] = 1.0
    return result
