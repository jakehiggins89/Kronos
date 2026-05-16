from scanner.edge.scoring import score_edge_candidate


def _features():
    return {
        "ticker": "TEST",
        "direction": "bullish",
        "potter_passed": 1.0,
        "research_score": 70.0,
        "rr_ratio": 2.2,
        "empty_space_score": 3.0,
        "kronos_directional_agreement": 0.72,
        "kronos_median_forecast_return_pct": 2.0,
        "kronos_worst_sampled_return_pct": -0.5,
        "data_quality_score": 1.0,
        "feed_confidence": 0.9,
        "options_spread_pct": 0.06,
    }


def test_score_edge_candidate_promotes_positive_analog_expectancy():
    analogs = [
        {"outcome_label": "win", "outcome_return_pct": 3.0, "r_multiple": 1.4, "mae_pct": -0.6, "mfe_pct": 4.0},
        {"outcome_label": "win", "outcome_return_pct": 2.0, "r_multiple": 1.0, "mae_pct": -0.8, "mfe_pct": 3.0},
        {"outcome_label": "loss", "outcome_return_pct": -0.7, "r_multiple": -0.3, "mae_pct": -1.2, "mfe_pct": 1.0},
    ]

    result = score_edge_candidate(_features(), analogs, min_analogs=3)

    assert result["edge_score"] >= 65
    assert result["recommendation"] == "promote"
    assert result["scorecard"]["analog_expectancy"] > 0
    assert result["analog_summary"]["count"] == 3


def test_score_edge_candidate_rejects_negative_expectancy():
    analogs = [
        {"outcome_label": "loss", "outcome_return_pct": -3.0, "r_multiple": -1.2, "mae_pct": -4.0, "mfe_pct": 0.5},
        {"outcome_label": "loss", "outcome_return_pct": -1.0, "r_multiple": -0.6, "mae_pct": -2.0, "mfe_pct": 0.7},
        {"outcome_label": "win", "outcome_return_pct": 0.3, "r_multiple": 0.1, "mae_pct": -1.5, "mfe_pct": 1.0},
    ]

    result = score_edge_candidate(_features(), analogs, min_analogs=3)

    assert result["edge_score"] < 55
    assert result["recommendation"] in {"reject", "research"}
    assert result["scorecard"]["analog_expectancy"] < 0


def test_score_edge_candidate_penalizes_thin_or_low_quality_evidence():
    features = _features()
    features["data_quality_score"] = 0.4
    features["feed_confidence"] = 0.25
    analogs = [
        {"outcome_label": "win", "outcome_return_pct": 3.0, "r_multiple": 1.4, "mae_pct": -0.6, "mfe_pct": 4.0}
    ]

    result = score_edge_candidate(features, analogs, min_analogs=5)

    assert result["recommendation"] != "promote"
    assert result["scorecard"]["sample_penalty"] < 0
    assert result["scorecard"]["data_quality"] < 0
