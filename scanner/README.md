# Potter Box Scanner V1

Local Windows Python scanner that identifies Potter Box-style options setups and sends Telegram alerts only when every gate passes.

## Safety Defaults
- Dry-run is default.
- Fail closed on missing/uncertain data.
- Live alerting requires both `--mode live` and `LIVE_MODE_ENABLED=true`.
- Live alerting also requires a current Edge Readiness Audit with `readiness=paper_trade_only`; run `--mode run_edge_lab` first.
- Secrets are loaded from `.env` only (do not hardcode keys/tokens in code).

## Setup
```bat
cd /d C:\Users\Jacob Higgins\projects\kronos-predictor
copy scanner\.env.example scanner\.env
scanner\setup_dependencies.bat
```

## Alpaca Market Data (Recommended)
Set these in `.env` for free IEX-based bars:
```env
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
MARKET_DATA_PROVIDER=auto
ALPACA_FEED=iex
ALPACA_OPTIONS_FEED=indicative
MINIMAX_ENABLED=false
MINIMAX_API_KEY=your_key
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M2.7-highspeed
```

Provider behavior:
- `MARKET_DATA_PROVIDER=auto`: Alpaca first, then yfinance fallback.
- `MARKET_DATA_PROVIDER=alpaca`: Alpaca only (fails if unavailable).
- `MARKET_DATA_PROVIDER=yfinance`: yfinance only.
- Current scans use `ALPACA_FEED` (`iex` on the Basic plan).
- Historical index building and `research_scan` request SIP data with a 16-minute delay, which fits Alpaca Basic's delayed consolidated-data access.
- Options selection joins Alpaca indicative snapshots for quotes, volume, IV, and Greeks availability with yfinance open interest. This improves research evidence but remains below execution-grade OPRA quality.

## Modes
```bat
scanner\run_scanner.bat --mode dry_run
scanner\run_scanner.bat --mode live
scanner\run_scanner.bat --mode backtest_intraday_60d
scanner\run_scanner.bat --mode backtest_daily_proxy_2y
scanner\run_scanner.bat --mode calibration --ticker PLTR --tradingview_csv C:\path\to\tradingview_export.csv
scanner\run_scanner.bat --mode calibration --ticker PLTR --tradingview_csv C:\path\to\tradingview_export.csv --sweep_anchors
scanner\run_scanner.bat --mode calibration --calibration_csv_glob "C:\Users\Jacob Higgins\Downloads\BATS_*, 1D.csv" --sweep_anchors
scanner\run_scanner.bat --mode test_telegram --test_message "Potter scanner connectivity test"
scanner\run_scanner.bat --mode test_minimax --test_message "MiniMax connectivity test"
scanner\run_scanner.bat --mode review_outcomes
scanner\run_scanner.bat --mode autotune
scanner\run_scanner.bat --mode autotune --apply_tuning
scanner\run_scanner.bat --mode replay_eval --replay_dataset "C:\Users\Jacob Higgins\projects\kronos-predictor\scanner\replay\sample_replay_dataset.json"
scanner\run_scanner.bat --mode research_scan
scanner\run_scanner.bat --mode diagnose_zero_results
scanner\run_scanner.bat --mode build_retrieval_index
scanner\run_scanner.bat --mode validate_edge
scanner\run_scanner.bat --mode edge_scan
scanner\run_scanner.bat --mode diagnose_edge
scanner\run_scanner.bat --mode audit_edge
scanner\run_scanner.bat --mode run_edge_lab
scanner\run_scanner.bat --mode research_ops
scanner\run_scanner.bat --mode doctor
```

Equivalent Python commands:
```bat
.\venv\Scripts\python.exe -m scanner.main --mode dry_run
.\venv\Scripts\python.exe -m scanner.main --mode backtest_intraday_60d
.\venv\Scripts\python.exe -m scanner.main --mode backtest_daily_proxy_2y
.\venv\Scripts\python.exe -m scanner.main --mode calibration --ticker PLTR --tradingview_csv C:\path\to\tradingview_export.csv
.\venv\Scripts\python.exe -m scanner.main --mode calibration --calibration_csv_glob "C:\Users\Jacob Higgins\Downloads\BATS_*, 1D.csv" --sweep_anchors
.\venv\Scripts\python.exe -m scanner.main --mode run_edge_lab
.\venv\Scripts\python.exe -m scanner.main --mode doctor
```

## Project Doctor
`doctor` is a no-secrets health report for local review. It verifies the Python version, core runtime imports, and whether secret/runtime artifact paths are ignored by Git. Use it before demos, handoffs, or deeper evidence-lab runs:

```bat
.\venv\Scripts\python.exe -m scanner.main --mode doctor
```

## What Is Logged
- PASS/SKIP/ERROR per ticker with reason.
- Rotating log file at `scanner\logs\scanner.log`.
- Alpaca request tracing at `scanner\logs\request_ids.log` (request id when available).
- Backtest and calibration reports in `scanner\reports\`.
- Decision journal for self-tuning at `scanner\reports\scan_decisions.jsonl`.
- Outcome review report at `scanner\reports\outcome_review_summary.json`.
- Replay report at `scanner\reports\replay_eval_report.json`.
- Calibration batch summary at `scanner\reports\calibration_summary.json`.
- Zero-result diagnostic at `scanner\reports\zero_result_diagnostic.json`.
- Edge Evidence Lab runs at `scanner\reports\evidence\<run_id>\manifest.json`.
- Edge readiness audit at `scanner\reports\edge_audit_report.json`.

## Edge Evidence Lab
`run_edge_lab` executes the full research loop in one local run:
1. Build the retrieval index.
2. Validate scored historical candidates.
3. Scan the current watchlist.
4. Write diagnostics.

Each lab run writes a manifest plus JSONL row artifacts for index records, validation candidates, scan candidates, metrics, and diagnostics. If a Parquet engine such as `pyarrow` is installed, matching `.parquet` sidecars are written automatically. If not, JSONL remains the canonical fallback. To enable Parquet sidecars, install the optional package extra with `.\venv\Scripts\python.exe -m pip install -e ".[evidence]"`.

Edge validation uses purged walk-forward analogs: historical candidates are scored only against records available before that candidate timestamp. Current scans may use the full saved index, but validation reports mark `validation_method=purged_walk_forward` and `future_analogs_allowed=false`.

Research recommendations are gated by live setup quality. Strong historical analogs cannot promote or research-label a candidate when both Potter Box and Empty Space gates fail.

## Research Operations
`research_ops` is the repeatable evidence-maintenance cycle. It backs up and deduplicates the decision journal, resolves aged outcomes, collects a fresh delayed-SIP research scan, runs diagnostics and bounded autotuning, refreshes the complete edge lab, and writes `scanner\reports\research_ops_report.json`.

```bat
.\venv\Scripts\python.exe -m scanner.main --mode research_ops
```

The decision journal rejects repeat observations of the same ticker/setup/day so repeated scans cannot inflate sample counts or bias autotuning.

## Edge Readiness Audit
`audit_edge` summarizes whether the current evidence is usable, research-only, or blocked. It checks:
- Purged walk-forward validation is enabled and future analogs are blocked.
- Threshold 55 has enough out-of-sample signals, precision, and positive average R.
- Current candidates have usable feed confidence and non-missing options liquidity fields.

The audit is intentionally conservative. Free IEX-only market data and indicative or missing options data are useful for research, but they should not be treated as capital-ready evidence without better coverage and liquidity checks.

The free-data ensemble records stock provider/feed/delay plus option provider/feed/quote age. Indicative options receive a quality penalty and cannot produce a `promote` recommendation; real-time OPRA-quality options data is required for promotion.

## Self-Tuning Loop
1. Run scanner (`dry_run` or `live`) so decisions are logged.
2. Run `--mode review_outcomes` to resolve pending decisions to win/loss after horizon.
3. Run `--mode autotune` to generate a bounded threshold proposal using resolved outcomes.
4. Run `--mode autotune --apply_tuning` to persist safe overrides into `scanner\tuning\overrides.json`.
5. Restart scanner process so new thresholds are loaded from overrides.

How learning records behave:
- Passed alerts are recorded as live decisions.
- Skipped setups can be recorded as counterfactual decisions (when direction/entry can be inferred) so missed calls can be evaluated later.
- Validation-only failures (for example, price below min threshold) are marked `not_applicable` and excluded from tuning.

Current gating for tuning:
- Outcomes must age past `OUTCOME_MIN_AGE_DAYS` before resolution.
- Autotune requires at least `AUTOTUNE_MIN_SAMPLES` resolved outcomes before proposing changes.

Suggested automation cadence:
- Every hour/day: `research_scan` while the strict alert path is still producing few or zero signals.
- Daily after close: `review_outcomes`.
- Daily after review: `diagnose_zero_results`.
- Daily after review: `autotune --apply_tuning`.

Research mode:
- `research_scan` logs graded near-miss Potter candidates as pending counterfactuals.
- These candidates do not send Telegram alerts and do not weaken live alert safety.
- Use this mode to build enough labeled data for autotune before enabling or relaxing live alerts.

## Quick Validation Runbook
```bat
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m scanner.main --mode dry_run
.\venv\Scripts\python.exe -m scanner.main --mode backtest_intraday_60d
.\venv\Scripts\python.exe -m scanner.main --mode backtest_daily_proxy_2y
.\venv\Scripts\python.exe -m scanner.main --mode replay_eval --replay_dataset "C:\Users\Jacob Higgins\projects\kronos-predictor\scanner\replay\sample_replay_dataset.json"
```

## Limitations
- Free Alpaca IEX feed is not full SIP coverage.
- yfinance data quality and intraday history depth are limited.
- Daily 2y backtest is proxy only and does not validate true 24h ETH parity.
- TradingView parity is unverified until calibration CSV comparison is run.
- Options liquidity can change intraday; pass/fail is point-in-time.
- Kronos output is treated conservatively; unknown format blocks alerts.
- Early-stage self-tuning will show `insufficient_samples` until enough resolved outcomes accumulate.

## Before Enabling Live Alerts
1. Rotate Telegram bot token and update `.env`.
2. Run `--mode run_edge_lab` and verify `scanner\reports\edge_audit_report.json` reports `readiness=paper_trade_only`.
3. Run `--mode dry_run` and verify ticker-by-ticker logs.
4. Run both backtests and inspect `reports\*.json`.
5. Run calibration with TradingView CSV and review mismatch report.
6. Set `LIVE_MODE_ENABLED=true` only after verification.
