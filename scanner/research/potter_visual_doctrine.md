# Potter Visual Doctrine (From Manual Dataset + Video Transcript)

Source inputs used:
- `C:/Users/Jacob Higgins/Downloads/Potter_Box_Visual_Dataset/Potter_Box_Visual_Dataset.md`
- `C:/Users/Jacob Higgins/Downloads/10 videos transcribed.txt`
- Example charts/screenshots shared in thread.

## Encoded Rules (Implemented)
1. Candle closes have priority over wick extremes for control logic.
2. Box control uses top/bottom close levels, while high/low are retained for context.
3. Cost basis is computed from control levels (50% midpoint).
4. Consolidation quality includes minimum top/bottom touch counts.
5. Break/breakdown requires close outside control level plus prior-close bias vs cost basis.
6. Diagnostics now capture:
   - control top/bottom
   - touch count and tolerance
   - breakout open and whether open was outside control zone

## Default Parameters
- `MIN_BOX_TOP_TOUCHES = 2`
- `MIN_BOX_BOTTOM_TOUCHES = 2`
- `BOX_TOUCH_TOLERANCE_PCT = 0.0015`
- `USE_CLOSE_BASED_CONTROL = True`

## Not Yet Fully Encoded
1. Full "punchback chain reaction" state machine across nested boxes.
2. Explicit overlap-box hierarchy scoring.
3. Timeframe-conditioned rules (24h primary, 4h support) in one unified signal model.
4. Pattern aging rules from transcript (e.g., 2-4 day consolidation cadence) as hard constraints.

These can be added once more labeled chart examples and desired strictness are finalized.
