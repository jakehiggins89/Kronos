import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_append_only_stores(monkeypatch, tmp_path):
    # Tests must never append to the production trial registry or overwrite
    # the shipped meta model - the registry is the multiple-testing ledger
    # behind every deflated-significance claim (a pytest run once clobbered
    # replay_eval_report.json the same way).
    monkeypatch.setattr(
        "scanner.learning.trial_registry.TRIAL_REGISTRY_PATH",
        tmp_path / "trial_registry.jsonl",
    )
    monkeypatch.setattr("scanner.main.META_MODEL_PATH", tmp_path / "meta_model.json", raising=False)
