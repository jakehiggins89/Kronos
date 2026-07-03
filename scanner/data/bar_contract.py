"""Fail-closed data contract for OHLCV bars feeding the evidence engine.

Every triple-barrier outcome and every feature in the edge index is only as
honest as the bars underneath it. This module enforces the hard per-bar
invariants before any bar set is allowed to become evidence; violations fail
the ticker rather than silently producing fake trade outcomes.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")

# One-day moves beyond this are almost always a missed corporate action on
# unadjusted data rather than a real repricing; they are surfaced as warnings
# (not violations) so a genuine crash cannot silently delete a ticker.
SUSPECT_MOVE_PCT = 45.0


def check_ohlcv_contract(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Return (violations, warnings) for a bar frame.

    Violations are hard invariant breaches - the bars must not become
    evidence. Warnings flag suspicious-but-possible data for the report.
    """
    violations: list[str] = []
    warnings: list[str] = []

    if df is None or df.empty:
        return ["empty bar frame"], warnings

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        return [f"missing columns: {', '.join(missing)}"], warnings

    ohlc = df[["Open", "High", "Low", "Close"]]
    nan_rows = int(ohlc.isna().any(axis=1).sum())
    if nan_rows:
        violations.append(f"{nan_rows} bars with NaN OHLC values")

    finite = df[~ohlc.isna().any(axis=1)]
    if not finite.empty:
        nonpositive = int((finite[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum())
        if nonpositive:
            violations.append(f"{nonpositive} bars with non-positive prices")

        body_high = finite[["Open", "Close"]].max(axis=1)
        body_low = finite[["Open", "Close"]].min(axis=1)
        bad_high = int((finite["High"] < body_high).sum())
        bad_low = int((finite["Low"] > body_low).sum())
        if bad_high:
            violations.append(f"{bad_high} bars with High below max(Open, Close)")
        if bad_low:
            violations.append(f"{bad_low} bars with Low above min(Open, Close)")

    volume = pd.to_numeric(df["Volume"], errors="coerce")
    negative_volume = int((volume < 0).sum())
    if negative_volume:
        violations.append(f"{negative_volume} bars with negative volume")

    index = pd.DatetimeIndex(df.index)
    if index.has_duplicates:
        violations.append(f"{int(index.duplicated().sum())} duplicate timestamps")
    if not index.is_monotonic_increasing:
        violations.append("timestamps not sorted ascending")

    if not finite.empty and len(finite) > 1:
        closes = finite["Close"].astype(float)
        day_moves = closes.pct_change().abs() * 100.0
        suspects = day_moves[day_moves > SUSPECT_MOVE_PCT]
        for ts, move in suspects.items():
            warnings.append(f"suspect one-bar move {move:.0f}% at {ts} (possible unadjusted corporate action)")

    return violations, warnings
