from scanner.edge.validation import compute_edge_validation_report


def test_compute_edge_validation_report_threshold_and_topk_metrics():
    candidates = [
        {"ticker": "A", "edge_score": 90, "outcome_label": "win", "outcome_return_pct": 4.0, "r_multiple": 2.0},
        {"ticker": "B", "edge_score": 80, "outcome_label": "loss", "outcome_return_pct": -2.0, "r_multiple": -1.0},
        {"ticker": "C", "edge_score": 60, "outcome_label": "win", "outcome_return_pct": 1.5, "r_multiple": 0.8},
        {"ticker": "D", "edge_score": 30, "outcome_label": "loss", "outcome_return_pct": -1.0, "r_multiple": -0.4},
    ]

    report = compute_edge_validation_report(candidates, thresholds=(50, 75), top_k=2, slippage_pct=0.1)

    assert report["samples"] == 4
    assert report["thresholds"]["50"]["signal_count"] == 3
    assert report["thresholds"]["50"]["precision"] == 2 / 3
    assert report["thresholds"]["50"]["recall"] == 1.0
    assert report["thresholds"]["75"]["signal_count"] == 2
    assert report["thresholds"]["75"]["precision"] == 0.5
    assert report["top_k"]["k"] == 2
    assert report["top_k"]["precision"] == 0.5
    assert report["thresholds"]["50"]["average_return_pct_after_slippage"] < report["thresholds"]["50"]["average_return_pct"]


def test_by_direction_blocks_carry_within_direction_ranking_metrics():
    candidates = [
        {
            "ticker": f"T{i}",
            "timestamp": f"2026-03-{(i % 25) + 1:02d}T15:00:00-04:00",
            "direction": "bullish" if i % 2 == 0 else "bearish",
            "edge_score": float(i),
            "outcome_label": "win" if i % 3 == 0 else "loss",
            "outcome_return_pct": (i % 7) - 3.0,
            "r_multiple": ((i % 7) - 3.0) / 2.0,
        }
        for i in range(80)
    ]

    report = compute_edge_validation_report(candidates)

    bullish = report["by_direction"]["bullish"]
    assert "rank_ic_r" in bullish and "n_days" in bullish["rank_ic_r"]
    assert "p_value_day_clustered" in bullish["rank_ic_r"]
    assert "tercile_lift" in bullish
    assert "tail_retention" in bullish
    assert bullish["t_stat_r_day_clustered"]["n_days"] > 0
    # Tiny subsets must degrade gracefully, not crash.
    small = compute_edge_validation_report(candidates[:4])
    assert small["by_direction"]["bullish"]["tercile_lift"]["insufficient"] is True
