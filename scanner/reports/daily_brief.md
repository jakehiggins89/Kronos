# Kronos Daily Brief — 2026-07-02

## Verdict
**blocked** — NOT live-ready. Evidence gates are failing; live alerting stays off.

## Evidence progress
- Ranking gate (not yet): rank IC 0.000 (need >= 0.07, p 1.000), top-decile signals 0/20, avg R 0.00, t 0.00, Wilson-LB precision 0.00 (need >= 0.45)
- Legacy threshold-55 gate (not yet): 0/20 signals
- Directions: bullish n=379 avgR 0.17; bearish n=221 avgR -0.04 BLOCKED

## Today's scan
- 30 tickers scanned: 17 skip, 13 reject
- T: bearish edge 7.05 — blocked by setup_gate_failed, non_positive_analog_expectancy, options_data_not_execution_grade
- RIVN: bullish edge 6.42 — blocked by setup_gate_failed, options_data_not_execution_grade, edge_score_below_research_threshold
- GME: bullish edge 2.21 — blocked by setup_gate_failed, options_data_not_execution_grade, edge_score_below_research_threshold

## Learning loop
- Journal: 22 resolved research candidates (8W/14L, 36.4% WR), 6 pending
- Policy: hold_current_threshold_pending_samples (threshold 72) — current threshold needs more resolved samples before another automatic tightening
- Kronos lift: no scored research candidates yet (accumulating from today forward)
- Doctrine v2: 8 resolved, baseline cohort 2W/1L avg 3.92%

## Open issues
- validation_threshold_55_unsupported: The absolute score-55 gate has no supporting signals. Fix: expected while scores stay compressed; the ranking gate is the realistic path.
- ranking_evidence_unsupported: The score does not yet rank outcomes strongly enough out-of-sample. Fix: keep daily research_ops running so walk-forward samples accumulate.
- low_feed_confidence: Equity bars come from the free IEX-only feed. Fix: acceptable for research; full-SIP data (Alpaca ATP or Polygon Starter) clears it.
- options_liquidity_missing: Open interest / volume / spread fields are missing on some candidates. Fix: same fix as execution-grade options data.
- options_data_not_execution_grade: Options quotes are indicative (free Alpaca feed), never execution-grade. Fix: open a free Tradier brokerage account (real-time OPRA + open interest) or pay for Alpaca Algo Trader Plus.
- no_current_actionable_candidates: Nothing on the watchlist is near a qualifying setup today. Fix: normal; the scanner is supposed to be quiet most days.
- bearish_edge_negative: Bearish setups have negative expectancy in validation. Fix: bearish promotion stays blocked until bearish evidence turns positive.

## Next action
Data decision: open a free Tradier brokerage account (real-time OPRA options + open interest, $0) or upgrade Alpaca to Algo Trader Plus ($99/mo). This is the only blocker code cannot fix.
