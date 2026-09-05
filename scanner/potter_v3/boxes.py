"""Box detection on 24-hour sessions, drawn the way the method draws them.

Source rules encoded here (numbers refer to research/potter_v3/METHOD_SPEC_FROM_SOURCES.md):
- R1/R2: a box is bounded by where sellers cap price (top) and buyers hold it
  (bottom). Edges sit at candle BODY extremes; wicks may pierce them (the INTC
  chart shows exactly that), so levels use max(open, close) / min(open, close).
- R3: each edge needs two or more rejection WAVES, where a wave is a run of
  consecutive sessions at the edge, not a single candle.
- R12: cost basis is the 50% mark of the box.
- R4/R10: a box is several sessions of sideways action, not a two-day pause, and
  a tiny box is not worth drawing.
- R9: a punched-through box is void, but its levels stay as reference.
- R34: the target through empty space is the first structure to the left, i.e.
  the nearest prior candle body beyond the edge, found before the box formed.

The only free numbers are the window bounds, the touch tolerance as a fraction
of box height, and the minimum box height; they are fixed constants here and
pre-registered, never tuned against outcomes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

MIN_BOX_SESSIONS = 5
MAX_BOX_SESSIONS = 30
TOUCH_TOLERANCE_FRACTION = 0.15
MIN_WAVES = 2
MIN_BOX_HEIGHT_PCT = 1.0
STRUCTURE_LOOKBACK_SESSIONS = 250


@dataclass
class Box:
    start: pd.Timestamp
    end: pd.Timestamp
    length: int
    top: float
    bottom: float
    top_waves: int
    bottom_waves: int
    nested_count: int = 1

    @property
    def cost_basis(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def height_pct(self) -> float:
        return self.height / self.cost_basis * 100.0 if self.cost_basis > 0 else 0.0

    def zone(self, price: float) -> str:
        if price > self.top:
            return "above_top"
        if price < self.bottom:
            return "below_bottom"
        if price >= self.cost_basis:
            return "upper_half"
        return "lower_half"

    def to_dict(self) -> dict:
        out = asdict(self)
        out["start"] = pd.Timestamp(self.start).isoformat()
        out["end"] = pd.Timestamp(self.end).isoformat()
        out["cost_basis"] = self.cost_basis
        out["height_pct"] = self.height_pct
        return out


def body_high(frame: pd.DataFrame) -> np.ndarray:
    return np.maximum(frame["Open"].to_numpy(dtype=float), frame["Close"].to_numpy(dtype=float))


def body_low(frame: pd.DataFrame) -> np.ndarray:
    return np.minimum(frame["Open"].to_numpy(dtype=float), frame["Close"].to_numpy(dtype=float))


def count_waves(mask: np.ndarray) -> int:
    """Number of maximal runs of True: consecutive touching sessions are one wave."""
    if mask.size == 0:
        return 0
    m = mask.astype(bool)
    starts = m & ~np.concatenate(([False], m[:-1]))
    return int(starts.sum())


def waves_interleave(top_mask: np.ndarray, bottom_mask: np.ndarray) -> bool:
    """Price must bounce between the edges, not touch one edge and then the other only.

    A rising channel touches the bottom early and the top late; a true range
    visits the top after the bottom AND the bottom after the top.
    """
    top_idx = np.flatnonzero(top_mask)
    bottom_idx = np.flatnonzero(bottom_mask)
    if top_idx.size == 0 or bottom_idx.size == 0:
        return False
    return bool(top_idx.min() < bottom_idx.max() and bottom_idx.min() < top_idx.max())


def _evaluate_window(highs: np.ndarray, lows: np.ndarray) -> tuple[float, float, int, int] | None:
    top = float(highs.max())
    bottom = float(lows.min())
    height = top - bottom
    mid = (top + bottom) / 2.0
    if mid <= 0 or height <= 0 or (height / mid) * 100.0 < MIN_BOX_HEIGHT_PCT:
        return None
    tol = height * TOUCH_TOLERANCE_FRACTION
    top_mask = highs >= top - tol
    bottom_mask = lows <= bottom + tol
    top_waves = count_waves(top_mask)
    bottom_waves = count_waves(bottom_mask)
    if top_waves < MIN_WAVES or bottom_waves < MIN_WAVES:
        return None
    if not waves_interleave(top_mask, bottom_mask):
        return None
    return top, bottom, top_waves, bottom_waves


def find_box(
    sessions: pd.DataFrame,
    end: int,
    *,
    min_len: int = MIN_BOX_SESSIONS,
    max_len: int = MAX_BOX_SESSIONS,
) -> Box | None:
    """The box formed by the sessions strictly before position ``end``.

    Tries every window length from longest to shortest and returns the
    longest qualifying range (the structure he would have drawn and dragged
    forward); ``nested_count`` is how many lengths qualified, a proxy for
    overlapping boxes at the same location.
    """
    if sessions is None or end < min_len:
        return None
    highs_all = body_high(sessions)
    lows_all = body_low(sessions)
    best: Box | None = None
    qualifying = 0
    for length in range(min(max_len, end), min_len - 1, -1):
        highs = highs_all[end - length : end]
        lows = lows_all[end - length : end]
        result = _evaluate_window(highs, lows)
        if result is None:
            continue
        qualifying += 1
        if best is None:
            top, bottom, top_waves, bottom_waves = result
            best = Box(
                start=sessions.index[end - length],
                end=sessions.index[end - 1],
                length=int(length),
                top=top,
                bottom=bottom,
                top_waves=int(top_waves),
                bottom_waves=int(bottom_waves),
            )
    if best is not None:
        best.nested_count = qualifying
    return best


@dataclass
class Structure:
    level: float | None
    kind: str
    session: pd.Timestamp | None
    distance_pct: float | None
    space_over_height: float | None
    next_level: float | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["session"] = pd.Timestamp(self.session).isoformat() if self.session is not None else None
        return out


def structure_beyond(
    sessions: pd.DataFrame,
    box: Box,
    direction: str,
    *,
    lookback: int = STRUCTURE_LOOKBACK_SESSIONS,
) -> Structure:
    """First structure to the left beyond the box edge in the trade direction.

    Bullish: the lowest prior candle body-low above the top, among sessions
    before the box formed. Bearish: the highest prior body-high below the
    bottom. No such body means price is in open air (all-time-high style),
    which the method does not trade (R55).
    """
    if direction not in {"bullish", "bearish"}:
        return Structure(None, "invalid_direction", None, None, None)
    positions = sessions.index.get_indexer([box.start])
    start_pos = int(positions[0]) if positions.size and positions[0] >= 0 else 0
    prior = sessions.iloc[max(0, start_pos - lookback) : start_pos]
    if prior.empty:
        return Structure(None, "no_history", None, None, None)
    tol = box.height * TOUCH_TOLERANCE_FRACTION
    if direction == "bullish":
        lows = pd.Series(body_low(prior), index=prior.index)
        candidates = lows[lows > box.top + tol]
        if candidates.empty:
            return Structure(None, "open_air", None, None, None)
        level = float(candidates.min())
        session = candidates.idxmin()
        edge = box.top
        beyond = candidates[candidates > level + 0.5 * box.height]
        next_level = float(beyond.min()) if not beyond.empty else None
    else:
        highs = pd.Series(body_high(prior), index=prior.index)
        candidates = highs[highs < box.bottom - tol]
        if candidates.empty:
            return Structure(None, "open_air", None, None, None)
        level = float(candidates.max())
        session = candidates.idxmax()
        edge = box.bottom
        beyond = candidates[candidates < level - 0.5 * box.height]
        next_level = float(beyond.max()) if not beyond.empty else None
    space = abs(level - edge)
    return Structure(
        level=level,
        kind="prior_body",
        session=pd.Timestamp(session),
        distance_pct=space / edge * 100.0 if edge > 0 else None,
        space_over_height=space / box.height if box.height > 0 else None,
        next_level=next_level,
    )


def empty_space_score(space_over_height: float | None) -> int:
    """0-3 descriptive grade of the empty space in box heights. Not a gate."""
    if space_over_height is None:
        return 0
    if space_over_height < 0.5:
        return 0
    if space_over_height < 1.0:
        return 1
    if space_over_height < 2.0:
        return 2
    return 3
