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
scanner\run_scanner.bat --mode adaptive_policy
scanner\run_scanner.bat --mode adaptive_policy --apply_tuning
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
scanner\run_scanner.bat --mode brief
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

## Automation (hands-off daily loop)
A Windows scheduled task named `Kronos Daily Research Ops` runs `scanner\run_research_ops_scheduled.bat` every weekday at 13:30 Central (14:30 ET, mid-session so Tradier quotes are execution-grade). It wakes the PC if asleep and catches up if the start was missed. Output appends to `scanner\logs\scheduled_research_ops.log`.

Each run finishes by writing `scanner\reports\daily_brief.md` and sending the condensed brief to Telegram (`BRIEF_TELEGRAM_ENABLED`, uses `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from `.env`). The Telegram message is a status report only; live trade alerting remains behind the evidence-gated live-mode checks.

To inspect or change the schedule: Task Scheduler > "Kronos Daily Research Ops", or re-register via `Register-ScheduledTask` (see git history for the exact command).

## Daily Brief
`brief` reads the latest report artifacts (no network, no model loads) and renders a verdict-first operator summary: evidence-gate progress, today's scan, learning-loop state including Kronos lift, every blocker in plain English with its fix, and the single next action. `research_ops` runs it automatically as its final stage.

```bat
.\venv\Scripts\python.exe -m scanner.main --mode brief
```

Output: printed to the console and saved at `scanner\reports\daily_brief.md`.

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
- Adaptive policy report at `scanner\reports\adaptive_policy_report.json`.
- Daily operator brief at `scanner\reports\daily_brief.md`.
- Trial registry (every tuning change evaluated/applied) at `scanner\reports\trial_registry.jsonl`.

## Edge Evidence Lab
`run_edge_lab` executes the full research loop in one local run:
1. Build the retrieval index.
2. Validate scored historical candidates.
3. Scan the current watchlist.
4. Write diagnostics.

Each lab run writes a manifest plus JSONL row artifacts for index records, validation candidates, scan candidates, metrics, and diagnostics. If a Parquet engine such as `pyarrow` is installed, matching `.parquet` sidecars are written automatically. If not, JSONL remains the canonical fallback. To enable Parquet sidecars, install the optional package extra with `.\venv\Scripts\python.exe -m pip install -e ".[evidence]"`.

Edge validation uses purged walk-forward analogs: historical candidates are scored only against records available before that candidate timestamp. Current scans may use the full saved index, but validation reports mark `validation_method=purged_walk_forward` and `future_analogs_allowed=false`.

How the evidence is measured (2026-07 revision):
- The retrieval index is built from the watchlist plus `EDGE_INDEX_EXTRA_UNIVERSE` (index/validation only), and analogs match on a curated set of scale-free setup features with direction matching and a cross-ticker embargo during validation.
- Historical outcomes are triple-barrier labeled (stop at -risk, target at +target, time exit at the horizon, evaluated against the High/Low path). A stopped-out trade is a loss even if price later recovers.
- The encoded plan's TARGET side is chosen by `EDGE_EXIT_TARGET_MODE` (`none` | `nearest_empty_space` | `next_empty_space` | `atr_multiple`, plus an `EDGE_EXIT_TARGET_R_FLOOR`), overridable per process via `KRONOS_EXIT_TARGET_*` env vars for lab sweeps. The shipped default is `none` (stop/horizon exits only): the 2026-07-02 six-variant sweep (logged as `exit_geometry_trial` in the trial registry) showed every tested profit target truncated more bullish upside than it locked in (bullish avg R: nearest -0.01, 1.5R floor +0.13, 2R floor +0.15, 2xATR +0.16, no target +0.19 at t=5.2), while bearish stayed negative under all six geometries. Each index record carries `target_mode`/`target_pct_used` provenance and the validation report stamps `exit_geometry_config`.
- Validation samples the most recent `EDGE_VALIDATION_MAX_RECORDS` records by timestamp across all tickers, and reports Spearman rank IC over all samples, top-5/10/20% percentile blocks, decile spread, per-direction expectancy, Wilson lower-bound precision, and R-multiple t-stats.
- The audit accepts either evidence route: the legacy absolute-threshold gate, or the ranking gate (rank IC >= 0.07 with p <= 0.05, plus a profitable top decile with >= 20 signals, t >= 2, Wilson-LB precision >= 0.45). Any direction with >= 15 validation samples and negative average R is flagged and cannot grant paper-trade readiness on its own promotions.

Research recommendations are gated by live setup quality. Strong historical analogs cannot promote or research-label a candidate when both Potter Box and Empty Space gates fail.

### Potter Doctrine v2 Features
The edge feature vector includes a research-only Potter Doctrine v2 score. It records punchback/retest reclaim state, failed reentry risk, cost-basis hold/reclaim/loss state, and overlap-box stack alignment. These fields are written into edge features and decision records so analog retrieval, scorecards, zero-result diagnostics, and future adaptive policy work can learn from failed or near-miss setups.

Doctrine v2 can improve research ranking, but it does not bypass live safety gates. Promotion still requires setup gates, enough analog samples, positive expectancy, usable feed confidence, and execution-grade options data quality.

`adaptive_policy --apply_tuning` may safely tighten `DOCTRINE_V2_SCORE_BASELINE` when resolved doctrine-scored research candidates are loss-heavy. It only tightens the baseline; it does not automatically lower doctrine standards.

## Research Operations
`research_ops` is the repeatable evidence-maintenance cycle. It backs up and deduplicates the decision journal, resolves aged outcomes, collects a fresh delayed-SIP research scan, runs diagnostics, runs bounded autotuning, applies only safe adaptive-policy overrides, refreshes the complete edge lab, and writes `scanner\reports\research_ops_report.json`.

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

## Adaptive Policy Loop
`adaptive_policy` evaluates resolved research candidates by score threshold and outcome quality. It uses conservative win-rate confidence bounds and average return checks before recommending any improvement threshold. When the resolved research cohort is loss-heavy, it may safely tighten `RESEARCH_CANDIDATE_MIN_SCORE`; it does not loosen live gates or promote signals without evidence.

The policy is two-sided with asymmetric safeguards. `RESEARCH_CANDIDATE_MIN_SCORE` is a data-collection throttle (research candidates are paper counterfactuals, never alerts), so a noise-driven tightening must not starve the journal forever. Loosening is recommended only when a lower threshold's cohort dominates the current one on conservative bounds (n >= 12, positive average return, Wilson LB >= 0.30, LB and return margins over the current cohort), capped at 10 points per change. Tightening applies immediately; loosening additionally requires a 7-day cooldown since the last automatic change plus a confirmation on a later calendar day. Every evaluated or applied change is appended to `scanner\reports\trial_registry.jsonl` so the multiple-testing trial count stays honest.

The report also includes a `kronos_lift` section: resolved research candidates split by Kronos directional agreement (research candidates are evaluated by Kronos at scan time). This is the evidence that decides whether the Kronos confirmation stage earns its gate.

The same report includes a `doctrine_v2` section with threshold cohorts, punchback-state outcomes, cost-basis-state outcomes, and risk flag counts. When Doctrine v2 evidence is loss-heavy at the current baseline, the safe auto-action is to raise `DOCTRINE_V2_SCORE_BASELINE`.

```bat
.\venv\Scripts\python.exe -m scanner.main --mode adaptive_policy
.\venv\Scripts\python.exe -m scanner.main --mode adaptive_policy --apply_tuning
```

`research_ops` runs this stage with safe application enabled, so repeated maintenance cycles can automatically reduce bad research candidates while keeping live alerts fail-closed.

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
- Daily after review: `adaptive_policy --apply_tuning`, or run `research_ops` to include it automatically.

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

## Tradier Options Data (wired 2026-07-02)
Set `TRADIER_API_TOKEN` in `scanner\.env` (a PRODUCTION brokerage token - sandbox tokens are 15-min delayed and stay research-grade). Option selection then uses Tradier's real-time OPRA-consolidated chains first: NBBO bid/ask with sizes, native volume and open interest, ORATS greeks, true quote timestamps.

Behavior:
- Liquidity-gate failures on Tradier data are authoritative (no fallback to lower-grade data to force a pass). Only infrastructure failures (auth/transport) fall back to the legacy Alpaca-indicative + yfinance pipeline, with a warning.
- `options_data_quality` is 0.9 for fresh quotes (execution-grade; clears the audit's 0.75 bar during market hours) and degrades past 30 minutes, so after-hours scans are honestly research-grade. Run scans during market hours for execution-grade evidence.
- Keep at least $2k in the account or make 2 trades/yr to avoid Tradier's $50 inactivity fee; unfunded accounts lose API access after 60 days.

## Remaining Data Upgrade Paths
- `low_feed_confidence` (equities): free Alpaca IEX remains the bar source. Full-SIP options: Alpaca Algo Trader Plus $99/mo (also real-time OPRA options on the existing SDK: `feed="sip"` / `feed="opra"`), or Polygon/Massive Stocks Starter $29/mo for delayed full-market bars.

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
