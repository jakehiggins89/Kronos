import json

from scanner.learning import outcome_store


def _record(**overrides):
    payload = {
        "ticker": "TEST",
        "mode": "research_scan",
        "decision_ts": "2026-06-06T10:00:00-04:00",
        "direction": "bullish",
        "entry_price": 10.1234,
        "stage_failed": "potter_box_research",
        "outcome_status": "pending",
    }
    payload.update(overrides)
    return payload


def test_append_decision_skips_duplicate_setup_on_same_day(monkeypatch, tmp_path):
    path = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(outcome_store, "DECISIONS_PATH", path)
    monkeypatch.setattr(outcome_store, "REPORT_DIR", tmp_path)

    first = outcome_store.append_decision(_record())
    second = outcome_store.append_decision(_record(decision_ts="2026-06-06T15:00:00-04:00"))

    assert first is True
    assert second is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_append_decision_enriches_duplicate_without_adding_sample(monkeypatch, tmp_path):
    path = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(outcome_store, "DECISIONS_PATH", path)
    monkeypatch.setattr(outcome_store, "REPORT_DIR", tmp_path)

    first = outcome_store.append_decision(_record(research_score=68))
    second = outcome_store.append_decision(
        _record(
            decision_ts="2026-06-06T15:00:00-04:00",
            research_score=68,
            doctrine_v2_score=74,
            doctrine_v2_punchback_state="reclaim",
            doctrine_v2_diagnostics={"score": 74, "punchback_state": "reclaim"},
        )
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert first is True
    assert second is False
    assert len(rows) == 1
    assert rows[0]["doctrine_v2_score"] == 74
    assert rows[0]["doctrine_v2_diagnostics"]["punchback_state"] == "reclaim"


def test_deduplicate_decisions_keeps_resolved_version():
    records = [
        _record(outcome_status="pending"),
        _record(
            decision_ts="2026-06-06T15:00:00-04:00",
            outcome_status="resolved",
            outcome_label="win",
        ),
    ]

    clean, report = outcome_store.deduplicate_decisions(records)

    assert len(clean) == 1
    assert clean[0]["outcome_status"] == "resolved"
    assert clean[0]["outcome_label"] == "win"
    assert report["duplicates_removed"] == 1


def test_deduplicate_decisions_handles_nested_diagnostics():
    records = [
        _record(research_diagnostics={"scorecard": {"touches": 2}}),
        _record(
            decision_ts="2026-06-06T15:00:00-04:00",
            outcome_status="resolved",
            outcome_label="win",
            research_diagnostics={"scorecard": {"touches": 3}},
        ),
    ]

    clean, report = outcome_store.deduplicate_decisions(records)

    assert len(clean) == 1
    assert clean[0]["outcome_status"] == "resolved"
    assert report["duplicates_removed"] == 1
