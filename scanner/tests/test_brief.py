import json
import logging

from scanner.brief import build_daily_brief, run_brief


def _write_reports(tmp_path):
    (tmp_path / "edge_audit_report.json").write_text(
        json.dumps(
            {
                "readiness": "blocked",
                "blockers": ["ranking_evidence_unsupported"],
                "warnings": ["options_data_not_execution_grade", "low_feed_confidence"],
                "checks": {
                    "ranking_evidence": {
                        "passed": False,
                        "value": {
                            "rank_ic": 0.03,
                            "rank_ic_p_value": 0.21,
                            "min_rank_ic": 0.07,
                            "top_decile_signals": 12,
                            "min_signals": 20,
                            "top_decile_average_r": 0.15,
                            "top_decile_t_stat": 1.1,
                            "top_decile_wilson_lb_precision": 0.38,
                        },
                    },
                    "validation_threshold": {
                        "passed": False,
                        "value": {"threshold": 55, "signal_count": 0, "min_signals": 20},
                    },
                },
                "summary": {"blocked_directions": ["bearish"]},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "edge_validation_report.json").write_text(
        json.dumps(
            {
                "by_direction": {
                    "bullish": {"signal_count": 300, "average_r_multiple": 0.21},
                    "bearish": {"signal_count": 200, "average_r_multiple": -0.05},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "adaptive_policy_report.json").write_text(
        json.dumps(
            {
                "research_candidates": {
                    "resolved": 22,
                    "resolved_outcomes": {"win": 8, "loss": 14},
                    "resolved_win_rate": 0.3636,
                    "current_threshold": 72,
                },
                "recommendation": {
                    "status": "loosen_research_threshold",
                    "reason": "a lower research threshold dominates the current cohort",
                },
                "kronos_lift": {
                    "rows_with_kronos": 4,
                    "agree": {"signal_count": 2, "win_rate": 1.0},
                    "disagree": {"signal_count": 2, "win_rate": 0.0},
                },
                "doctrine_v2": {
                    "resolved": 8,
                    "current_threshold": {"wins": 2, "losses": 1, "average_return_pct": 3.9},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "zero_result_diagnostic.json").write_text(
        json.dumps({"research_candidates": {"pending": 6}}),
        encoding="utf-8",
    )
    (tmp_path / "edge_scan_report.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "T",
                        "status": "candidate",
                        "direction": "bearish",
                        "edge_score": 7.05,
                        "recommendation": "reject",
                        "blocking_reasons": ["setup_gate_failed", "options_data_not_execution_grade"],
                    },
                    {"ticker": "SOFI", "status": "skip", "reason": "not near box edge"},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_build_daily_brief_renders_verdict_progress_and_next_action(tmp_path):
    _write_reports(tmp_path)

    markdown, payload = build_daily_brief(tmp_path)

    assert payload["readiness"] == "blocked"
    assert "## Verdict" in markdown
    assert "NOT live-ready" in markdown
    assert "rank IC 0.030" in markdown
    assert "top-decile signals 12/20" in markdown
    assert "bearish n=200 avgR -0.05 BLOCKED" in markdown
    assert "T: bearish edge 7.05" in markdown
    assert "Kronos lift: 4 scored" in markdown
    assert "loosen_research_threshold" in markdown
    assert "Confirm the pending research-threshold loosening" in payload["next_action"]


def test_build_daily_brief_survives_missing_reports(tmp_path):
    markdown, payload = build_daily_brief(tmp_path)

    assert payload["readiness"] == "unknown"
    assert "No scan data yet" in markdown


def test_run_brief_writes_markdown_file(tmp_path, capsys):
    _write_reports(tmp_path)

    payload = run_brief(logging.getLogger("test"), report_dir=tmp_path)

    output = tmp_path / "daily_brief.md"
    assert output.exists()
    assert payload["path"] == str(output.resolve())
    assert "## Verdict" in output.read_text(encoding="utf-8")
    assert "Kronos Daily Brief" in capsys.readouterr().out
    assert payload["telegram"]["status"] == "no_credentials"


def test_run_brief_sends_condensed_telegram_when_configured(tmp_path, monkeypatch):
    _write_reports(tmp_path)
    sent = {}

    def fake_send(token, chat_id, message, logger):
        sent.update({"token": token, "chat_id": chat_id, "message": message})
        return True

    monkeypatch.setattr("scanner.brief.send_telegram_message", fake_send)

    payload = run_brief(
        logging.getLogger("test"),
        report_dir=tmp_path,
        telegram_env={"telegram_token": "tok", "telegram_chat_id": "42"},
    )

    assert payload["telegram"]["status"] == "sent"
    assert sent["chat_id"] == "42"
    assert "KRONOS DAILY BRIEF" in sent["message"]
    assert "Verdict: BLOCKED" in sent["message"]
    assert "NEXT:" in sent["message"]
    assert len(sent["message"]) < 1500


def test_run_brief_telegram_failure_never_raises(tmp_path, monkeypatch):
    _write_reports(tmp_path)

    def boom(token, chat_id, message, logger):
        raise RuntimeError("telegram down")

    monkeypatch.setattr("scanner.brief.send_telegram_message", boom)

    payload = run_brief(
        logging.getLogger("test"),
        report_dir=tmp_path,
        telegram_env={"telegram_token": "tok", "telegram_chat_id": "42"},
    )

    assert payload["telegram"]["status"] == "failed"


def test_run_brief_telegram_respects_disable_flag(tmp_path, monkeypatch):
    _write_reports(tmp_path)
    monkeypatch.setattr("scanner.brief.scanner_config.BRIEF_TELEGRAM_ENABLED", False)

    def fail_send(*args, **kwargs):
        raise AssertionError("must not send when disabled")

    monkeypatch.setattr("scanner.brief.send_telegram_message", fail_send)

    payload = run_brief(
        logging.getLogger("test"),
        report_dir=tmp_path,
        telegram_env={"telegram_token": "tok", "telegram_chat_id": "42"},
    )

    assert payload["telegram"]["status"] == "disabled"
