from __future__ import annotations

import pandas as pd
import pytest

from scanner.potter_v3 import triggers as T
from scanner.potter_v3.boxes import Box, Structure

TOP, BOTTOM = 20.7, 19.0
CB = (TOP + BOTTOM) / 2
STRUCTURE_ABOVE = 22.4
N_PRIOR, N_BOX = 3, 12


def _box_closes():
    closes = []
    for w in range(6):  # bottom, top, bottom, top, bottom, top
        closes.extend([BOTTOM if w % 2 == 0 else TOP] * 2)
    return closes


def _frames(scenario):
    """prior collapse (26 -> 24 -> 22.4) + 12-session box + scenario rows.

    scenario rows: (open, partial_close, full_close). Highs/lows are derived.
    """
    prior = [(26.5, 26.0, 26.0), (26.0, 24.0, 24.0), (24.0, STRUCTURE_ABOVE, STRUCTURE_ABOVE)]
    box = [(19.3, c, c) for c in _box_closes()]
    rows = prior + box + list(scenario)
    idx = pd.bdate_range("2026-01-05", periods=len(rows), tz="America/New_York")
    full = pd.DataFrame(
        {
            "Open": [r[0] for r in rows],
            "High": [max(r[0], r[2]) + 0.2 for r in rows],
            "Low": [min(r[0], r[2]) - 0.2 for r in rows],
            "Close": [r[2] for r in rows],
            "Volume": 1000,
        },
        index=idx,
    )
    partial = full.copy()
    partial["Close"] = [r[1] for r in rows]
    return full, partial


def _scenario(triggers, full):
    """Triggers read on scenario sessions only (the box's own wave crossings are separate)."""
    first = full.index[N_PRIOR + N_BOX]
    return [t for t in triggers if t.session >= first]


def _kinds(triggers):
    return [t.kind for t in triggers]


def test_wave_crossings_inside_a_forming_box_are_plain_cb_breaks_not_punchbacks():
    full, partial = _frames([])
    trig = T.scan_triggers("TST", full, partial)
    assert trig, "a box that alternates between its edges crosses cost basis"
    assert all(t.kind in {"cb_break_bull", "cb_break_bear"} for t in trig)
    assert not any("punchback_bull" in t.flags or "punchback_bear" in t.flags for t in trig)


def test_breakout_trigger_plan_and_confirmation():
    full, partial = _frames([(20.6, 21.3, 21.4)])
    trig = _scenario(T.scan_triggers("TST", full, partial), full)
    assert _kinds(trig) == ["breakout"]
    t = trig[0]
    assert t.direction == "bullish"
    assert t.entry_price == pytest.approx(21.3)
    assert t.prev_close == pytest.approx(TOP)
    assert t.confirmed_24h is True
    assert t.box.top == pytest.approx(TOP) and t.box.bottom == pytest.approx(BOTTOM)
    assert t.structure.level == pytest.approx(STRUCTURE_ABOVE)
    names = [leg.name for leg in t.plan.legs]
    assert names == ["trim_50pct_empty_space", "structure"]
    assert t.plan.legs[0].level == pytest.approx(TOP + 0.5 * (STRUCTURE_ABOVE - TOP))
    assert t.plan.legs[1].level == pytest.approx(STRUCTURE_ABOVE)
    assert t.plan.stop_rule == "close_inside_box" and t.plan.stop_level == pytest.approx(TOP)
    assert t.plan.risk_pct == pytest.approx((21.3 - TOP) / 21.3 * 100)
    assert t.tradeable is True
    assert t.empty_space_score == 2  # exactly one box height of air


def test_breakout_not_confirmed_when_24h_candle_closes_back_inside():
    full, partial = _frames([(20.6, 21.3, 20.4)])
    trig = _scenario(T.scan_triggers("TST", full, partial), full)
    assert _kinds(trig) == ["breakout"]
    assert trig[0].confirmed_24h is False


def test_cost_basis_break_after_punch_down_and_floor_loss_becomes_punchback():
    scenario = [
        (20.6, 18.5, 18.5),  # breakdown: lost the floor
        (18.6, 19.4, 19.4),  # floor reclaim, still under cost basis
        (19.5, 20.2, 20.2),  # close through the 50% mark -> punch back
    ]
    full, partial = _frames(scenario)
    trig = _scenario(T.scan_triggers("TST", full, partial), full)
    assert _kinds(trig) == ["breakdown", "floor_reclaim", "punchback_bull"]
    breakdown, reclaim, punch = trig
    assert breakdown.tradeable is False and breakdown.untradeable_reason == "open_air_no_structure_target"
    assert reclaim.plan.legs[0].name == "cost_basis" and reclaim.plan.legs[0].level == pytest.approx(CB)
    assert reclaim.plan.stop_rule == "close_outside_box" and reclaim.plan.stop_level == pytest.approx(BOTTOM)
    assert "cb_break_bull" in punch.flags and "punchback_bull" in punch.flags
    assert punch.floor_loss_depth == pytest.approx((BOTTOM - 18.5) / (TOP - BOTTOM))
    assert [leg.name for leg in punch.plan.legs] == ["box_edge", "structure"]
    assert punch.plan.legs[0].level == pytest.approx(TOP)
    assert punch.plan.stop_rule == "close_through_cost_basis" and punch.plan.stop_level == pytest.approx(CB)
    assert punch.overlapping is True and reclaim.overlapping is True


def test_plain_cost_basis_break_without_floor_loss_is_cb_break():
    scenario = [
        (20.6, 19.3, 19.3),  # punch down through cost basis from above
        (19.4, 20.2, 20.2),  # back through it from below
    ]
    full, partial = _frames(scenario)
    trig = _scenario(T.scan_triggers("TST", full, partial), full)
    assert _kinds(trig) == ["cb_break_bear", "cb_break_bull"]
    assert trig[0].direction == "bearish" and trig[1].direction == "bullish"
    assert "punchback_bull" not in trig[1].flags
    assert trig[0].plan.legs[0].level == pytest.approx(BOTTOM)


def test_ceiling_reject_and_no_trigger_inside_same_half():
    scenario = [
        (20.6, 21.3, 21.3),  # breakout
        (21.2, 20.3, 20.3),  # back inside, upper half -> ceiling reject (bearish)
        (20.3, 20.4, 20.4),  # drifting inside the same half: nothing
    ]
    full, partial = _frames(scenario)
    trig = _scenario(T.scan_triggers("TST", full, partial), full)
    assert _kinds(trig) == ["breakout", "ceiling_reject"]
    assert trig[1].direction == "bearish"
    assert trig[1].plan.legs[0].level == pytest.approx(CB)


def test_low_priced_names_are_flagged_untradeable():
    full, partial = _frames([(20.6, 21.3, 21.4)])
    trig = _scenario(T.scan_triggers("TST", full, partial, min_price=50.0), full)
    assert trig and trig[0].tradeable is False and "price below" in trig[0].untradeable_reason


def test_no_box_means_no_triggers_and_empty_inputs_are_safe():
    idx = pd.bdate_range("2026-01-05", periods=15, tz="America/New_York")
    trend = pd.DataFrame({"Open": range(10, 25), "High": range(11, 26), "Low": range(9, 24), "Close": range(10, 25), "Volume": 1}, index=idx).astype(float)
    assert T.scan_triggers("TST", trend, trend) == []
    assert T.scan_triggers("TST", pd.DataFrame(), pd.DataFrame()) == []


def _box():
    return Box(start=pd.Timestamp("2026-01-05", tz="America/New_York"), end=pd.Timestamp("2026-01-20", tz="America/New_York"), length=12, top=TOP, bottom=BOTTOM, top_waves=3, bottom_waves=3)


def _structure(level):
    return Structure(level=level, kind="prior_body" if level is not None else "open_air", session=None, distance_pct=None, space_over_height=None)


def test_build_plan_shapes_for_every_kind():
    box = _box()
    beyond = _structure(STRUCTURE_ABOVE)
    air = _structure(None)
    assert [leg.name for leg in T.build_plan("breakout", 21.0, box, air).legs] == ["none_beyond_entry"]
    bear = T.build_plan("breakdown", 18.5, box, _structure(17.0))
    assert bear.legs[0].level == pytest.approx(BOTTOM + 0.5 * (17.0 - BOTTOM)) and bear.stop_level == pytest.approx(BOTTOM)
    cb = T.build_plan("cb_break_bear", 19.5, box, air)
    assert [leg.name for leg in cb.legs] == ["box_edge"] and cb.legs[0].level == pytest.approx(BOTTOM)
    assert T.build_plan("ceiling_reject", 20.3, box, beyond).stop_level == pytest.approx(TOP)
    tiny = T.build_plan("cb_break_bull", CB + 0.001, box, beyond)
    assert tiny.risk_pct == pytest.approx(T.RISK_PCT_BOUNDS[0])


def test_build_plan_rolls_weight_past_legs_the_entry_already_cleared():
    box = _box()
    # entry above the 50% trim of a 20.7 -> 22.4 void: only the structure leg remains, at full weight
    plan = T.build_plan("breakout", 21.9, box, _structure(STRUCTURE_ABOVE))
    assert [leg.name for leg in plan.legs] == ["structure"]
    assert plan.legs[0].weight == pytest.approx(1.0)
    # entry beyond every target: horizon-only plan with zero-weight marker leg
    plan = T.build_plan("breakout", 23.0, box, _structure(STRUCTURE_ABOVE))
    assert [leg.name for leg in plan.legs] == ["none_beyond_entry"] and plan.legs[0].weight == 0.0


def test_trigger_to_dict_is_json_friendly():
    full, partial = _frames([(20.6, 21.3, 21.4)])
    d = _scenario(T.scan_triggers("TST", full, partial), full)[0].to_dict()
    assert d["kind"] == "breakout" and isinstance(d["session"], str)
    assert d["box"]["cost_basis"] == pytest.approx(CB)
    assert d["plan"]["legs"][1]["name"] == "structure"
    assert d["session_pos"] == N_PRIOR + N_BOX
