from pathlib import Path


def test_scheduled_research_ops_batch_propagates_python_exit_code():
    script = Path("scanner/run_research_ops_scheduled.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert "set \"research_ops_exit=%errorlevel%\"" in lowered
    assert "exit /b %research_ops_exit%" in lowered
