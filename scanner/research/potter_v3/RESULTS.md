# Potter v3 results — 2026-09-05

Pre-registration: `PREREGISTRATION.md` / `preregistration.json`, committed at
386039a before any outcome was read. Inputs: 55 names, Alpaca SIP 30-minute
bars 2024-08-21 to 2026-09-04 (as-of 2026-09-05T00:00 ET, file hashes in the
registration). Full tables: `evaluation_2026-09-05.md` / `.json`. Trial
registered in `scanner/reports/trial_registry.jsonl` as `potter_v3_trial`.

## Verdict: FAIL on every pre-registered gate. The retirement stands.

Primary cell: bullish punch back (24h close through the box midline after the
box lost and reclaimed its floor), read at the 16:00 close, three-session plan.

| gate | value | required |
|---|---:|---:|
| independent entry days | 56 (62 signals, 35 names) | >= 60 |
| HAC t, entry-day mean net return | -1.45 | >= 2.0 |
| HAC t, paired difference vs same-day control | -0.08 | >= 2.0 |
| day-clustered precision lower bound | 0.32 | >= 0.45 |

Supporting numbers for that cell:

| quantity | value |
|---|---:|
| mean gross return (stock leg) | +0.03% |
| mean / median net return (25 bps per side) | -0.47% / -0.20% |
| win rate (net > 0), Wilson lower bound | 46.8%, 0.39 |
| median MFE / MAE over the hold | +1.95% / -1.86% |
| legs filled: none / box edge only / edge and structure | 34 / 11 / 16 |
| exits: stop on 24h close / target / 10:30 horizon | 32 / 21 / 9 |
| median box height, median risk to cost basis | 10.5%, 1.0% |
| empty-space score 0 / 1 / 2 | 58 / 3 / 1 |
| same-day control, mean net return | -0.88% |
| modelled contract: mean / median net return, win rate | -17.5% / -31.2%, 27.9% |

## What the whole index says

- 5,522 triggers; 2,615 tradeable and non-overlapping (43% overlap with an
  open same-direction position; 555 breakouts/breakdowns into open air; 458
  reads under $5).
- All 39 cells (13 families x 3 horizons) are net negative on the stock leg.
  Gross returns sit at or near zero everywhere, so the round-trip cost floor
  is the entire loss: there is no drift to pay it.
- Bearish cells are the worst, as in every earlier study on this universe:
  punch-back bear -1.29% (t -2.54), ceiling reject -1.14% (t -4.27), all
  bearish -0.97% (t -5.67).
- The same-day drift controls are as negative as the triggers (-0.3% to
  -1.5%). Paired differences are small and mixed; two of 39 cells reach
  |t| >= 2 (floor reclaim at one session +2.17, punch-back bear at three
  sessions -2.11), which is the count chance produces.
- The contract leg loses 15-40% on average in every cell. With a $0.05 floor
  and a 10%-per-side spread on cheap out-of-the-money ten-day contracts, the
  spread alone is a ~20% round trip and theta takes the rest; the stock path
  would need to move several percent in a few sessions to cover it, and it
  does not (median MFE about +2%).
- Confirming the trigger on the finished 24h candle (51 of 62 punch backs)
  changes nothing (-0.50%).

## Reading

1. The method as its author describes it, encoded as faithfully as the
   sources allow and run on the exact candle he insists on, shows no
   exploitable edge on liquid US names over the last two years after
   realistic costs. This is a different and stronger negative than the
   retirement record's: that one tested a detector the method never
   specified; this one tests the specification.
2. The structure that fails is not the box but the arithmetic: a 1% stop to
   cost basis against targets one box height away, a 50% hit rate, and 50
   bps of round-trip cost. His own hit-rate claim (about 7 in 10, R J of the
   spec) is not reproduced: 47%.
3. What this test could not do, and what a genuinely different next attempt
   would need: his 1h/4h lower-timeframe entries with intraday management
   (R18, R25), real option chains instead of a Black-Scholes proxy (R42-R47),
   an earnings filter with historical dates (R49), and the discretionary
   chart selection he calls "every chart needs your discretion" (R2b). None
   of these are a constant to tune in this code.

## Guardrails honoured

No threshold, window, tolerance, horizon, target or contract parameter was
changed after registration, and none will be re-run. `scanner/RETIRED.json`
is untouched; no schedule was created; nothing here can alert. The two-ticker
smoke run disclosed in the registration is the only outcome read before it.

## Caveats

- Hardware: this machine has a documented history of silent compute
  corruption; the test canary passed on 2026-09-04 and 2026-09-05, but the
  numbers inherit the caveat until MemTest86 is run.
- The synthetic 24h candle was never calibrated against a TradingView 24h
  extended-hours export.
- Universe drift over the period was negative (controls), so a bullish
  method was tested in a market that did not help it; the paired control is
  the defence against reading that as the method's fault or its excuse.
