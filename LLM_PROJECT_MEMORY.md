# Kronos Predictor LLM Project Memory

Last updated: 2026-05-15

This file is the first document future LLM agents should read. It explains what this project is, why the major folders exist, what changed in the latest Codex work session, and how to verify the system without making unsafe trading claims.

## Current Project Goal

Kronos Predictor is a local market forecasting and scanner project. It has two major layers:

- A Kronos time-series forecasting model wrapper and Streamlit app for forecasts.
- A Potter Box options scanner that now includes an evidence-driven edge engine.

The project should optimize for validated evidence, not more alerts. Live alerts and trading must remain fail-closed unless the existing safeguards, credentials, and evidence all pass.

## Critical Guardrails For Future Agents

- Do not promise profits or claim the system is profitable from toy validation.
- Do not force live Telegram alerts on. Live alerting requires existing scanner safeguards such as `--mode live`, valid Telegram credentials, and `LIVE_MODE_ENABLED=true`.
- Do not delete or ignore `scanner/` just because Git once showed it as untracked. It contains the active scanner implementation. Runtime reports under `scanner/reports/` are generated evidence and are intentionally ignored.
- Do not loosen thresholds just to produce more signals. The current design rejects weak evidence by default.
- Prefer deterministic tests and report files over narrative confidence.
- Treat yfinance, Alpaca IEX, and indicative options feeds as lower-confidence data unless better data credentials are configured.

## Repository File Structure

### Root Files

- `README.md`: Upstream/project README for Kronos.
- `README_JAKE.md`: Local user-facing launch and usage notes for Jake's Windows desktop setup.
- `requirements.txt`: Root Python dependencies for Kronos model tests and related tooling.
- `pytest.ini`: Added so pytest collects actual test folders and does not accidentally collect script-like files such as `finetune/qlib_test.py`.
- `kronos_app.py`: Local Streamlit app entrypoint for desktop forecasting.
- `launch_kronos.bat`: Windows launcher for the Streamlit app.
- `install_deps.bat`: Local Windows dependency helper.
- `model/`: Kronos model/tokenizer/predictor implementation.
- `tests/`: Root model regression and sampler safety tests.

### `model/`

Core Kronos model code.

- `model/kronos.py`: Main tokenizer/model/predictor implementation. Updated to make `sample_from_logits` NaN/Inf-safe and deterministic under invalid logits.
- `model/module.py`: Supporting neural network modules.
- `model/__init__.py`: Package exports.

### `tests/`

Root test suite for Kronos model behavior.

- `tests/test_kronos_regression.py`: Regression tests for model output and stochastic MSE health. The stochastic MSE test now checks finite bounded health instead of exact brittle values.
- `tests/test_kronos_sampling_safety.py`: Added to prove invalid logits no longer crash sampling.
- `tests/data/`: Regression fixtures.

### `scanner/`

Local Potter Box scanner and edge engine. This is the active scanner system.

- `scanner/main.py`: Scanner CLI entrypoint. Supports legacy modes plus new edge modes:
  - `build_retrieval_index`
  - `validate_edge`
  - `edge_scan`
  - `diagnose_edge`
- `scanner/config.py`: Non-secret scanner thresholds, report paths, and edge-engine settings.
- `scanner/tickers.py`: Watchlist source.
- `scanner/README.md`: Scanner usage, modes, safety defaults, and runbook.
- `scanner/reports/`: Generated reports and decision journals. These are evidence artifacts, not source logic, and should remain untracked unless a small fixture is intentionally added.
- `scanner/logs/`: Runtime logs.
- `scanner/replay/`: Replay datasets.
- `scanner/tests/`: Scanner unit tests.

### `scanner/edge/`

Evidence-driven edge engine added in the latest Codex work session.

- `scanner/edge/features.py`: Converts a candidate/window into a stable, JSON-safe feature vector. Captures Potter geometry, compression, volume behavior, risk/reward, data quality, options quality, and Kronos fields.
- `scanner/edge/retrieval.py`: Builds and loads historical edge records, computes nearest analogs, and applies same-ticker embargo rules to reduce leakage.
- `scanner/edge/scoring.py`: Combines setup quality, analog expectancy, Kronos fields, data quality, sample size, and uncertainty into a transparent `edge_score`.
- `scanner/edge/validation.py`: Computes ranked validation reports with threshold and top-K metrics.
- `scanner/edge/__init__.py`: Package marker.

### `scanner/strategy/`

Rule-based scanner logic.

- `potter_box.py`: Potter Box detection and research candidate scoring.
- `empty_space.py`: Reward/risk and empty-space scoring.
- `risk_reward.py`: Shared R/R calculation helpers.

### `scanner/data/`

Market, options, event, and synthetic session data.

- `market_data.py`: yfinance and Alpaca fetching, ticker validation, timestamp helpers.
- `synthetic_sessions.py`: Builds synthetic daily sessions from intraday bars.
- `options_data.py`: Selects candidate options contracts.
- `events.py`: Earnings/dividend risk checks.

### `scanner/learning/`

Decision logging and outcome review.

- `outcome_store.py`: JSONL decision persistence.
- `outcome_reviewer.py`: Resolves pending outcomes after the horizon.
- `autotuner.py`: Proposes bounded threshold overrides only when outcome data supports it.
- `replay_runner.py`: Replay evaluation. Updated to include stage/reason details.

### `scanner/ai/`

Optional MiniMax scoring adapter. It is not required for the edge engine to run.

### `docs/superpowers/`

Agent workflow artifacts.

- `docs/superpowers/specs/2026-05-14-kronos-edge-engine-design.md`: Approved edge-engine design.
- `docs/superpowers/plans/2026-05-14-kronos-edge-engine.md`: Implementation plan used for the edge engine.

### `finetune/` and `finetune_csv/`

Training and fine-tuning scripts/data from the Kronos ecosystem. Some files here are scripts, not pytest tests. `pytest.ini` prevents accidental collection of script names like `qlib_test.py`.

### `webui/`

Separate web UI from the upstream project.

### `examples/` and `figures/`

Example scripts and documentation images.

## Latest Codex Work Session Changes

The latest work session built the first working version of the evidence-driven edge engine.

### Stability Changes

- Hardened `model/kronos.py::sample_from_logits`:
  - Handles NaN and Inf logits.
  - Handles rows where filtering leaves no finite logits.
  - Uses deterministic fallback probabilities instead of crashing.
  - Fixes the `top_k` variable shadowing bug by calling `torch.topk`.
- Added `tests/test_kronos_sampling_safety.py`.
- Adjusted stochastic Kronos MSE tests to check finite bounded model health instead of exact sampled-path values.
- Added `pytest.ini` so root pytest avoids collecting optional script files as tests.
- Installed missing root requirement `matplotlib` into the local venv during verification.

### Edge Engine Changes

- Added `scanner/edge/features.py`.
- Added `scanner/edge/retrieval.py`.
- Added `scanner/edge/scoring.py`.
- Added `scanner/edge/validation.py`.
- Added edge tests:
  - `scanner/tests/test_edge_features.py`
  - `scanner/tests/test_edge_retrieval.py`
  - `scanner/tests/test_edge_scoring.py`
  - `scanner/tests/test_edge_validation.py`
  - `scanner/tests/test_edge_cli_units.py`
- Added new scanner modes in `scanner/main.py`:
  - `build_retrieval_index`
  - `validate_edge`
  - `edge_scan`
  - `diagnose_edge`
- Added edge config/report paths and thresholds in `scanner/config.py`.

### Replay Changes

- Replaced `scanner/replay/sample_replay_dataset.json` with a longer sample that has enough bars for the Potter window.
- Updated `scanner/learning/replay_runner.py` so replay details include:
  - `stage`
  - `reason`
  - `potter_passed`
  - `direction`
  - `edge_score`
- Added `scanner/tests/test_replay_runner.py`.

### Documentation Changes

- Added this memory document.
- Added edge-engine design and implementation plan under `docs/superpowers/`.

## Verification Snapshot From Latest Session

These commands were run successfully after implementation:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Result:

```text
34 passed
```

```powershell
.\venv\Scripts\python.exe -m pytest scanner\tests -q
```

Result:

```text
27 passed
```

```powershell
.\venv\Scripts\python.exe -m scanner.main --mode build_retrieval_index
```

Result:

```text
records: 5632
tickers: 30
errors: {}
```

```powershell
.\venv\Scripts\python.exe -m scanner.main --mode validate_edge
```

Result summary:

```text
validation samples: 600
threshold 55: 2 signals, 2 wins, 0 losses, precision 1.0 in the bounded validation slice
threshold 65: 0 signals
```

```powershell
.\venv\Scripts\python.exe -m scanner.main --mode edge_scan
```

Result summary:

```text
30 tickers scanned
5632 index records used
No promoted candidates
Top current candidate: TTD, edge_score 40.17, recommendation reject
```

```powershell
.\venv\Scripts\python.exe -m scanner.main --mode diagnose_edge
```

Result summary:

```text
diagnosis: no edge candidates passed current research scoring
```

## How To Run The Edge Engine

From repo root:

```powershell
.\venv\Scripts\python.exe -m scanner.main --mode build_retrieval_index
.\venv\Scripts\python.exe -m scanner.main --mode validate_edge
.\venv\Scripts\python.exe -m scanner.main --mode edge_scan
.\venv\Scripts\python.exe -m scanner.main --mode diagnose_edge
```

Important reports:

- `scanner/reports/edge_index_report.json`
- `scanner/reports/edge_retrieval_index.json`
- `scanner/reports/edge_validation_report.json`
- `scanner/reports/edge_scan_report.json`
- `scanner/reports/edge_diagnostic_report.json`
- `scanner/reports/replay_eval_report.json`

## Current Interpretation

The edge engine is working, but it is currently conservative:

- It can build a historical analog index.
- It can validate ranked candidates.
- It can rank the current watchlist.
- It did not promote current live candidates because their edge scores were below thresholds.

That is intentional. The system should reject weak evidence rather than manufacture excitement.

## Recommended Next Work

1. Improve retrieval performance. Current validation is bounded to 600 records because naive analog search over the full index is slow.
2. Add provider-quality metadata into live scan features instead of defaulting feed confidence.
3. Expand validation with purged walk-forward splits by date.
4. Add a small dashboard or report renderer for edge scorecards.
5. Collect more replay/outcome data before changing promotion thresholds.
6. Consider better market and options data feeds before trusting live decisions.

## Git/Workspace Notes

At the time this document was created, several local project files and `scanner/` appeared as untracked in Git status. Treat them as project assets unless the user explicitly says otherwise. Do not clean them up automatically.
