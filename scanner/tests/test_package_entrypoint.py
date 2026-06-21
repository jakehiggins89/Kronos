import subprocess
import sys
import json
from pathlib import Path

import scanner.main as scanner_main


def test_scanner_help_runs_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "-m", "scanner.main", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "Potter Box Scanner V1" in result.stdout


def test_parse_args_accepts_research_ops(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scanner.main", "--mode", "research_ops"])

    args = scanner_main.parse_args()

    assert args.mode == "research_ops"


def test_load_env_reads_scanner_env_file(monkeypatch, tmp_path):
    root_env = tmp_path / ".env"
    scanner_env = tmp_path / "scanner.env"
    root_env.write_text("ALPACA_API_KEY=\nMARKET_DATA_PROVIDER=\n", encoding="utf-8")
    scanner_env.write_text(
        "ALPACA_API_KEY=test-key\n"
        "ALPACA_SECRET_KEY=test-secret\n"
        "MARKET_DATA_PROVIDER=alpaca\n"
        "ALPACA_FEED=iex\n",
        encoding="utf-8",
    )
    for key in ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "MARKET_DATA_PROVIDER", "ALPACA_FEED"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(scanner_main, "ENV_PATHS", (root_env, scanner_env))

    env = scanner_main._load_env()

    assert env["alpaca_key"] == "test-key"
    assert env["alpaca_secret"] == "test-secret"
    assert env["market_data_provider"] == "alpaca"


def test_live_preflight_blocks_when_edge_audit_is_blocked(monkeypatch, tmp_path):
    audit_path = tmp_path / "edge_audit_report.json"
    audit_path.write_text(
        json.dumps(
            {
                "readiness": "blocked",
                "blockers": ["validation_threshold_55_unsupported"],
                "warnings": ["no_current_actionable_candidates"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(scanner_main, "EDGE_AUDIT_REPORT_PATH", audit_path)
    env = {
        "market_data_provider": "auto",
        "alpaca_key": "key",
        "alpaca_secret": "secret",
        "telegram_token": "token",
        "telegram_chat_id": "chat",
        "live_mode_enabled": True,
        "minimax_api_key": "",
    }

    assert scanner_main._preflight_checks("live", env, scanner_main.setup_logging(tmp_path)) is False


def test_live_preflight_requires_edge_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner_main, "EDGE_AUDIT_REPORT_PATH", tmp_path / "missing_audit.json")
    env = {
        "market_data_provider": "auto",
        "alpaca_key": "key",
        "alpaca_secret": "secret",
        "telegram_token": "token",
        "telegram_chat_id": "chat",
        "live_mode_enabled": True,
        "minimax_api_key": "",
    }

    assert scanner_main._preflight_checks("live", env, scanner_main.setup_logging(tmp_path)) is False


def test_live_preflight_blocks_research_only_audit(monkeypatch, tmp_path):
    audit_path = tmp_path / "edge_audit_report.json"
    audit_path.write_text(
        json.dumps({"readiness": "research_only", "blockers": [], "warnings": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(scanner_main, "EDGE_AUDIT_REPORT_PATH", audit_path)
    env = {
        "market_data_provider": "auto",
        "alpaca_key": "key",
        "alpaca_secret": "secret",
        "telegram_token": "token",
        "telegram_chat_id": "chat",
        "live_mode_enabled": True,
        "minimax_api_key": "",
    }

    assert scanner_main._preflight_checks("live", env, scanner_main.setup_logging(tmp_path)) is False


def test_live_preflight_allows_paper_trade_only_audit(monkeypatch, tmp_path):
    audit_path = tmp_path / "edge_audit_report.json"
    audit_path.write_text(
        json.dumps({"readiness": "paper_trade_only", "blockers": [], "warnings": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(scanner_main, "EDGE_AUDIT_REPORT_PATH", audit_path)
    env = {
        "market_data_provider": "auto",
        "alpaca_key": "key",
        "alpaca_secret": "secret",
        "telegram_token": "token",
        "telegram_chat_id": "chat",
        "live_mode_enabled": True,
        "minimax_api_key": "",
    }

    assert scanner_main._preflight_checks("live", env, scanner_main.setup_logging(tmp_path)) is True
