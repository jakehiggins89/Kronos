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
