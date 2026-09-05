from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.potter_v3 import boxes as B


def _sessions(closes, opens=None, highs=None, lows=None, start="2026-01-05"):
    closes = list(closes)
    opens = list(opens) if opens is not None else [closes[0]] + closes[:-1]
    highs = list(highs) if highs is not None else [max(o, c) + 0.3 for o, c in zip(opens, closes)]
    lows = list(lows) if lows is not None else [min(o, c) - 0.3 for o, c in zip(opens, closes)]
    idx = pd.bdate_range(start, periods=len(closes), tz="America/New_York")
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": 1000}, index=idx)


def _range_closes(n_waves: int, top: float, bottom: float, per_wave: int = 2):
    """Closes bouncing between the edges: bottom-wave, top-wave, bottom-wave..."""
    closes = []
    for w in range(n_waves * 2):
        level = bottom if w % 2 == 0 else top
        closes.extend([level] * per_wave)
    return closes


def test_count_waves_collapses_consecutive_touches():
    assert B.count_waves(np.array([True, True, False, True, False, False, True])) == 3
    assert B.count_waves(np.array([False, False])) == 0
    assert B.count_waves(np.array([])) == 0
    assert B.count_waves(np.array([True, True, True])) == 1


def test_waves_must_interleave_to_be_a_range():
    top = np.array([False, False, False, True, True, False])
    bottom = np.array([True, True, False, False, False, False])
    assert B.waves_interleave(top, bottom) is False  # rising channel: bottom then top only
    top2 = np.array([False, True, False, True, False])
    bottom2 = np.array([True, False, True, False, True])
    assert B.waves_interleave(top2, bottom2) is True


def test_find_box_on_clean_range_uses_body_extremes_and_counts_waves():
    closes = _range_closes(3, top=20.7, bottom=19.0)  # 12 sessions, 3 waves each edge
    opens = [19.3] * len(closes)
    highs = [c + 0.8 for c in closes]  # wicks pierce well beyond the bodies
    lows = [c - 0.8 for c in closes]
    sessions = _sessions(closes, opens=opens, highs=highs, lows=lows)
    box = B.find_box(sessions, end=len(sessions))
    assert box is not None
    assert box.top == pytest.approx(20.7)
    assert box.bottom == pytest.approx(19.0)
    assert box.cost_basis == pytest.approx(19.85)
    assert box.top_waves == 3 and box.bottom_waves == 3
    assert box.length == len(sessions)
    assert box.start == sessions.index[0] and box.end == sessions.index[-1]


def test_find_box_rejects_trend_and_single_touch_ranges():
    trend = _sessions([10 + 0.3 * i for i in range(12)])
    assert B.find_box(trend, end=len(trend)) is None
    one_wave = _sessions([19.0, 19.0, 19.0, 19.0, 20.7, 20.7, 19.0, 19.0, 19.0, 19.0])
    assert B.find_box(one_wave, end=len(one_wave)) is None  # top touched once


def test_find_box_rejects_too_small_boxes_and_too_short_windows():
    tiny = _sessions(_range_closes(3, top=100.3, bottom=100.0))
    assert B.find_box(tiny, end=len(tiny)) is None
    short = _sessions(_range_closes(1, top=20.7, bottom=19.0, per_wave=1))
    assert B.find_box(short, end=len(short)) is None


def test_find_box_excludes_the_session_at_end_and_prefers_longest_window():
    closes = _range_closes(3, top=20.7, bottom=19.0) + [22.5]  # breakout session last
    sessions = _sessions(closes, opens=[19.3] * len(closes))
    box = B.find_box(sessions, end=len(sessions) - 1)
    assert box is not None and box.top == pytest.approx(20.7)
    with_breakout = B.find_box(sessions, end=len(sessions))
    # the breakout session becomes the top with one wave, so the longest
    # qualifying window must exclude it or fail entirely
    assert with_breakout is None or with_breakout.top == pytest.approx(20.7)
    assert box.nested_count >= 1


def test_structure_beyond_finds_first_prior_body_and_open_air():
    # collapse from 26 to a 19-20.7 box: prior bodies at 26/24 and 24/21.4
    prior_closes = [26.0, 24.0, 21.4]
    prior_opens = [26.5, 26.0, 24.0]
    box_closes = _range_closes(3, top=20.7, bottom=19.0)
    closes = prior_closes + box_closes
    opens = prior_opens + [19.3] * len(box_closes)
    sessions = _sessions(closes, opens=opens)
    box = B.find_box(sessions, end=len(sessions))
    assert box is not None and box.top == pytest.approx(20.7)
    up = B.structure_beyond(sessions, box, "bullish")
    assert up.kind == "prior_body"
    assert up.level == pytest.approx(21.4)  # first structure to the left above the top
    assert up.space_over_height == pytest.approx((21.4 - 20.7) / 1.7)
    assert up.next_level == pytest.approx(24.0)
    down = B.structure_beyond(sessions, box, "bearish")
    assert down.kind == "open_air" and down.level is None
    assert B.structure_beyond(sessions, box, "sideways").kind == "invalid_direction"


def test_empty_space_score_grades_by_box_heights():
    assert B.empty_space_score(None) == 0
    assert B.empty_space_score(0.2) == 0
    assert B.empty_space_score(0.7) == 1
    assert B.empty_space_score(1.5) == 2
    assert B.empty_space_score(3.0) == 3


def test_box_zone_and_to_dict():
    box = B.Box(start=pd.Timestamp("2026-01-05", tz="America/New_York"), end=pd.Timestamp("2026-01-20", tz="America/New_York"), length=12, top=20.7, bottom=19.0, top_waves=3, bottom_waves=3)
    assert box.zone(21.0) == "above_top"
    assert box.zone(18.0) == "below_bottom"
    assert box.zone(20.0) == "upper_half"
    assert box.zone(19.2) == "lower_half"
    d = box.to_dict()
    assert d["cost_basis"] == pytest.approx(19.85)
    assert d["height_pct"] == pytest.approx(1.7 / 19.85 * 100)
    assert isinstance(d["start"], str)
