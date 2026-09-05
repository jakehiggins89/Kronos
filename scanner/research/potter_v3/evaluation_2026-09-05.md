# Potter v3 evaluation

**Verdict:** FAIL: primary cell does not clear the pre-registered gates

Primary cell `punchback_bull` at h3:

| gate | value | required | ok |
|---|---:|---:|---|
| entry_days | 56 | 60 | no |
| hac_t_net_return | -1.45 | 2.0 | no |
| hac_t_vs_control | -0.08 | 2.0 | no |
| precision_lower_bound | +0.32 | 0.45 | no |

Index: 5522 triggers, 2615 tradeable non-overlapping, 55 tickers, sessions 2024-08-26 to 2026-09-04, controls 2615.

## Cells (stock leg net of 25 bps/side; contract leg net of 10%/side spread)

| cell | h | n | days | mean net % | HAC t | win | prec LB | mean R | contract mean % | contract median % | control mean % | paired diff % | HAC t vs ctrl | exits |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| punchback_bull | h1 | 63 | 57 | -0.67 | -2.86 | +0.38 | +0.23 | -0.38 | -28 | -32 | -0.80 | +0.13 | +0.29 | horizon:47,stop_close:7,target:9 |
| punchback_bull | h3 | 62 | 56 | -0.47 | -1.45 | +0.47 | +0.32 | -0.26 | -18 | -31 | -0.88 | +0.41 | -0.08 | horizon:9,stop_close:32,target:21 |
| punchback_bull | h5 | 62 | 56 | -0.52 | -1.29 | +0.47 | +0.34 | -0.25 | -17 | -32 | -1.04 | +0.52 | +0.39 | horizon:3,stop_close:34,target:25 |
| cb_break_bull | h1 | 493 | 256 | -0.63 | -4.72 | +0.40 | +0.36 | -0.49 | -25 | -30 | -0.60 | -0.02 | +0.68 | horizon:390,stop_close:49,target:54 |
| cb_break_bull | h3 | 488 | 254 | -0.75 | -2.46 | +0.48 | +0.43 | -0.61 | -31 | -40 | -0.62 | -0.12 | +0.50 | horizon:127,stop_close:214,target:147 |
| cb_break_bull | h5 | 486 | 252 | -0.71 | -1.98 | +0.46 | +0.42 | -0.57 | -32 | -43 | -0.71 | +0.00 | +0.75 | horizon:59,stop_close:252,target:175 |
| breakout_es1plus | h1 | 24 | 22 | -0.68 | -1.59 | +0.38 | +0.21 | -0.04 | -29 | -29 | -0.33 | -0.35 | -0.81 | horizon:16,stop_close:3,target:5 |
| breakout_es1plus | h3 | 23 | 21 | -0.20 | -0.33 | +0.52 | +0.35 | +0.29 | -25 | -14 | -0.41 | +0.20 | +0.63 | horizon:3,stop_close:9,target:11 |
| breakout_es1plus | h5 | 23 | 21 | -0.01 | +0.12 | +0.57 | +0.40 | +0.35 | -24 | -14 | -0.59 | +0.58 | +0.69 | horizon:2,stop_close:10,target:11 |
| breakout_all | h1 | 444 | 250 | -0.45 | -3.07 | +0.39 | +0.35 | -0.54 | -22 | -21 | -0.48 | +0.03 | +0.15 | horizon:292,stop_close:33,target:119 |
| breakout_all | h3 | 441 | 249 | -0.34 | -1.61 | +0.43 | +0.37 | -0.40 | -19 | -22 | -0.34 | +0.01 | -0.15 | horizon:147,stop_close:138,target:156 |
| breakout_all | h5 | 440 | 248 | -0.36 | -1.82 | +0.42 | +0.37 | -0.44 | -21 | -26 | +0.13 | -0.48 | -1.76 | horizon:114,stop_close:168,target:158 |
| floor_reclaim | h1 | 282 | 169 | -0.20 | +0.00 | +0.44 | +0.40 | -0.13 | -15 | -24 | -0.64 | +0.44 | +2.17 | horizon:204,stop_close:23,target:55 |
| floor_reclaim | h3 | 279 | 167 | -0.21 | -0.14 | +0.50 | +0.43 | -0.22 | -17 | -35 | -0.88 | +0.66 | +1.69 | horizon:72,stop_close:104,target:103 |
| floor_reclaim | h5 | 278 | 166 | -0.33 | -0.86 | +0.47 | +0.41 | -0.19 | -20 | -40 | -0.83 | +0.50 | +0.90 | horizon:35,stop_close:125,target:118 |
| punchback_bear | h1 | 74 | 67 | -0.93 | -4.08 | +0.38 | +0.29 | -0.78 | -28 | -31 | -0.32 | -0.61 | -1.57 | horizon:57,stop_close:12,target:5 |
| punchback_bear | h3 | 74 | 67 | -1.29 | -2.54 | +0.32 | +0.23 | -1.24 | -38 | -39 | -0.41 | -0.89 | -2.11 | horizon:20,stop_close:41,target:13 |
| punchback_bear | h5 | 74 | 67 | -1.23 | -3.04 | +0.34 | +0.25 | -1.24 | -41 | -37 | -0.43 | -0.80 | -1.87 | horizon:14,stop_close:46,target:14 |
| cb_break_bear | h1 | 477 | 269 | -0.66 | -3.12 | +0.42 | +0.37 | -0.56 | -24 | -26 | -0.64 | -0.02 | -0.78 | horizon:395,stop_close:41,target:41 |
| cb_break_bear | h3 | 477 | 269 | -0.67 | -2.56 | +0.47 | +0.41 | -0.72 | -26 | -38 | -0.70 | +0.03 | -0.45 | horizon:153,stop_close:211,target:113 |
| cb_break_bear | h5 | 477 | 269 | -0.72 | -2.47 | +0.47 | +0.41 | -0.71 | -27 | -41 | -0.86 | +0.14 | -0.20 | horizon:83,stop_close:246,target:148 |
| breakdown_es1plus | h1 | 23 | 22 | -0.12 | -0.52 | +0.35 | +0.19 | -0.14 | -21 | -29 | -0.75 | +0.62 | +1.22 | horizon:14,stop_close:2,target:7 |
| breakdown_es1plus | h3 | 23 | 22 | +0.23 | +0.72 | +0.43 | +0.28 | -0.48 | -23 | -26 | -0.91 | +1.15 | +1.51 | horizon:6,stop_close:7,target:10 |
| breakdown_es1plus | h5 | 23 | 22 | +0.38 | +0.98 | +0.48 | +0.31 | -0.55 | -26 | -27 | -1.11 | +1.48 | +1.44 | horizon:3,stop_close:9,target:11 |
| breakdown_all | h1 | 436 | 236 | -0.55 | -3.16 | +0.40 | +0.33 | -0.53 | -21 | -21 | -0.99 | +0.44 | +1.28 | horizon:288,stop_close:41,target:107 |
| breakdown_all | h3 | 435 | 235 | -1.12 | -3.57 | +0.43 | +0.37 | -0.71 | -25 | -23 | -1.54 | +0.42 | +0.66 | horizon:120,stop_close:160,target:155 |
| breakdown_all | h5 | 429 | 233 | -1.14 | -2.79 | +0.44 | +0.38 | -0.70 | -24 | -24 | -1.23 | +0.09 | -0.05 | horizon:91,stop_close:181,target:157 |
| ceiling_reject | h1 | 337 | 220 | -0.82 | -4.58 | +0.33 | +0.29 | -0.72 | -26 | -29 | -0.62 | -0.20 | -0.41 | horizon:250,stop_close:27,target:60 |
| ceiling_reject | h3 | 337 | 220 | -1.14 | -4.27 | +0.39 | +0.35 | -0.88 | -31 | -39 | -1.10 | -0.04 | +0.07 | horizon:60,stop_close:164,target:113 |
| ceiling_reject | h5 | 336 | 219 | -1.24 | -4.00 | +0.40 | +0.37 | -0.99 | -33 | -43 | -1.30 | +0.06 | +0.52 | horizon:22,stop_close:186,target:128 |
| punchback_bull_confirmed_24h | h1 | 51 | 47 | -0.55 | -2.35 | +0.41 | +0.26 | -0.16 | -27 | -33 | -0.73 | +0.19 | +0.25 | horizon:43,target:8 |
| punchback_bull_confirmed_24h | h3 | 50 | 46 | -0.50 | -1.44 | +0.50 | +0.34 | -0.07 | -15 | -36 | -0.83 | +0.32 | -0.35 | horizon:9,stop_close:24,target:17 |
| punchback_bull_confirmed_24h | h5 | 50 | 46 | -0.57 | -1.28 | +0.50 | +0.35 | -0.05 | -14 | -39 | -0.96 | +0.39 | +0.10 | horizon:3,stop_close:26,target:21 |
| all_bullish | h1 | 1282 | 396 | -0.47 | -4.20 | +0.40 | +0.37 | -0.42 | -22 | -25 | -0.58 | +0.10 | +0.70 | horizon:933,stop_close:112,target:237 |
| all_bullish | h3 | 1270 | 394 | -0.47 | -2.21 | +0.46 | +0.41 | -0.43 | -23 | -30 | -0.59 | +0.12 | +0.82 | horizon:355,stop_close:488,target:427 |
| all_bullish | h5 | 1266 | 392 | -0.49 | -2.38 | +0.45 | +0.40 | -0.42 | -24 | -33 | -0.46 | -0.03 | -0.49 | horizon:211,stop_close:579,target:476 |
| all_bearish | h1 | 1324 | 393 | -0.68 | -6.52 | +0.39 | +0.32 | -0.60 | -24 | -25 | -0.73 | +0.05 | -0.72 | horizon:990,stop_close:121,target:213 |
| all_bearish | h3 | 1323 | 392 | -0.97 | -5.67 | +0.43 | +0.37 | -0.79 | -28 | -33 | -1.06 | +0.09 | -0.16 | horizon:353,stop_close:576,target:394 |
| all_bearish | h5 | 1316 | 390 | -1.02 | -4.54 | +0.44 | +0.39 | -0.81 | -28 | -34 | -1.07 | +0.05 | +0.09 | horizon:210,stop_close:659,target:447 |

Multiplicity: 39 cells evaluated, 1 primary.
