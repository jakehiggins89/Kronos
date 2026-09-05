# Potter v3 pre-registration

Registered 2026-09-05, before any outcome of the full index was read. Companion
file `preregistration.json` carries the SHA-256 of every input bar file and the
exact as-of timestamp; the build and evaluation must be run with that as-of so
the inputs are byte-identical to what is registered here.

## Why this exists

The retired scanner (see `docs/RETIREMENT-2026-08-20.md`) never encoded the
Potter Box method it was named after. `METHOD_SPEC_FROM_SOURCES.md` documents,
rule by rule from the primary sources, where it diverged: regular-session daily
bars instead of the 24-hour extended-hours candle he calls "imperative";
breakout-close entries only, when the cost-basis reclaim ("punch back") is the
trigger he calls "the entirety of everything that I do"; a fixed five-bar hold
with no target instead of structure targets, a 50% trim and a two-to-three
session hold; stock-path P&L when every return he quotes is an option
contract; and an empty-space scorer that returned zero on 2,340 of 2,344
detector-passing setups (`CODE_GAP_MAP.md`, section 0).

This is therefore a test of a **new mechanism** under revival criterion 1 of
the retirement record, not a threshold, target, horizon, regime, retest, stop,
chart-pattern, loss-function or subgroup variation of the retired design. It
does not remove `scanner/RETIRED.json`, re-enable any schedule, or send any
alert; a passing result would only justify the next criterion (twenty new
post-retirement market days of paper confirmation), never live capital.

## Hypothesis

H1: On 24-hour extended-hours sessions, the bullish cost-basis punch back
(a 24h close through the box midline after the box lost and reclaimed its
floor), read at the 16:00 close and managed as the method describes, has
positive net expectancy on the stock path over three sessions, and beats a
same-day, same-direction, same-geometry entry on a universe name with no setup.

H0: it does not (net expectancy indistinguishable from zero, or from the
same-day drift control).

## Fixed inputs

- Universe: `scanner.config.DEFAULT_WATCHLIST` + `EDGE_INDEX_EXTRA_UNIVERSE`
  (55 names), the same universe every retired-era experiment used.
- Bars: Alpaca SIP 30-minute bars, split-adjusted, 04:00-20:00 ET, ~740
  calendar days, cached under `scanner/reports/potter_v3_cache/` and hashed in
  `preregistration.json`. As-of `2026-09-05T00:00-04:00`.
- Sessions: one candle per trading date from those bars (04:00-20:00), plus
  the same candle cut at 16:00 for the reading; the in-progress session is
  dropped.

## Fixed rules (constants in code, never tuned against outcomes)

- Box: body-extreme range over the longest window of 5-30 completed sessions
  before the reading session with >= 2 rejection waves at each edge (touch
  tolerance 15% of box height), waves interleaving, height >= 1% of price.
  Cost basis = midpoint. Boxes void after 40 sessions or a close more than one
  box height beyond an edge.
- Triggers (16:00 close vs. prior 24h close vs. active box): breakout,
  breakdown, cost-basis break (bull/bear), punch back (cost-basis break with a
  close outside the edge within the last 10 sessions of this box), floor
  reclaim, ceiling reject.
- Plan: targets are the box edge and then the first prior candle body beyond
  it (structure to the left, searched before the box formed, 250-session
  lookback); breakouts trim half at 50% of that empty space; stop is a 24h
  close back through the defining level, executed at the next regular open;
  the remainder exits at the 10:30 print on the last session. Legs already
  passed by the entry are dropped.
- Costs: 25 bps per side on the stock leg (project floor). Contract leg:
  Black-Scholes with 20-session realised volatility, strike at the target
  (snapped to listed increments), 10 calendar days to expiry (14 for
  bearish), $0.05 premium floor, 10% spread haircut per side. The contract
  number is a proxy and is reported, not gated.
- Untradeable (recorded, excluded): price below $5; breakouts/breakdowns into
  open air (no prior structure), because he does not trade all-time highs.
- Overlap: a trigger inside the hold window of an earlier same-direction
  trigger is excluded from every cell (same open position).
- Control: for every eligible trigger, one universe name with no trigger that
  day, chosen by a seeded RNG (seed 20260905), entered at its own 16:00 close
  with the same percent geometry and horizon.

## Primary cell and acceptance (one primary, all others descriptive)

Primary: kind `punchback_bull`, tradeable, non-overlapping, resolved, horizon
3 sessions, stock leg net of costs. Pass requires ALL of:

| gate | threshold |
|---|---|
| independent entry days | >= 60 |
| HAC t of entry-day mean net return (5 lags) | >= 2.0 |
| HAC t of paired difference vs. the same-day control | >= 2.0 |
| day-clustered precision lower bound (net return > 0) | >= 0.45 |

Secondary cells (13 cells x 3 horizons = 39 evaluations, logged for
multiplicity, none of which can turn a failed primary into a pass):
`cb_break_bull`, `breakout_es1plus`, `breakout_all`, `floor_reclaim`,
`punchback_bear`, `cb_break_bear`, `breakdown_es1plus`, `breakdown_all`,
`ceiling_reject`, `punchback_bull_confirmed_24h`, `all_bullish`,
`all_bearish`, at horizons 1, 3 and 5.

## Falsification

If the primary cell fails any gate, the verdict is that the method as encoded
here shows no exploitable edge on this universe and period, and the retirement
stands. No threshold, window, tolerance, horizon, target, or contract
parameter will be changed and re-run; any follow-up would be a new
pre-registration with a genuinely different mechanism.

## Disclosures

- Before this document was written, a two-ticker (SOFI, PLTR) mechanical smoke
  run of the pipeline printed per-kind mean returns for those two names. The
  cells, gates and rules above were authored in the same step, before that
  output was read, and were not changed afterwards. The full-universe index
  had not been built or read.
- The machine has a documented history of silent compute corruption
  (`memory: hardware-fault-silent-corruption`); the test suite's canary
  passed on 2026-09-04 and 2026-09-05, but every number remains subject to
  that caveat until MemTest86 is run.
- Historical earnings dates are not available for the period, so the method's
  earnings filter is not applied; records are not flagged for it.
- No historical option chains exist in this project; the contract leg is a
  labelled Black-Scholes proxy with realised volatility and cannot capture
  IV expansion or crush.
- The synthetic 24h candle was never calibrated against a TradingView 24h
  extended-hours export (the April 2026 calibration used regular 1D exports).
