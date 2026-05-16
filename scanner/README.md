# Potter Box Scanner V1

Local Windows Python scanner that identifies Potter Box-style options setups and sends Telegram alerts only when every gate passes.

## Safety Defaults
- Dry-run is default.
- Fail closed on missing/uncertain data.
- Live alerting requires both `--mode live` and `LIVE_MODE_ENABLED=true`.
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
MINIMAX_ENABLED=false
MINIMAX_API_KEY=your_key
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M2.7-highspeed
```

Provider behavior:
- `MARKET_DATA_PROVIDER=auto`: Alpaca first, then yfinance fallback.
- `MARKET_DATA_PROVIDER=alpaca`: Alpaca only (fails if unavailable).
- `MARKET_DATA_PROVIDER=yfinance`: yfinance only.

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
```

Equivalent Python commands:
```bat
.\venv\Scripts\python.exe -m scanner.main --mode dry_run
.\venv\Scripts\python.exe -m scanner.main --mode backtest_intraday_60d
.\venv\Scripts\python.exe -m scanner.main --mode backtest_daily_proxy_2y
.\venv\Scripts\python.exe -m scanner.main --mode calibration --ticker PLTR --tradingview_csv C:\path\to\tradingview_export.csv
.\venv\Scripts\python.exe -m scanner.main --mode calibration --calibration_csv_glob "C:\Users\Jacob Higgins\Downloads\BATS_*, 1D.csv" --sweep_anchors
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
2. Run `--mode dry_run` and verify ticker-by-ticker logs.
3. Run both backtests and inspect `reports\*.json`.
4. Run calibration with TradingView CSV and review mismatch report.
5. Set `LIVE_MODE_ENABLED=true` only after verification.
