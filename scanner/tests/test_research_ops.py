import json

import scanner.main as scanner_main


def test_research_ops_orchestrates_cycle_and_writes_report(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(scanner_main, "REPORT_DIR", tmp_path)
    clock = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 8.0, 9.0, 10.0, 11.0, 12.0, 18.0, 20.0])
    timestamps = iter([f"2026-06-16T00:00:{second:02d}Z" for second in range(14)])
    monkeypatch.setattr(scanner_main, "_monotonic_seconds", lambda: next(clock))
    monkeypatch.setattr(scanner_main, "_utc_now_iso", lambda: next(timestamps))
    monkeypatch.setattr(scanner_main, "load_decisions", lambda: [{"ticker": "A"}, {"ticker": "A"}])
    monkeypatch.setattr(
        scanner_main,
        "deduplicate_decisions",
        lambda rows: ([{"ticker": "A"}], {"input_records": 2, "unique_records": 1, "duplicates_removed": 1}),
    )
    monkeypatch.setattr(scanner_main, "save_decisions", lambda rows: calls.append(("save", len(rows))))
    monkeypatch.setattr(
        scanner_main,
        "review_pending_outcomes",
        lambda rows, logger: (rows, {"pending_reviewed": 0, "resolved_now": 0}),
    )
    monkeypatch.setattr(
        scanner_main,
        "run_watchlist_scan",
        lambda watchlist, mode, env, logger: {"mode": mode, "total": 1, "pass": 1, "skip": 0, "error": 0},
    )
    monkeypatch.setattr(
        scanner_main,
        "_write_zero_result_diagnostic",
        lambda logger: {"resolved_label_counts": {"win": 1, "loss": 0}},
    )
    monkeypatch.setattr(
        scanner_main,
        "propose_overrides",
        lambda rows: {"status": "hold_no_edge", "samples": 1, "overrides": {}},
    )
    monkeypatch.setattr(
        scanner_main,
        "run_edge_lab",
        lambda watchlist, logger: {
            "run_id": "test-run",
            "audit": {"readiness": "blocked", "blockers": ["unsupported"], "warnings": []},
        },
    )

    report = scanner_main.run_research_ops(["TEST"], {}, scanner_main.setup_logging(tmp_path))

    assert report["mode"] == "research_ops"
    assert report["started_at"] == "2026-06-16T00:00:00Z"
    assert report["completed_at"] == "2026-06-16T00:00:13Z"
    assert report["duration_seconds"] == 20.0
    assert report["stages"]["journal_integrity"]["duration_seconds"] == 1.0
    assert report["stages"]["research_scan"]["duration_seconds"] == 2.5
    assert report["stages"]["edge_lab"]["duration_seconds"] == 6.0
    assert report["journal_integrity"]["duplicates_removed"] == 1
    assert report["research_scan"]["pass"] == 1
    assert report["edge_readiness"]["readiness"] == "blocked"
    assert calls == [("save", 1), ("save", 1)]
    assert json.loads((tmp_path / "research_ops_report.json").read_text())["mode"] == "research_ops"
