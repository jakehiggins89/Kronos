# Potter Box — Code Gap Map (retired implementation vs. the taught method)

Read-only audit of the `scanner/` codebase as of 2026-09-04 (branch `codex/finish-kronos-cleanup`, HEAD `f69669e`). Companion to `METHOD_SPEC_FROM_SOURCES.md` in this directory; rule IDs `R<n>` below refer to that file. All `path:line` references are to the working tree. Every number in section 3 comes from a read-only probe of `scanner/reports/edge_retrieval_index.json` (11,030 records) or from calling the shipped scorer on a synthetic series; nothing was written except this file.

Two files appeared under `scanner/potter_v3/` (package) and `scanner/tests/test_potter_v3_sessions.py` while this audit ran (untracked, 20:14–20:15 today). They are read and referenced in sections 4 and 9; they were not modified.

---

## 0. Empty-space diagnosis (the headline)

`scanner/strategy/empty_space.py` does not detect empty space. It measures the distance from the breakout close to the **nearest prior bar high inside the last 120 bars** and demands that distance be ≥1.5× the distance to the box midpoint. Three compounding defects make that ratio ≈0 on 99.9% of detector-passing setups:

1. **Fallback inversion.** When the breakout close is above *every* high in the lookback — the method's textbook "empty space to the left" (R32–R34) — `nearest_target = float(hist["High"].max())` (`empty_space.py:25`), a level **below** the entry. `compute_rr` clamps reward to `max(target - entry, 0.0)` (`risk_reward.py:6`), so `rr = 0`, `score = 0`. In the index, 415 of 2,344 `potter_passed` records (17.7%; 292 bullish, 123 bearish) have `distance_to_target_pct == 0` exactly. The cleanest setups score worst.
2. **Window contamination.** `hist = bars.iloc[:-1].tail(120)` (`empty_space.py:18`) excludes only the breakout bar; it *includes* the 15-bar consolidation window and everything before it. A close that just cleared the close-based control (median `breakout_strength_pct` 1.66%) is by construction sitting under the box's own wicks or the previous swing, so the "nearest resistance" is 0.07–0.87% away (IQR of non-zero distances; median 0.37%; 1,144 of 2,344 within 0.5%).
3. **Denominator.** `invalidation = cost_basis` (`empty_space.py:39`), the midpoint of the close controls (`potter_box.py:75`), so risk = half the box height + breakout distance: median `risk_pct` 10.0% (IQR 6.3–15.7%) because median `box_width_pct` is 15.4%. A 0.37% reward over a 10% risk is `rr ≈ 0.04`.

Net effect in the index: `rr == 0` for 415 records, `rr < 1` for 2,340, `1 ≤ rr < 1.5` for 2, `rr ≥ 1.5` for 2 (TTD 2025-07-25 rr 4.13 and 2025-07-28 rr 3.02 — a prior peak 33%/29% above the entry). Median `rr` 0.154, 90th percentile 0.44. Pass condition is `score ≥ 2 and rr ≥ 1.5` (`empty_space.py:54`; `MIN_EMPTY_SPACE_SCORE=2`, `MIN_RR=1.5`, `config.py:23-24`), i.e. the scorer only passes when there is *overhead supply far away* — the opposite of empty space — and it never represents the method's 50% trim level (R35). Synthetic confirmation (calling the shipped functions): a clean 15-bar box at 99.8–100.2 with all prior highs ≤101 and a breakout close of 102 returns `nearest_target=101.0, reward=0, rr=0.000, passed=False`; the same box with its own wick at 101.5 and a 101.0 close returns `nearest_target=101.5, rr=0.5`; adding a lone shelf at 115 forty bars back returns `rr=6.5, passed=True`.

---

## 1. Pipeline map

### 1.1 Modes and chaining (`scanner/main.py`)

`parse_args` (`main.py:173-219`) accepts the `--mode` choices at `main.py:176-201`. `main()` (`main.py:2126-2210`) runs `_preflight_checks` (`main.py:472-625`) then dispatches. Relevant chains:

- `research_ops` → `run_research_ops` (`main.py:2030-2089`): journal dedupe (2040-2050) → `review_pending_outcomes` (2052-2055) → `run_adaptive_policy(apply_tuning=True)` (2058) → `run_watchlist_scan(..., "research_scan")` (2059) → `_write_zero_result_diagnostic` (2060) → `propose_overrides` (2061) → **`run_edge_lab`** (2062) → `run_brief` (2063). Writes `reports/research_ops_report.json` (2083-2086).
- `run_edge_lab` (`main.py:1910-1946`): `start_evidence_run(mode="run_edge_lab", root_dir=EVIDENCE_DIR)` (1912-1923) → `run_build_retrieval_index` (1925) → `run_validate_edge` (1926) → `run_edge_scan` (1927) → `run_diagnose_edge` (1928) → `run_audit_edge` (1929) → `evidence_run.flush()` (1930).
- `build_retrieval_index` → `run_build_retrieval_index` (`main.py:1541-1616`): universe = `WATCHLIST + EDGE_INDEX_EXTRA_UNIVERSE` (1544; 30 + 25 names, `config.py:187-205`). Per ticker: `fetch_daily_bars(ticker, research=True, adjustment=EDGE_BARS_ADJUSTMENT)` (1553) → `drop_in_progress_daily_bar` (1554) → `drop_vendor_placeholder_bars` (1558) → `check_ohlcv_contract` (1567) → `check_session_completeness` (1568) → `cross_check_daily_bars` (1571) → any violation raises and skips the ticker (1576) → `build_edge_records_from_bars(ticker, daily, horizon=PRED_DAYS)` (1581). Then `save_edge_index(records, EDGE_INDEX_PATH)` (1584), `evidence_run.record_rows("edge_index_records", ...)` (1588), and `reports/edge_index_report.json` (1613).

### 1.2 Bar → record (`scanner/edge/retrieval.py`)

`build_edge_records_from_bars` (`retrieval.py:185-293`) walks every bar from `min_history=35` to `len-horizon` (218). For each index `idx`: `window = clean.iloc[:idx+1]` (219); `pb = detect_potter_box(ticker, window)` (220); `research = score_potter_research_candidate(pb, window)` (222).

**The fallback that records a bar even when the detector fails** is `retrieval.py:223-224`:

```python
if direction not in {"bullish", "bearish"}:
    direction = research.get("direction")
```

`score_potter_research_candidate` assigns a direction whenever the last close is above/below the control or within `RESEARCH_NEAR_BREAKOUT_PCT=1.2%` of it (`potter_box.py:195-210`, `config.py:47`), with no touch or prior-close requirement. So 8,686 of 11,030 index records (79%) carry `potter_passed=0`, `skip_reason="no valid Potter Box breakout/breakdown"`, and still get a direction, an entry (`pb.breakout_close`, i.e. the last close, 228), an empty-space score (231), a doctrine score (232), features (260-263), and a triple-barrier outcome (264-274). Records are emitted for *every* bar with no de-overlap, so consecutive days of the same box are separate "signals" (validation compensates with day-clustered statistics; the 2026-08-18 experiment de-overlapped explicitly). The same fallback exists in the live scorer at `main.py:1400`.

Outcome per record: `_future_outcome` (`retrieval.py:140-182`) — `future = bars.iloc[idx+1 : idx+1+horizon]` (156), risk from `resolve_trade_risk_pct` (170), target from `resolve_plan_target_pct` (171-177), `walk_triple_barrier` (178). See section 5.

### 1.3 Record schema

`EdgeRecord` (`retrieval.py:24-40`): `ticker, timestamp, direction, features, outcome_return_pct, outcome_label, r_multiple, mae_pct, mfe_pct, exit_reason, risk_pct_used, outcome_method, target_pct_used, target_mode`. Index file: `scanner/reports/edge_retrieval_index.json` (`EDGE_INDEX_PATH`, `config.py:14`; 30.7 MB, 11,030 records, 55 tickers, timestamps 2024-10-01 → 2026-08-11, `bar_count` 36–501). Evidence copy: `scanner/reports/evidence/20260819T183310Z-a6c8c0d0/edge_index_records.jsonl` (+ `.parquet`).

`features` keys (`extract_edge_features`, `features.py:85-203`, `FEATURE_VERSION=4` at `features.py:11`): `feature_version, ticker, timestamp, direction, bar_count, latest_close, potter_passed, empty_space_passed, event_risk_passed, options_passed, kronos_passed, box_top, box_bottom, box_width_pct, close_position_in_box, breakout_distance_pct, abs_breakout_distance_pct, breakout_strength_pct, atr_value, range_compression_ratio, no_trend_score, top_touches, bottom_touches, touch_tolerance, volume_expansion, volume_percentile, realized_volatility_pct, recent_return_pct, empty_space_score, rr_ratio, distance_to_target_pct, risk_pct, doctrine_v2_passed, doctrine_v2_version, doctrine_v2_score, doctrine_v2_box_stack_score, doctrine_v2_punchback_reclaim, doctrine_v2_failed_reentry, punchback_state, cost_basis_state, options_spread_pct, options_open_interest, options_volume, options_data_provider, options_data_feed, options_quote_age_minutes, options_source_disagreement_pct, options_data_quality, kronos_directional_agreement, kronos_median_forecast_return_pct, kronos_worst_sampled_return_pct, kronos_sample_count, data_missing_bars, data_stale_minutes, data_quality_score, feed_confidence, data_provider, data_feed, data_delay_minutes, skip_reason`. Note `box_top`/`box_bottom` in features are the **close-based controls**, not the wick extremes (`features.py:113-114, 149-150`). In the index `data_provider` is `None` for all 11,030 rows (the builder never passes `data_quality`), `target_mode` is `"none"` for all, `exit_reason` is `horizon` 7,854 / `stop` 3,176, and `options_*` are zero/None.

### 1.4 Record → validation stat → readiness

- `run_validate_edge` (`main.py:1619-1741`): `load_edge_index` (1621) → `EdgeAnalogIndex` (1622) → `select_recent_records(records, EDGE_VALIDATION_MAX_RECORDS=1500)` (1623) → per record `find_analogs(allow_future=False, direction_match=True, embargo 11/11 days)` (1626-1634) → `score_edge_candidate` (1635) → `compute_edge_validation_report(candidates, thresholds=(45,55,65), top_k=25, cost_bps_per_side=EDGE_COST_BPS_PER_SIDE)` (1678-1683) → `reports/edge_validation_report.json` (1739).
- `compute_edge_validation_report` (`validation.py:118-228`): charges costs first via `apply_transaction_costs` (131; body 35-74: `charge_pct = 2*bps/100` at 53, net R re-divided by stored `risk_pct_used` at 68, label recomputed at 72), then threshold blocks (135-138), top-k (140-142), per-direction rank IC / tercile / tail retention (144-162), percentile blocks (167-170), decile spread (172-176), and a `cost_model` provenance block (219-227) that the audit later verifies.
- `run_edge_scan` (`main.py:1744-1806`) scores the *current* watchlist from intraday synthetic sessions (1756-1759, section 4) with `_score_edge_for_bars` (`main.py:1389-1457`).
- `run_audit_edge` (`main.py:1885-1907`) → `compute_edge_audit_report` (`audit.py:134-673`): gates at 139-148 (threshold 55, ≥20 signals, precision LB ≥0.55, rank IC ≥0.07 with clustered p ≤0.05, top-decile t ≥2, Wilson LB ≥0.45); `costs_charged` requires basis `net_of_costs`, floor `MIN_AUDITED_COST_BPS_PER_SIDE=25.0` (`audit.py:12`, 325-376); `readiness ∈ {blocked, paper_trade_only, research_only, watch_only}` (620-627). Current verdict is `blocked` (`RETIRED.json` `final_evidence`).

---

## 2. Detector as it is now

### 2.1 `detect_potter_box` (`scanner/strategy/potter_box.py:39-173`)

1. Needs `CONSOLIDATION_BARS + 2 = 17` bars (44); fewer → `passed=False`, `skip_reason="not enough synthetic bars"` (45-61).
2. `breakout = df.iloc[-1]` (64); `prior_close = df.iloc[-2]["Close"]` (65).
3. **Window:** `cons = df.iloc[-(15+1):-1]` — exactly the 15 bars before the last bar (68). There is no search for where a box starts or ends; every bar is evaluated as "the 15 bars before me are the box".
4. **Levels:** `box_top/box_bottom` = wick max/min of the window (69-70); `close_top_control/close_bottom_control` = max/min close (71-72); `control_top/control_bottom` = the close versions because `USE_CLOSE_BASED_CONTROL=True` (73-74, `config.py:44`); `cost_basis = (control_top + control_bottom)/2` (75).
5. Advisory compression metrics: ATR(14) on pre-breakout bars (80-82), `prior_window = pre_breakout_df.iloc[-(15+14):-15]` (84), `range_compression_ratio = mean(cons range)/mean(prior range)` (88-92), `no_trend_score = |slope of closes / mean close|` (94-97). Since commit `04680e7` these are not pass conditions (118-136 comment; `passed` at 138-142).
6. **Touch counting:** `touch_tol = max(0.10 × (control_top − control_bottom), breakout_close × 0.0015)` (103-104; `BOX_TOUCH_TOLERANCE_PCT=0.0015`, `config.py:43`). `top_touches` = number of window closes ≥ `control_top − tol`; `bottom_touches` = closes ≤ `control_bottom + tol` (`_count_touches`, 33-36; 105-106). The extreme close always counts as one touch, so the rule is "at least one more close within tolerance of the max/min close". Touches are candles, not waves (method R3 says a rejection is a wave and "two candles does not count as two rejections").
7. **Prior-close bias:** `bullish = breakout_close > control_top and prior_close > cost_basis` (108); bearish mirror (109). `breakout_strength_pct` = % beyond control (111-116).
8. `passed = top_touches ≥ 2 and bottom_touches ≥ 2 and (bullish or bearish)` (138-142; `MIN_BOX_TOP_TOUCHES/MIN_BOX_BOTTOM_TOUCHES=2`, `config.py:41-42`). Diagnostics (159-172) carry `control_top/bottom, touch_tolerance, top/bottom_touches, breakout_open, breakout_open_outside_box`.

Yield after `04680e7`: 2,344 of 11,030 index records (1,292 bullish / 1,052 bearish). Before it the three compression gates plus the breakout gate were near mutually exclusive: 10 firings over 24,254 decision bars (`scanner/research/experiments/20260813_detector_fidelity/PHASE1_FINDINGS.md`, Finding 3). The diff (`git show 04680e7 -- scanner/strategy/potter_box.py`) removed the `atr_compressed/range_compressed/no_trend` terms from `passed`, dropped the early return on missing ATR lookback, and lowered `min_needed` from 31 to 17.

What the detector cannot express relative to the method: box start/end (R4, R9), waves as touches (R3), wick-cluster edges (R2b, R11), a box that persists after the breakout bar (R6, R28), any entry other than "last close outside control" (R20–R26), and it fires on RTH daily bars (R17).

### 2.2 `score_potter_research_candidate` (`potter_box.py:176-287`)

Near-miss grader used for journal counterfactuals and as the index's direction fallback: `confirmed_*` if close beyond control, `near_*` if within 1.2% (195-210); points for state (223-228), compression flags (230-238), touches (239-244), prior-close bias (246-253), volume expansion ≥1.15 (255-266), close location (268-272); `passed = score ≥ RESEARCH_CANDIDATE_MIN_SCORE` (274-275). Direction is assigned even when `passed` is false.

### 2.3 `score_potter_doctrine_v2` (`scanner/strategy/potter_doctrine.py:119-202`)

Controls come from `pb.diagnostics` (30-35); direction is `pb.direction` or inferred from the latest close vs. controls (38-46); `tolerance = max(touch_tolerance, 5% of box height, 0.1% of price)` (139).

- `_punchback_state` (49-81) looks at **only the last 3 bars** (52). Bullish: if the latest close ≤ top → `failed_reentry` (56-57); else it scans the two prior bars and returns `reclaim` only if a bar whose range intersects `top ± tol` closes above `top` **after an earlier close above `top`** (59-69); otherwise `fresh_breakout` (70).
- `_cost_basis_state` (84-100): last 5 closes; `lost` if latest is on the wrong side of `cost_basis`, `reclaimed` if any of the prior 4 was, else `held`.
- `_box_stack_score` (103-116): +5 per lookback (15/30/60) whose range is ≤ max(2.5× box width, 8%).
- Score: direction 10 (149-151), ≥2/≥2 touches 15 (153-157), `reclaim` 30 / `fresh_breakout` 18 / `failed_reentry` −20 (159-167), cost basis held/reclaimed 15 / lost −15 (169-174), stack ≤15 (176-178), empty space passed or score ≥2 → 10 (180-183). `passed = score ≥ 70 and no failed_reentry/cost_basis_lost` (185-186). The 70 is hard-coded; `DOCTRINE_V2_SCORE_BASELINE` is only used by `scoring.py:104`.

**Can reclaim ever gate an entry? No, on two levels.** (a) The doctrine result only feeds features (`features.py:170-179`), a ±15 scorecard term (`scoring.py:98-109`), and journal fields (`main.py:786, 818, 852`); it never changes `pb.passed`, `direction`, or `entry`. (b) On production-derived controls `reclaim` is unreachable: the two "prior" bars the state machine inspects are bars −3 and −2 of the window, which sit *inside* the 15-bar consolidation whose max close *is* `control_top`, so `close > top` can never be true for them, `breakout_seen` never flips, and the function returns `fresh_breakout`. Index probe: `punchback_state` is `fresh_breakout` ×7,164 and `unknown` ×3,866; **zero** `reclaim` in 11,030 rows, so `doctrine_v2_punchback_reclaim` is a constant-zero feature. The only test that produces `reclaim` hand-supplies controls below the recent closes (`test_potter_doctrine.py:15-51`).

### 2.4 Constants in play

| constant | value | where |
|---|---|---|
| `CONSOLIDATION_BARS` | 15 | `config.py:36` |
| `ATR_PERIOD` | 14 | `config.py:37` |
| `ATR_COMPRESSION` / `RANGE_COMPRESSION` / `NO_TREND_SLOPE_ABS_MAX` | 0.75 / 0.65 / 0.0015 (advisory only) | `config.py:38-40` |
| `MIN_BOX_TOP_TOUCHES` / `MIN_BOX_BOTTOM_TOUCHES` | 2 / 2 | `config.py:41-42` |
| `BOX_TOUCH_TOLERANCE_PCT` | 0.0015 | `config.py:43` |
| `USE_CLOSE_BASED_CONTROL` | True | `config.py:44` |
| `RESEARCH_CANDIDATE_MIN_SCORE` | 62 → **65** via override | `config.py:45`; `scanner/tuning/overrides.json` |
| `DOCTRINE_V2_SCORE_BASELINE` | 70 → **75** via override | `config.py:46`; `overrides.json` |
| `RESEARCH_NEAR_BREAKOUT_PCT` / `RESEARCH_MIN_VOLUME_EXPANSION` | 0.012 / 1.15 | `config.py:47-48` |
| `MIN_RR` / `MIN_EMPTY_SPACE_SCORE` | 1.5 / 2 (not overridden) | `config.py:23-24` |
| `PRED_DAYS` (outcome horizon) | 5 | `config.py:49` |
| `EDGE_EXIT_TARGET_MODE` | `"none"` (env `KRONOS_EXIT_TARGET_MODE`) | `config.py:151` |
| `EDGE_COST_BPS_PER_SIDE` | 25 (env `KRONOS_COST_BPS_PER_SIDE`) | `config.py:135` |
| `EDGE_BARS_ADJUSTMENT` | `"split"` | `config.py:163` |

`overrides.json` (`scanner/tuning/overrides.json`, last auto-change 2026-07-17) only affects the `_TUNABLES` keys (`config.py:216-227`); `_apply_overrides` (230-247) runs at import and on `reload_overrides()`.

---

## 3. Empty-space scorer

### 3.1 Algorithm (`scanner/strategy/empty_space.py:11-78`, `risk_reward.py:4-12`)

`hist = bars.iloc[:-1].tail(120)` (18). Bullish: `resistances = hist.High[hist.High > breakout_close]` (24); `nearest_target = min(resistances)` else `hist.High.max()` (25); `next_target = min(resistances > nearest)` (26-28). Bearish mirrors with lows (30-34). `compute_rr(entry, target, invalidation=cost_basis)` (36-41): `reward = max(target − entry, 0)`, `risk = max(entry − cost_basis, 1e-9)`, `rr = reward/risk` (`risk_reward.py:5-11`). `score` = 3/2/1 for `rr ≥ 2.5/1.5/1.0` else 0 (46-52); `passed = score ≥ MIN_EMPTY_SPACE_SCORE and rr ≥ MIN_RR` (54) — effectively `rr ≥ 1.5`. The result labels its source `"rolling_swing_levels"` (65), but no swing detection exists; it is a raw max/min over bar extremes. Diagnostics carry `reward_abs, risk_abs, lookback_bars, next_target, distance_to_next_target_pct` (67-77).

### 3.2 Diagnosis

Stated in section 0. The task's hypothesis ("the nearest-resistance search includes bars from the box's own window or the breakout bar") is **confirmed for the box window and partly wrong about the breakout bar**: `iloc[:-1]` excludes the breakout bar, but the box's 15 bars (and the 105 before them) are in `hist`, and the more damaging branch is the `else hist.High.max()` fallback, which turns "nothing above" into "target below entry". Index evidence on the 2,344 `potter_passed` rows:

| quantity | value |
|---|---|
| `empty_space_passed` | 2 bullish, 0 bearish |
| `empty_space_score` | 0 ×2,340, 1 ×2, 3 ×2 |
| `distance_to_target_pct == 0` (fallback branch) | 415 (17.7%): 292 bullish, 123 bearish |
| distance ∈ (0, 0.5] / (0.5, 1] / (1, 2] / (2, 5] / >5 | 1,144 / 379 / 230 / 127 / 49 |
| non-zero distance p10/p25/p50/p75/p90 | 0.07 / 0.15 / 0.37 / 0.87 / 1.89 % |
| `risk_pct` p10/p25/p50/p75/p90 | 4.1 / 6.3 / 10.0 / 15.7 / 22.8 % |
| `rr_ratio` == 0 / <1 / [1,1.5) / ≥1.5 | 415 / 2,340 / 2 / 2 |
| `rr_ratio` p50 / p75 / p90 / max | 0.154 / 0.228 / 0.444 / 4.13 |
| top skip strings | `"...rr 0.00..."` 496, `"...rr 0.01..."` 309, `"...rr 0.02..."` 265, `"...rr 0.03..."` 218 |

`rr_ratio` equals `distance_to_target_pct / risk_pct` to 1e-16, so the stored features fully reconstruct the computation. The two passers are TTD 2025-07-25 (rr 4.13, target 32.9% above, risk 8.0%; outcome −0.01R) and 2025-07-28 (rr 3.02; +0.15R).

What the method wants instead (R32–R36): a **void** scan to the left — the first prior structure (candle body / consolidation) above the box, ignoring the box itself and the move that formed it; if none within the lookback, the setup is *unbounded*, not zero; the target is the far edge of the void, and the trim is at 50% of it (R35). Risk, per R39, is "close back inside the box", not the midpoint.

---

## 4. Bars and sessions

### 4.1 Data paths (`scanner/data/market_data.py`)

- `fetch_intraday_bars(ticker, interval="30m", period="60d", *, research, now, adjustment="split")` (266-322). Provider via `MARKET_DATA_PROVIDER` (`_provider_choice`, 72-73; default `auto`, `config.py:55`). Alpaca branch: `days` parsed from `period` (278), `end = now − 16 min` when `research=True` (280-282), `start = end − (days+5) days` (283), `feed = "sip"` when research else `ALPACA_FEED`/`iex` (284), then `_fetch_alpaca_bars` (288-296). yfinance fallback: `yf.download(period, interval, prepost=True, auto_adjust=False)` (305-313), attrs `data_adjustment="raw"` (319-321).
- `_fetch_alpaca_bars` (125-186): `GET https://data.alpaca.markets/v2/stocks/{ticker}/bars` (142-143) with `timeframe ∈ {30Min, 1Day}` only (`_interval_to_alpaca`, 118-122), `start/end` UTC ISO, `adjustment`, `sort=asc`, `limit=10000`, `feed` (148-156), and `next_page_token` pagination until exhausted (157-168). **No extended-hours parameter is sent; the date range is not capped in code.**
- `fetch_daily_bars(ticker, period="2y", *, research, adjustment="raw")` (325-388). Alpaca `1Day`, `start = end − (365×years+10) days` (335-337), same delay/feed logic (338-341), `adjustment` passed through (the index passes `"split"`, `main.py:1553`). yfinance fallback `prepost=False, auto_adjust=False, repair=True` (357-369), attrs stamped `data_adjustment="split"` (379-387).
- `drop_in_progress_daily_bar` (391-416): drops today's bar before 16:15 ET. `drop_vendor_placeholder_bars` (419-450): drops zero-volume flat bars.
- `scanner/data/bar_contract.py`: `check_ohlcv_contract(df, profile="daily"|"intraday")` (37-150; requires `Open/High/Low/Close/Volume` present, extra columns tolerated, 13/53-55) and `check_session_completeness` against the XNYS calendar (184-232; one bar per exchange session expected, >5 missing fails).

### 4.2 Synthetic sessions (`scanner/data/synthetic_sessions.py:16-70`)

`build_synthetic_sessions(intraday, anchor_hour, anchor_minute, source_interval, prepost_enabled)`: `session_date = date if minute_of_day ≥ anchor else date − 1` (37-40), then groupby OHLCV (42-53); `prepost_enabled` is only echoed into diagnostics (60-69), it filters nothing. With the default anchor `20:00` (`config.py:58-59`) every 04:00–19:30 bar of calendar day D lands in the session **labelled D−1** (probe: two days of 32 bars each → labels `03-01`, `03-02`). So the scan-time "synthetic session" *already is* a 24h ETH candle (04:00–20:00), shifted one label back — which is why `outcome_reviewer.py` needs `source_session_date` alignment (`test_outcome_reviewer.py:60`).

Callers: `main.py:763-769` (`_run_single_ticker`: dry_run/live/research_scan), `main.py:1159-1165` (calibration), `main.py:1758` (`run_edge_scan`), `backtest_runner.py:81` (`backtest_intraday_60d`), `outcome_reviewer.py:263` (journal resolution). **Not** used by `run_build_retrieval_index`, which consumes `fetch_daily_bars` (`main.py:1553`). Consequence: the analog index is built on RTH daily bars while the scan that queries it is built on ETH sessions; `find_analogs` compares `box_width_pct`, `breakout_distance_pct`, etc. computed on different candles. `backtest_daily_proxy_2y` labels itself "daily proxy only (not true 24h ETH validation)" (`backtest_runner.py:118`).

Per-ticker anchors: `_resolve_calibrated_anchor` (`main.py:152-172`) reads `reports/calibration_summary.json` and uses `best_anchor` unless `quality_status == "fail"`. Current file: AAL 18:00 (pass), SNAP 17:00 (pass), SOUN 16:00 (pass), HIMS/RIOT/SOFI/TTD 16:00 (warn — still used). The calibration target is a TradingView `BATS_*, 1D.csv` export (`scanner/README.md` calibration lines; `_calc_mismatch_and_merge`, `main.py:1087-1108` merges by calendar date; pass at avg abs mismatch ≤0.35 price units, `config.py:88`). TradingView daily bars are RTH-only, so those seven tickers were tuned *toward* an RTH-shaped candle; the rest use 20:00. Either way no live session is the chart-date-labelled 04:00–20:00 candle the method reads (R17).

### 4.3 Can the providers deliver ~2 years of ETH 30m bars?

- **Alpaca (code):** pagination is unbounded (`limit=10000` per page + `next_page_token`, 154-168); `period="740d"` yields `start = now − 745 days` (278-283); `research=True` already backs `end` off 16 minutes, which satisfies the documented Basic-plan rule that SIP queries need `end` ≥15 minutes old (Alpaca Market Data FAQ, fetched 2026-09-04: "the `end` parameter must be at least 15 minutes old to query SIP data without a subscription"). ~32 bars/day × ~500 sessions ≈ 16k rows = 2 pages. **Whether `30Min` bars include pre/post-market trades is not stated on the two Alpaca doc pages fetched** (`reference/stockbars`, `docs/market-data-faq`); the new `scanner/potter_v3/sessions.py:5-8` asserts it. Verify with one ticker: histogram `index.hour` of a `fetch_intraday_bars(..., period="740d", research=True)` frame; expect bars at 04:00–19:30 ET and ~32/day.
- **yfinance (code + vendor):** `prepost=True` (309) but Yahoo caps 30m history at 60 days; the fallback would silently return a 60-day frame (no span check in code). Not viable for 2 years.
- **Tradier:** only used for the daily cross-check (`cross_check.py:64`) and options; not a bar source here.

### 4.4 What a 24h-ETH daily series needs (and what already exists)

`scanner/potter_v3/sessions.py` (untracked, 2026-09-04): `load_intraday_eth` (50-85) calls `fetch_intraday_bars(period=f"{740}d", research=True, adjustment="split")` and pickles per ticker/day under `REPORT_DIR/potter_v3_cache` (41-47; `.gitignore` gained `scanner/reports/potter_v3_cache/`); `_clean_intraday` keeps 04:00 ≤ t < 20:00 and drops bad rows (88-102); `build_eth_sessions` reuses `build_synthetic_sessions` with anchor **04:00** so a session carries its own date (105-125; adds `session_last_bar`, `bar_count`, `attrs["session_kind"]="eth_24h"`); `drop_in_progress_session` drops the last session if its final bar starts before 19:30 (128-138); `resample_eth` gives 1h/4h ETH candles aligned to 04:00 (141-154). Tests: `scanner/tests/test_potter_v3_sessions.py`. Still missing: the XNYS `check_session_completeness` pass on the session frame, `check_ohlcv_contract(profile="intraday")` on the raw frame, early-close days (extended session ends 17:00, so `bar_count` < 32 is legitimate on those dates), the ETH-inclusion probe above, and the placeholder/halt handling that `drop_vendor_placeholder_bars` gives the daily path.

---

## 5. Outcomes

### 5.1 Stock-path plan (`scanner/edge/outcomes.py`)

- **Entry:** the decision bar's close (`retrieval.py:228`: `entry = pb.breakout_close`), filled at that close with no next-open slippage; the walk starts at the next bar (`retrieval.py:156`). Method: end-of-day 24h-candle close at 15:50–16:15 (R21) — same bar, but on ETH candles whose "close" is the 20:00 print.
- **Stop:** `risk_pct` = empty-space `risk_pct` = `(entry − cost_basis)/entry × 100` (`retrieval.py:270` ← `features.py:169` ← `empty_space.py:43`); `resolve_trade_risk_pct` (`outcomes.py:26-36`) substitutes ATR% then 2% when ≤0.05, and clamps to [0.25, 15]. `stop_price = entry × (1 − sign·risk/100)` (`outcomes.py:143`); a wick touch exits (153); a gap through the stop fills at the open (158-164). Method R39: stop = a *close* back inside the box (tested and falsified as a variant on RTH bars, `experiments/20260819_close_invalidation_stop/REPORT.md`).
- **Target:** `resolve_plan_target_pct` (`outcomes.py:39-98`) — modes `none` (62-66, shipped), `next_empty_space` (73-79), `atr_multiple` (80-85), `nearest_empty_space` (86-91), optional R-floor (95-97). With `"none"` the target is `None`; `walk_triple_barrier` then never checks a target (137, 154-157). No mode expresses "50% of the empty space" (R35).
- **Horizon:** `PRED_DAYS=5` bars (`retrieval.py:264-267`, `config.py:49`); exit at the final close (147-149). Method R40: 2–3 days typical, sell next morning.
- **R:** `r_multiple = clamp(ret_pct / risk, ±10)` (183); `label = win` if target hit or horizon return >0 (184). MAE/MFE over the held window (175-181).
- **Costs:** none inside `walk_triple_barrier`; charged once downstream: `apply_transaction_costs(rows, EDGE_COST_BPS_PER_SIDE)` in validation (`validation.py:131`, `main.py:1682`) and on analogs in scoring (`scoring.py:71-73`); audit floor `MIN_AUDITED_COST_BPS_PER_SIDE=25.0` (`audit.py:12`, enforced 338-376). Journal outcomes (`outcome_reviewer.py:67-101`) reuse the same walker but with a **different denominator** — session ATR% (`_session_atr_pct`, 55-64; 83) rather than cost basis — so journal R and index R are not on one scale.

### 5.2 Where an options model plugs in

`_future_outcome` (`retrieval.py:140-182`) is the single seam: it receives `bars, idx, horizon, direction, entry, risk_pct, target_pct, atr_value, next_target_pct` and returns the outcome dict consumed at `retrieval.py:275-292`. An options P&L needs inputs the record does not carry: contract type/strike/expiration (the method: OTM, strike at the empty-space target, ~1 week per 24h resistance crossed, R43–R45), option entry mark (bid/ask/mid), IV at entry, exit rule (50% trim + runners, R35/R37), and the option exit mark. `select_options_contract` (`options_data.py:282-...`, 30–60 DTE, nearest strike, liquidity gates) returns `OptionsContractResult` (`utils/validation.py:63-88`: `strike, bid, ask, midpoint, spread_pct, open_interest, volume, implied_volatility, dte, expiration`) but only live; historical rows have no chain. Options: (a) a historical-chain vendor (Tradier has no chain history), or (b) a Black–Scholes proxy per record using the stock path (have), a strike rule, DTE rule, `realized_volatility_pct` (`features.py:67-73`, 20-day) or an IV proxy, and a rate — labelled as a proxy in the record. New record fields needed either way: `stop_price, target_price, trim_price, exit_price, exit_ts, contract_spec, option_entry_mark, option_exit_mark, contract_return_pct, pricing_basis`.

---

## 6. Reclaim entry

Today the only trigger is `breakout_close > control_top` / `< control_bottom` with the prior-close bias (`potter_box.py:108-109`). The method's primary trigger is the 24h close back through the cost basis after losing it (R20, R22, R28); the code has the *state* (`_cost_basis_state` returns `reclaimed`, `potter_doctrine.py:84-100`; 619 of 2,344 `potter_passed` rows carry it) but only as a score term.

Where it slots without disturbing the breakout path:

- **Detector:** do not edit `detect_potter_box` (pinned, section 7). Add a v3 function, e.g. `scanner/potter_v3/entries.py: cost_basis_reclaim_entry(sessions, box, idx) -> Entry | None`, that needs the box's `cost_basis` and the last two ETH closes (prior close < cost_basis, current close > cost_basis, with the box still valid per R9/R31). A `breakout_entry` twin reproduces the current rule on ETH candles so both can be compared on the same boxes.
- **Record builder:** `build_edge_records_from_bars` derives `direction/entry` only from `pb` (`retrieval.py:221-231`). A v3 builder emits one record per `(box_id, entry_kind)` with `entry_kind ∈ {"breakout", "cost_basis_reclaim", "control_retest"}`, `entry_ts`, `entry_price`, and de-overlaps per box instead of per bar. Do not write these into `EDGE_INDEX_PATH`; `load_edge_index` drops unknown keys (`retrieval.py:530-534`) but the retired lab would still ingest the rows.
- **Prior art to cite in the preregistration:** the 2026-08-18 experiment tested a 3-bar *control-level* retest on RTH daily bars and falsified it (`experiments/20260818_retest_entry/REPORT.md`); `RETIRED.json` `revival_requires[0]` forbids "a retest ... slice of the retired design". A cost-basis reclaim on 24h-ETH candles with an empty-space target is a different mechanism (R22 vs. R23/R24), and the preregistration must say so explicitly.

---

## 7. Guards you must not trip

### 7.1 Retirement / readiness / live guards

| guard | where | effect |
|---|---|---|
| `RETIREMENT_MARKER_PATH = ROOT_DIR / "RETIRED.json"` | `config.py:8` (imported `main.py:59`) | path only |
| live preflight: `if mode == "live" and RETIREMENT_MARKER_PATH.is_file(): return False` | `main.py:473-479` | blocks `--mode live` only; **no research mode reads the marker** |
| scheduled wrapper: `if exist "%~dp0RETIRED.json" ... exit /b 0` | `scanner/run_research_ops_scheduled.bat:4-7` | skips scheduled `research_ops`; `scheduled_research_ops.py` itself does not check |
| `BRIEF_TELEGRAM_ENABLED = False` | `config.py:76-79`; consumed `brief.py:885` | no Telegram sends from briefs |
| docs that pin the state | `REPO_MAP.md:20`, `scanner/README.md:4-9`, `docs/RETIREMENT-2026-08-20.md:90,116`, `docs/daily-notes/2026-08-20.md:44` | policy |
| tests | `tests/conftest.py:19,31,38` (marker redirected to `tmp_path`), `tests/test_package_entrypoint.py:142-148`, `tests/test_scheduled_research_ops.py:11-16` (pins the `.bat` text) | |
| other live gates (all after the marker) | `main.py:481-618` (provider creds, Telegram, `LIVE_MODE_ENABLED`, audit ≤24h, `readiness == paper_trade_only`, same-run provenance, runtime fingerprint, evidence timestamps, promotable direction + execution-ready candidate); `_authorize_live_candidate` `main.py:660-737`; `candidate_execution_ready` `audit.py:92-122` | |
| runtime fingerprint | `evidence/provenance.py:9-36` hashes every `scanner/**/*.py` except `tests/`, `reports/`, `logs/`, `research/experiments/` | **`scanner/potter_v3/*.py` is inside the hashed set**; adding/editing it changes the fingerprint. Harmless for the audit (scan/validation/expected are computed in one `run_edge_lab` process) and moot for live (blocked at 473 first), but any pre-existing `edge_audit_report.json` stops matching the current runtime. Accept and document, or place code under `research/experiments/` (excluded) — editing `provenance.py` to add an exclusion would itself touch the retired path. |

Also never write to: `EDGE_INDEX_PATH`, `EDGE_*_REPORT_PATH` (`config.py:14-19`), `reports/scan_decisions.jsonl`, `tuning/overrides.json`, `reports/calibration_summary.json` (it changes live anchors), `reports/trial_registry.jsonl` with existing kinds (`calibration_trial`, `adaptive_policy`, `autotune`, `exit_geometry_trial` are read back by `_previous_calibration_passes`/adaptive policy); a new kind such as `potter_v3_trial` via `record_trial` (`trial_registry.py:19-27`) is safe and keeps the multiple-testing count honest.

### 7.2 Tests that pin current semantics

- `tests/test_potter_box.py`: `box_top == 101.0` is the wick max and `breakout_close > box_top` (28-32); prior close below cost basis fails (35-39); compression flags false yet `passed` true (42-56); an 18-bar window passes (59-67); near-breakout research scoring (70-79); runtime threshold (82-95).
- `tests/test_potter_doctrine.py`: reclaim only with hand-supplied controls (40-51); pre-breakout touch is `fresh_breakout` (54-62); `failed_reentry` + `cost_basis_lost` (65-73).
- `tests/test_empty_space.py`: score 0 when the nearest high is 0.1 above (20-25); `rr ≥ 1.5 → score ≥ 2` (28-33); bearish `rr ≥ 2.5 → 3` (36-41); `next_target` semantics (44-63); **"one level above → nearest 101, next None" (66-71) pins that `hist` includes every prior bar, box included**.
- `tests/test_config_hot_reload.py:66-76`: empty-space gate reads live `MIN_RR`/`MIN_EMPTY_SPACE_SCORE`.
- `tests/test_edge_features.py`: `potter_passed == 1.0`, `breakout_distance_pct > 0`, `volume_expansion > 1`, `feature_version` present on the 40-bar fixture (22-34); option provenance keys (37-63); doctrine keys (66-88).
- `tests/test_edge_retrieval.py`: analog ranking (5-39), same-ticker embargo (42-74), `EDGE_EMBARGO_DAYS == 11` (77-110), cross-ticker embargo `== 11` (113-151), index/brute-force parity (154-203), `allow_future=False` (206-243).
- `tests/test_edge_retrieval_quality.py`: distance ignores price-level features (37), direction match (64), cross-ticker embargo (81), purge config (115), Kronos neutrality (174, 188).
- `tests/test_triple_barrier_outcomes.py`: `resolve_trade_risk_pct` (158-164), plan modes incl. `none` (166-210), no-target rides to horizon / still stops (213-250), config default (252-258), `_future_outcome` stamps geometry (260-296).
- `tests/test_edge_cli_units.py`: `_score_edge_for_bars` returns a candidate on its 45-bar fixture (67-84) — depends on `detect_potter_box` passing it; option fields (86-96); doctrine payload (98-106).
- `tests/test_edge_evidence_lab.py`: monkeypatches `scanner.main.fetch_daily_bars(ticker, research=False, adjustment="raw")` and `scanner.main.build_edge_records_from_bars(ticker, bars, horizon)` by signature (66, 93-94, 114) — changing either signature breaks them; fail-closed on a contract violation (80-102).
- `tests/test_kronos_research_wiring.py:41-53, 141-165`: monkeypatches `scanner.main.detect_potter_box / score_potter_research_candidate / score_empty_space / score_potter_doctrine_v2` by name — those names must stay importable from `scanner.main`.
- `tests/test_package_entrypoint.py:55-396`: every live-preflight branch.
- `tests/conftest.py:12-70` (autouse): redirects `REPORT_DIR, EVIDENCE_DIR, TUNING_DIR, RETIREMENT_MARKER_PATH, OVERRIDES_PATH, EDGE_*` on `scanner.config` and `scanner.main`, plus `REPORT_DIR` on `outcome_store, outcome_reviewer, replay_runner, trial_registry, adaptive_policy, autotuner, brief, backtest_runner`; deletes `TRADIER_API_TOKEN`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`. A v3 module that does `from ..config import REPORT_DIR` at import time would escape this isolation; read `scanner_config.REPORT_DIR` at call time (as `potter_v3/sessions.py:41-43` does). No conftest fixture provides bars or records; each test file builds its own (`_make_synthetic_df`, `_bars`, `_daily_bars`, `_edge_record`).

---

## 8. Scoring / ranking layer

`score_edge_candidate` (`scoring.py:62-207`) turns a feature dict plus k=7 direction-matched analogs (`find_analogs`, `retrieval.py:296-355`; distance = RMS of scale-normalised differences over `ANALOG_FEATURE_KEYS`, `retrieval.py:48-77, 115-125`) into a 0–100 `edge_score`: base 30 + setup quality (`0.15×research_score + 5·potter + 2×empty_space_score`, cap 24) − 25 if neither `potter_passed` nor `empty_space_passed` + doctrine ±15 around `DOCTRINE_V2_SCORE_BASELINE` + `4×rr` (cap 12) + net analog expectancy (`25×avgR + 20×(win−0.5)`, [−30, 35]) − analog return std (cap 12) − sample penalty (111-134); capped at 44 when the setup gate fails (138); `promote` needs ≥65, positive net analog R, ≥`EDGE_MIN_ANALOGS`, data/feed/options gates (140-153), `research` needs ≥45 (154). Because `empty_space_score` is 0 and `rr ≈ 0` on essentially every row, the setup-quality and reward-risk terms are constants and the score is driven by `research_score` and analog outcomes — the ranking bet that failed (rank IC 0.036, `RETIRED.json`). For the rebuild: reuse `apply_transaction_costs` (`validation.py:35-74`), `walk_triple_barrier`, `edge/stats.py` (`day_clustered_t`, `day_clustered_precision`, `spearman_rank_ic`, `wilson_lower_bound`, `_hac_day_mean_summary`), `EvidenceRun`, `record_trial`; bypass `find_analogs`/`score_edge_candidate`/`extract_edge_features` entirely.

---

## 9. Recommended seams for `potter_v3`

Design rule: v3 imports *from* the retired package (data, outcomes, stats, evidence) and is never imported *by* it; it never touches `scanner/main.py`, the `--mode` list, `detect_potter_box`, `score_empty_space`, `build_edge_records_from_bars`, `EDGE_INDEX_PATH`, or any report path the lab/brief/preflight reads. The retired path then stays byte-for-byte unchanged (only the runtime fingerprint moves, section 7.1).

**Package `scanner/potter_v3/`** (already started; `__init__.py` states the isolation contract):

- `sessions.py` — exists. Add `validate_sessions(sessions) -> tuple[list[str], list[str], dict]` wrapping `check_ohlcv_contract(sessions[["Open","High","Low","Close","Volume"]], profile="daily")` and `check_session_completeness(sessions)`; add the ETH-inclusion probe as a test-time assertion on `bar_count`.
- `boxes.py` — `@dataclass Box(ticker, start_ts, end_ts, control_top, control_bottom, wick_top, wick_bottom, cost_basis, top_waves, bottom_waves, quality, status)`; `find_boxes(sessions: pd.DataFrame, *, min_waves: int = 2, wick_cluster_tol_pct: float) -> list[Box]` — a stateful pass that opens a box on consolidation, counts *waves* (R3) not candles, keeps it open until a 24h close outside it (R9), and lets boxes overlap (R6). Levels per R2a/R2b/R11: bodies define the edge, repeated wicks may extend it — parameterise, do not hard-code.
- `empty_space.py` (v3) — `measure_empty_space(sessions, box, idx, direction) -> EmptySpace(kind: "bounded"|"unbounded", void_start, void_end, target, trim_50, first_structure_ts, lookback_bars)`; scans left **excluding the box and the impulse that formed it**, identifies the first prior structure (body/consolidation, R34) or a gap/vertical move (R32); `unbounded` when none — never a zero.
- `entries.py` — `breakout_entry(...)`, `cost_basis_reclaim_entry(...)`, `control_retest_entry(...)` → `Entry(kind, ts, price, stop_price, stop_kind: "close_in_box"|"wick_midpoint", box_id)`.
- `outcomes.py` (v3) — `walk_plan(sessions, entry, target, trim_50, horizon) -> StockOutcome` built on `walk_triple_barrier` (two calls: to `trim_50`, then runner to `target`/horizon) plus `option_proxy_outcome(stock_outcome, strike_rule, dte_rule, iv_proxy) -> OptionOutcome` clearly labelled `pricing_basis="bs_proxy"`; costs via `apply_transaction_costs` at `EDGE_COST_BPS_PER_SIDE` for stock, a separate per-contract cost for options.
- `records.py` — `@dataclass V3Record` (`ticker, box_id, entry_kind, entry_ts, entry_price, stop_price, target_price, trim_price, empty_space_kind, box: dict, stock: dict, option: dict | None, session_kind, source_hashes`); `build_v3_records(ticker, sessions) -> list[V3Record]`; `save/load` at `scanner_config.REPORT_DIR / "potter_v3" / "records.json"` (resolved at call time).
- `lab.py` + `__main__.py` — `python -m scanner.potter_v3 --mode build|evaluate --as-of YYYY-MM-DD --experiment <dir>`; uses `start_evidence_run(mode="potter_v3_lab", root_dir=scanner_config.REPORT_DIR/"potter_v3"/"evidence")` (`evidence/store.py:130-141`; `record_rows/record_metrics/log_artifact/flush` at 51-111) and `record_trial("potter_v3_trial", ...)`. No Telegram, no scheduled task, no `main.py` mode.

**Experiments** under `scanner/research/experiments/<date>_potter_v3_<name>/` following the existing contract (`preregistration.json` with `hypothesis/null/rule/controls/acceptance_gates/falsification/amendments` as in `20260818_retest_entry/preregistration.json`; a `run_experiment.py` that prints JSON and mutates nothing; `results.json`; `REPORT.md`). Reuse `_hac_day_mean_summary` with lag = wait + horizon, the same-setup and drift-placebo controls from `20260818_retest_entry/run_experiment.py:57-118`, and the SHA-256 input-hash pattern (`run_experiment.py:44-49`) over the ETH cache pickles. Note `research/experiments/` is excluded from the runtime fingerprint (`provenance.py:26-27`), so harness code there never perturbs production provenance.

**Tests**: `scanner/tests/test_potter_v3_*.py` only; construct bars in-file like the existing suites; never import `scanner.main` (it loads Kronos/MiniMax adapters and the retired wiring).

**Bars**: the RTH daily cache `research/experiments/20260813_horizon_sweep/bars_cache.pkl` (55 tickers, used by every August experiment) is the right control set for "same setups, different candle" comparisons; the ETH cache comes from `sessions.load_eth_sessions` for `sessions.research_universe()`.

---

## Summary

1. Empty-space starvation is a scorer bug, not a market fact: no prior high above the entry → target = max prior high *below* entry → reward 0 → `rr 0.00` (415 of 2,344 setups); otherwise the box's own wicks/recent swing sit 0.07–0.87% away against a ~10% midpoint risk; 2 of 2,344 pass, both TTD.
2. `detect_potter_box` is "the 15 bars before me" with close-based controls, candle-count touches (≥2/≥2 within `max(10% box, 0.15%)`), and a last-close-outside-control trigger; no box lifecycle, no waves, no reclaim.
3. Doctrine v2 `reclaim` is unreachable on production controls (0 of 11,030 rows) and never gates anything.
4. 79% of index records are non-setups admitted by the `research.get("direction")` fallback (`retrieval.py:223-224`).
5. The index is RTH daily (`fetch_daily_bars`, `prepost=False`); the scan already runs on 04:00–20:00 ETH synthetic sessions labelled a day early (anchor 20:00), with seven tickers on 16:00–18:00 anchors calibrated against RTH TradingView exports.
6. Alpaca pagination can reach 2 years of 30m SIP bars behind the 16-minute delay; ETH inclusion in `30Min` bars is asserted by the new `potter_v3/sessions.py` but not confirmed by the docs fetched — probe it.
7. Outcomes: entry at decision close, wick stop at the box midpoint, no target (`EDGE_EXIT_TARGET_MODE="none"`), 5-bar horizon, ±10R clamp, 25 bps/side charged downstream; journal R uses a different (ATR) denominator.
8. Options: no historical chain; the seam is `_future_outcome`; a labelled BS proxy is the realistic first step.
9. Only `--mode live` and the scheduled `.bat` read `RETIRED.json`; research modes are not blocked, and `scanner/potter_v3/*.py` is inside the runtime fingerprint.
10. Signatures pinned by tests: `fetch_daily_bars(ticker, research, adjustment)`, `build_edge_records_from_bars(ticker, bars, horizon)`, and the four strategy names imported into `scanner.main`.
11. Reuse: `walk_triple_barrier`, `apply_transaction_costs`, `edge/stats.py`, `EvidenceRun`, `record_trial`, `build_synthetic_sessions`, `bar_contract`; bypass analogs/edge score/features.
12. Build v3 as a sibling package with its own records path, CLI entry (`python -m scanner.potter_v3`), experiment dirs, and tests; never write to the lab's report paths.
