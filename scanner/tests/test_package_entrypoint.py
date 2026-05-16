import subprocess
import sys
from pathlib import Path


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
