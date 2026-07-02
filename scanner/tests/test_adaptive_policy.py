import json

from scanner.learning.adaptive_policy import build_adaptive_policy_report, apply_adaptive_overrides


def _research_record(ticker, score, label, ret, day=1, doctrine_score=None, punchback_state=None):
    record = {
        "ticker": ticker,
        "mode": "research_scan",
        "decision_ts": f"2026-06-{day:02d}T10:00:00-04:00",
        "final_pass": False,
        "stage_failed": "potter_box_research",
        "skip_reason": "research_candidate",
        "outcome_status": "resolved",
        "outcome_label": label,
        "outcome_ret_5bar_pct": ret,
        "research_score": score,
        "research_diagnostics": {
            "passed": True,
            "score": score,
            "reason": "research_candidate",
            "reasons": ["confirmed_breakout", "volume_expansion"],
        },
    }
    if doctrine_score is not None:
        record.update(
            {
                "doctrine_v2_score": doctrine_score,
                "doctrine_v2_passed": doctrine_score >= 70,
                "doctrine_v2_punchback_state": punchback_state or "fresh_breakout",
                "doctrine_v2_cost_basis_state": "held",
                "doctrine_v2_risk_flags": ["failed_reentry"] if punchback_state == "failed_reentry" else [],
            }
        )
    return record


def test_adaptive_policy_tightens_loss_heavy_research_candidates():
    records = [
        _research_record("L1", 63, "loss", -2.2, 1),
        _research_record("L2", 65, "loss", -1.8, 2),
        _research_record("L3", 68, "loss", -4.1, 3),
        _research_record("L4", 63, "loss", -0.6, 4),
        _research_record("L5", 65, "loss", -3.4, 5),
        _research_record("L6", 68, "loss", -1.1, 6),
        _research_record("W1", 63, "win", 0.7, 7),
        _research_record("W2", 65, "win", 0.4, 8),
    ]

    report = build_adaptive_policy_report(records, current_research_score=62, min_research_samples=8)

    assert report["research_candidates"]["resolved"] == 8
    assert report["research_candidates"]["resolved_outcomes"] == {"loss": 6, "win": 2}
    assert report["research_candidates"]["resolved_win_rate"] == 0.25
    assert report["recommendation"]["status"] == "tighten_research_threshold"
    assert report["recommendation"]["auto_apply_safe"] is True
    assert report["recommendation"]["proposed_overrides"] == {"RESEARCH_CANDIDATE_MIN_SCORE": 67}


def test_adaptive_policy_selects_supported_higher_score_threshold():
    records = []
    for i in range(8):
        records.append(_research_record(f"LOW{i}", 63 + (i % 2), "loss", -1.5, i + 1))
    for i in range(12):
        label = "loss" if i == 0 else "win"
        ret = -0.3 if label == "loss" else 1.4
        records.append(_research_record(f"HIGH{i}", 72 + (i % 3), label, ret, i + 10))

    report = build_adaptive_policy_report(records, current_research_score=62, min_research_samples=8)

    assert report["recommendation"]["status"] == "improve_research_threshold"
    assert report["recommendation"]["selected_threshold"] == 70
    assert report["recommendation"]["proposed_overrides"] == {"RESEARCH_CANDIDATE_MIN_SCORE": 70}
    selected = next(row for row in report["threshold_candidates"] if row["threshold"] == 70)
    assert selected["signal_count"] == 12
    assert selected["win_rate"] > 0.9
    assert selected["average_return_pct"] > 1.0


def test_adaptive_policy_does_not_ratcheting_tighten_without_current_threshold_samples():
    records = [
        _research_record("L1", 63, "loss", -2.2, 1),
        _research_record("L2", 65, "loss", -1.8, 2),
        _research_record("L3", 68, "loss", -4.1, 3),
        _research_record("L4", 63, "loss", -0.6, 4),
        _research_record("L5", 65, "loss", -3.4, 5),
        _research_record("L6", 68, "loss", -1.1, 6),
        _research_record("W1", 63, "win", 0.7, 7),
        _research_record("W2", 65, "win", 0.4, 8),
    ]

    report = build_adaptive_policy_report(records, current_research_score=67, min_research_samples=8)

    assert report["research_candidates"]["signal_count"] == 2
    assert report["recommendation"]["status"] == "hold_current_threshold_pending_samples"
    assert report["recommendation"]["auto_apply_safe"] is False
    assert report["recommendation"]["proposed_overrides"] == {}


def test_adaptive_policy_can_tighten_doctrine_v2_baseline_from_losses():
    records = [
        _research_record("D1", 65, "loss", -2.2, 1, doctrine_score=71, punchback_state="failed_reentry"),
        _research_record("D2", 65, "loss", -1.8, 2, doctrine_score=72, punchback_state="failed_reentry"),
        _research_record("D3", 65, "loss", -4.1, 3, doctrine_score=73, punchback_state="failed_reentry"),
        _research_record("D4", 65, "loss", -0.6, 4, doctrine_score=74, punchback_state="failed_reentry"),
        _research_record("D5", 65, "loss", -3.4, 5, doctrine_score=71, punchback_state="fresh_breakout"),
        _research_record("D6", 65, "loss", -1.1, 6, doctrine_score=72, punchback_state="fresh_breakout"),
        _research_record("D7", 65, "win", 0.7, 7, doctrine_score=73, punchback_state="reclaim"),
        _research_record("D8", 65, "win", 0.4, 8, doctrine_score=74, punchback_state="reclaim"),
    ]

    report = build_adaptive_policy_report(
        records,
        current_research_score=80,
        current_doctrine_score_baseline=70,
        min_research_samples=8,
        min_doctrine_samples=8,
    )

    assert report["doctrine_v2"]["resolved"] == 8
    assert report["doctrine_v2"]["current_baseline"] == 70
    assert report["doctrine_v2"]["punchback_states"]["failed_reentry"]["losses"] == 4
    assert report["doctrine_v2"]["recommendation"]["status"] == "tighten_doctrine_v2_baseline"
    assert report["recommendation"]["proposed_overrides"] == {"DOCTRINE_V2_SCORE_BASELINE": 75}


def test_apply_adaptive_overrides_merges_existing_tuning(monkeypatch, tmp_path):
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(json.dumps({"MIN_RR": 1.7}), encoding="utf-8")
    monkeypatch.setattr("scanner.learning.adaptive_policy.OVERRIDES_PATH", overrides_path)
    monkeypatch.setattr("scanner.learning.adaptive_policy.TUNING_DIR", tmp_path)

    result = apply_adaptive_overrides(
        {
            "recommendation": {
                "auto_apply_safe": True,
                "proposed_overrides": {"RESEARCH_CANDIDATE_MIN_SCORE": 67},
            }
        },
        logger=None,
    )

    assert result["status"] == "applied"
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {
        "MIN_RR": 1.7,
        "RESEARCH_CANDIDATE_MIN_SCORE": 67,
    }


def test_apply_adaptive_overrides_refreshes_runtime_config(monkeypatch, tmp_path):
    overrides_path = tmp_path / "overrides.json"
    calls = []
    monkeypatch.setattr("scanner.learning.adaptive_policy.OVERRIDES_PATH", overrides_path)
    monkeypatch.setattr("scanner.learning.adaptive_policy.TUNING_DIR", tmp_path)
    monkeypatch.setattr(
        "scanner.learning.adaptive_policy.scanner_config.reload_overrides",
        lambda: calls.append("reload"),
    )

    result = apply_adaptive_overrides(
        {
            "recommendation": {
                "auto_apply_safe": True,
                "proposed_overrides": {"RESEARCH_CANDIDATE_MIN_SCORE": 72},
            }
        },
        logger=None,
    )

    assert result["status"] == "applied"
    assert calls == ["reload"]
