import subprocess
import sys
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
