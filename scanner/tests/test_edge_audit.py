from scanner.edge.audit import compute_edge_audit_report


def test_edge_audit_blocks_when_walk_forward_validation_has_no_supported_threshold():
    validation = {
        "validation_method": "purged_walk_forward",
        "future_analogs_allowed": False,
        "thresholds": {
            "45": {"signal_count": 1, "precision": 0.0, "average_r_multiple": -0.9},
            "55": {"signal_count": 0, "precision": 0.0, "average_r_multiple": 0.0},
        },
    }
    scan = {
        "candidates": [
            {
                "ticker": "CHPT",
                "status": "candidate",
                "recommendation": "reject",
                "features": {
                    "feed_confidence": 0.5,
                    "options_open_interest": 0.0,
                    "options_volume": 0.0,
                    "options_spread_pct": 0.0,
                },
            }
        ]
    }

    report = compute_edge_audit_report(validation, scan)

    assert report["readiness"] == "blocked"
    assert "validation_threshold_55_unsupported" in report["blockers"]
    assert "options_liquidity_missing" in report["warnings"]
    assert report["checks"]["future_analogs_blocked"]["passed"] is True


def test_edge_audit_allows_research_only_when_validation_and_candidate_quality_pass():
    validation = {
        "validation_method": "purged_walk_forward",
        "future_analogs_allowed": False,
        "thresholds": {
            "55": {"signal_count": 25, "precision": 0.64, "average_r_multiple": 0.8},
        },
    }
    scan = {
        "candidates": [
            {
                "ticker": "TEST",
                "status": "candidate",
                "recommendation": "research",
                "features": {
                    "feed_confidence": 0.9,
                    "options_open_interest": 250.0,
                    "options_volume": 80.0,
                    "options_spread_pct": 0.05,
                },
            }
        ]
    }

    report = compute_edge_audit_report(validation, scan)

    assert report["readiness"] == "research_only"
    assert report["blockers"] == []
    assert report["summary"]["research_candidates"] == 1


def _ranking_validation(within_bullish_ic=None):
    by_direction = {}
    if within_bullish_ic is not None:
        by_direction["bullish"] = {
            "signal_count": 500,
            "average_r_multiple": 0.2,
            "rank_ic_r": {"ic": within_bullish_ic, "p_value": 0.01, "p_value_day_clustered": 0.02, "n": 500},
        }
    return {
        "validation_method": "purged_walk_forward",
        "future_analogs_allowed": False,
        "thresholds": {"55": {"signal_count": 0, "precision": 0.0, "average_r_multiple": 0.0}},
        "rank_ic_r": {"ic": 0.12, "p_value": 0.001, "n": 1000},
        "percentiles": {
            "top_10_pct": {
                "signal_count": 100,
                "average_r_multiple": 0.4,
                "t_stat_r_multiple": 3.0,
                "wilson_lb_precision": 0.5,
            }
        },
        "by_direction": by_direction,
    }


_EMPTY_SCAN = {"candidates": []}


def test_ranking_gate_rejects_pooled_ic_without_within_direction_skill():
    # Pooled IC of 0.12 driven purely by direction separation must NOT pass:
    # no per-direction block clears the bar (fail-closed when absent too).
    report = compute_edge_audit_report(_ranking_validation(within_bullish_ic=None), _EMPTY_SCAN)
    assert report["checks"]["ranking_evidence"]["passed"] is False
    assert "ranking_evidence_unsupported" in report["blockers"]

    report = compute_edge_audit_report(_ranking_validation(within_bullish_ic=0.01), _EMPTY_SCAN)
    assert report["checks"]["ranking_evidence"]["passed"] is False


def test_ranking_gate_passes_with_within_direction_skill():
    report = compute_edge_audit_report(_ranking_validation(within_bullish_ic=0.10), _EMPTY_SCAN)
    assert report["checks"]["ranking_evidence"]["passed"] is True
    assert report["checks"]["ranking_evidence"]["value"]["within_direction_passed"] is True
    assert "ranking_evidence_unsupported" not in report["blockers"]


def test_edge_audit_warns_when_options_data_is_not_execution_grade():
    validation = {
        "validation_method": "purged_walk_forward",
        "future_analogs_allowed": False,
        "thresholds": {
            "55": {"signal_count": 25, "precision": 0.64, "average_r_multiple": 0.8},
        },
    }
    scan = {
        "candidates": [
            {
                "ticker": "TEST",
                "status": "candidate",
                "recommendation": "research",
                "features": {
                    "feed_confidence": 0.9,
                    "options_open_interest": 250.0,
                    "options_volume": 80.0,
                    "options_spread_pct": 0.05,
                    "options_data_quality": 0.6,
                },
            }
        ]
    }

    report = compute_edge_audit_report(validation, scan)

    assert "options_data_not_execution_grade" in report["warnings"]
    assert report["summary"]["non_execution_grade_options_candidates"] == ["TEST"]
