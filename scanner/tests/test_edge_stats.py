import numpy as np

from scanner.edge.stats import (
    day_clustered_t,
    spearman_rank_ic,
    tail_retention,
    tercile_lift,
)


def _synthetic_rows(n=120, ic_strength=0.9, seed=3):
    rng = np.random.default_rng(seed)
    scores = rng.normal(size=n)
    outcomes = ic_strength * scores + rng.normal(scale=0.5, size=n)
    days = [f"2026-01-{(i % 20) + 1:02d}" for i in range(n)]
    ids = [f"T{i}" for i in range(n)]
    return list(scores), list(outcomes), days, ids


def test_day_clustered_t_uses_days_not_trades():
    # 100 identical trades on 2 days must not manufacture a huge t-stat.
    values = [1.0] * 50 + [0.5] * 50
    days = ["2026-01-05"] * 50 + ["2026-01-06"] * 50
    result = day_clustered_t(values, days)
    assert result["n_days"] == 2
    # 2 day-means -> t is computable but tiny-n; the point is n_days honesty.
    assert result["mean_of_day_means"] == 0.75


def test_spearman_day_clustered_p_is_more_conservative():
    scores, outcomes, days, _ = _synthetic_rows()
    result = spearman_rank_ic(scores, outcomes, day_keys=days)
    assert result["n"] == 120
    assert result["n_days"] == 20
    assert result["p_value_day_clustered"] >= result["p_value"]


def test_tercile_lift_detects_real_spread():
    scores, outcomes, days, ids = _synthetic_rows()
    result = tercile_lift(scores, outcomes, days, row_ids=ids)
    assert result["insufficient"] is False
    assert result["spread_r"] > 0
    assert result["spread_ci_low"] is not None
    assert result["spread_ci_low"] > 0  # strong synthetic signal


def test_tercile_lift_insufficient_below_30():
    result = tercile_lift([1.0] * 10, [0.5] * 10, ["2026-01-01"] * 10)
    assert result["insufficient"] is True


def test_tercile_lift_is_deterministic():
    scores, outcomes, days, ids = _synthetic_rows()
    a = tercile_lift(scores, outcomes, days, row_ids=ids)
    b = tercile_lift(scores, outcomes, days, row_ids=ids)
    assert a == b


def test_tercile_lift_mass_ties_do_not_bias_by_input_order():
    # 90 zero-score rows where the LAST 30 in input order carry all the R:
    # stable sort would put early rows in the top tercile deterministically.
    scores = [0.0] * 90
    outcomes = [0.0] * 60 + [2.0] * 30
    days = [f"2026-02-{(i % 15) + 1:02d}" for i in range(90)]
    ids = [f"X{i}" for i in range(90)]
    result = tercile_lift(scores, outcomes, days, row_ids=ids)
    # With hash tie-breaking the tail spreads across buckets instead of
    # landing wholesale in one; the spread must not be the degenerate 2.0.
    assert abs(result["spread_r"]) < 2.0


def test_tail_retention_reports_top_tercile_capture():
    # Scores perfectly rank outcomes: every tail trade is in the top tercile.
    n = 90
    scores = list(range(n))
    outcomes = [s / 10.0 for s in scores]
    ids = [f"Y{i}" for i in range(n)]
    result = tail_retention(scores, outcomes, row_ids=ids, tail_r=8.0)
    assert result["insufficient"] is False
    assert result["tail_count"] == 10
    assert result["tail_in_top_tercile"] == 10
    assert result["observed_share"] == 1.0


def test_tail_retention_insufficient_below_30():
    result = tail_retention([1.0] * 5, [0.5] * 5)
    assert result["insufficient"] is True
