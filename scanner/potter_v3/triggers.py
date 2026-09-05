"""Entry triggers as the method states them, read at the 3:50 pm close.

Every trigger is a relationship between yesterday's completed 24-hour candle,
today's still-forming candle at 16:00 ET, and the active box (spec rules in
research/potter_v3/METHOD_SPEC_FROM_SOURCES.md):

- ``breakout`` / ``breakdown``  R20: a close outside the structure.
- ``cb_break_bull`` / ``cb_break_bear``  R14/R20: a close through the 50% mark
  from the other side ("break over your cost basis you will go to resistance").
- ``punchback_bull`` / ``punchback_bear``  R22/R28: the cost-basis break that
  follows a lost-and-reclaimed floor (ceiling). This is the setup he calls
  "the entirety of everything that I do".
- ``floor_reclaim`` / ``ceiling_reject``  R23: a close back inside after losing
  the edge, good for a move to cost basis only.

The trade plan attached to each trigger follows R34-R40: targets are the box
edge and then the first structure to the left through empty space, the trim
sits at 50% of that empty space, the stop is a 24-hour close back through the
level that defined the trade, and the hold is a few sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .. import config as scanner_config
from .boxes import Box, Structure, empty_space_score, find_box, structure_beyond

PUNCHBACK_LOOKBACK_SESSIONS = 10
BOX_VOID_HEIGHTS = 1.0
BOX_MAX_AGE_SESSIONS = 40
HOLD_SESSIONS = 3
RISK_PCT_BOUNDS = (0.5, 15.0)

BULLISH_KINDS = ("breakout", "punchback_bull", "cb_break_bull", "floor_reclaim")
BEARISH_KINDS = ("breakdown", "punchback_bear", "cb_break_bear", "ceiling_reject")


@dataclass
class Leg:
    level: float
    weight: float
    name: str


@dataclass
class Plan:
    legs: list[Leg]
    stop_rule: str
    stop_level: float
    risk_pct: float
    horizon_sessions: int = HOLD_SESSIONS

    def to_dict(self) -> dict:
        return {
            "legs": [{"level": leg.level, "weight": leg.weight, "name": leg.name} for leg in self.legs],
            "stop_rule": self.stop_rule,
            "stop_level": self.stop_level,
            "risk_pct": self.risk_pct,
            "horizon_sessions": self.horizon_sessions,
        }


@dataclass
class Trigger:
    ticker: str
    session: pd.Timestamp
    kind: str
    direction: str
    flags: list[str]
    entry_price: float
    prev_close: float
    full_close: float
    confirmed_24h: bool
    box: Box
    structure: Structure
    empty_space_score: int
    plan: Plan
    tradeable: bool
    untradeable_reason: str | None
    floor_loss_depth: float | None = None
    overlapping: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "session": pd.Timestamp(self.session).isoformat(),
            "kind": self.kind,
            "direction": self.direction,
            "flags": list(self.flags),
            "entry_price": self.entry_price,
            "prev_close": self.prev_close,
            "full_close": self.full_close,
            "confirmed_24h": self.confirmed_24h,
            "box": self.box.to_dict(),
            "structure": self.structure.to_dict(),
            "empty_space_score": self.empty_space_score,
            "plan": self.plan.to_dict(),
            "tradeable": self.tradeable,
            "untradeable_reason": self.untradeable_reason,
            "floor_loss_depth": self.floor_loss_depth,
            "overlapping": self.overlapping,
            **self.extra,
        }


def _clamp_risk_pct(entry: float, stop_level: float) -> float:
    raw = abs(entry - stop_level) / entry * 100.0 if entry > 0 else RISK_PCT_BOUNDS[0]
    return float(min(max(raw, RISK_PCT_BOUNDS[0]), RISK_PCT_BOUNDS[1]))


def build_plan(kind: str, entry: float, box: Box, structure: Structure) -> Plan:
    bullish = kind in BULLISH_KINDS
    beyond = structure.level
    if kind in {"breakout", "breakdown"}:
        edge = box.top if bullish else box.bottom
        if beyond is None:
            legs = [Leg(level=edge, weight=1.0, name="edge_only")]
        else:
            trim = edge + 0.5 * (beyond - edge)
            legs = [Leg(level=trim, weight=0.5, name="trim_50pct_empty_space"), Leg(level=beyond, weight=0.5, name="structure")]
        stop_rule = "close_inside_box"
        stop_level = edge
    elif kind in {"punchback_bull", "cb_break_bull", "punchback_bear", "cb_break_bear"}:
        first = box.top if bullish else box.bottom
        if beyond is None:
            legs = [Leg(level=first, weight=1.0, name="box_edge")]
        else:
            legs = [Leg(level=first, weight=0.5, name="box_edge"), Leg(level=beyond, weight=0.5, name="structure")]
        stop_rule = "close_through_cost_basis"
        stop_level = box.cost_basis
    else:
        legs = [Leg(level=box.cost_basis, weight=1.0, name="cost_basis")]
        stop_rule = "close_outside_box"
        stop_level = box.bottom if bullish else box.top
    legs = _drop_passed_legs(legs, entry, bullish)
    return Plan(legs=legs, stop_rule=stop_rule, stop_level=stop_level, risk_pct=_clamp_risk_pct(entry, stop_level))


def _drop_passed_legs(legs: list[Leg], entry: float, bullish: bool) -> list[Leg]:
    """Legs the entry has already passed cannot be targets; their weight rolls forward.

    A big trigger candle can close beyond the 50% trim or even the box edge.
    Keeping such a leg would book a fill below the entry as if it were profit.
    If nothing lies beyond the entry the plan is horizon-only.
    """
    ahead = [leg for leg in legs if (leg.level > entry if bullish else leg.level < entry)]
    if not ahead:
        return [Leg(level=entry, weight=0.0, name="none_beyond_entry")]
    total = sum(leg.weight for leg in legs)
    ahead_total = sum(leg.weight for leg in ahead)
    if ahead_total <= 0:
        return ahead
    scale = total / ahead_total
    return [Leg(level=leg.level, weight=leg.weight * scale, name=leg.name) for leg in ahead]


def _classify(prev: float, close: float, box: Box, floor_lost: bool, ceiling_lost: bool) -> tuple[str | None, list[str]]:
    """Primary trigger kind for today's 16:00 close against yesterday's 24h close."""
    top, bottom, cb = box.top, box.bottom, box.cost_basis
    flags: list[str] = []
    kind: str | None = None
    if close > top:
        if prev <= top:
            kind = "breakout"
            flags.append("breakout")
            if prev < cb:
                flags.append("cb_crossed")
    elif close < bottom:
        if prev >= bottom:
            kind = "breakdown"
            flags.append("breakdown")
            if prev > cb:
                flags.append("cb_crossed")
    elif close > cb:
        if prev < cb:
            flags.append("cb_break_bull")
            if prev < bottom:
                flags.append("floor_reclaim")
            kind = "punchback_bull" if floor_lost else "cb_break_bull"
            if floor_lost:
                flags.append("punchback_bull")
        elif prev > top:
            kind = "ceiling_reject"
            flags.append("ceiling_reject")
    elif close < cb:
        if prev > cb:
            flags.append("cb_break_bear")
            if prev > top:
                flags.append("ceiling_reject")
            kind = "punchback_bear" if ceiling_lost else "cb_break_bear"
            if ceiling_lost:
                flags.append("punchback_bear")
        elif prev < bottom:
            kind = "floor_reclaim"
            flags.append("floor_reclaim")
    return kind, flags


def _same_zone(kind: str, close: float, box: Box) -> bool:
    if kind == "breakout":
        return close > box.top
    if kind == "breakdown":
        return close < box.bottom
    if kind in {"punchback_bull", "cb_break_bull"}:
        return box.cost_basis < close <= box.top
    if kind in {"punchback_bear", "cb_break_bear"}:
        return box.bottom <= close < box.cost_basis
    if kind == "floor_reclaim":
        return box.bottom <= close < box.cost_basis
    if kind == "ceiling_reject":
        return box.cost_basis < close <= box.top
    return False


def _box_is_void(box: Box, last_close: float, age_sessions: int) -> bool:
    if age_sessions > BOX_MAX_AGE_SESSIONS:
        return True
    if last_close > box.top + BOX_VOID_HEIGHTS * box.height:
        return True
    if last_close < box.bottom - BOX_VOID_HEIGHTS * box.height:
        return True
    return False


def scan_triggers(
    ticker: str,
    full: pd.DataFrame,
    partial: pd.DataFrame,
    *,
    hold_sessions: int = HOLD_SESSIONS,
    min_price: float | None = None,
) -> list[Trigger]:
    """Walk the sessions in order and emit every trigger the method would have read.

    ``full`` holds complete 04:00-20:00 candles, ``partial`` the same dates cut
    at 16:00. Boxes are built from completed candles strictly before the
    session being read, so nothing from the reading day leaks into its levels.
    """
    if full is None or full.empty or partial is None or partial.empty:
        return []
    min_price = float(scanner_config.MIN_STOCK_PRICE if min_price is None else min_price)
    full = full.sort_index()
    partial = partial.sort_index()
    partial_close = partial["Close"]
    closes = full["Close"].to_numpy(dtype=float)
    triggers: list[Trigger] = []
    active: Box | None = None
    active_since = 0
    structure_cache: dict[tuple, dict[str, Structure]] = {}
    # A trigger inside the hold window of an earlier SAME-direction trigger is
    # the same open position (a breakout two days after the cost-basis break
    # that started the move); it is recorded but excluded from the cells.
    last_pos_by_direction: dict[str, int] = {}

    for pos in range(1, len(full)):
        date = full.index[pos]
        candidate = find_box(full, end=pos)
        if candidate is not None:
            if active is None or candidate.top != active.top or candidate.bottom != active.bottom:
                active_since = pos
            active = candidate
        elif active is not None and _box_is_void(active, closes[pos - 1], pos - active_since):
            active = None
        if active is None or date not in partial_close.index:
            continue
        close = float(partial_close.loc[date])
        prev = float(closes[pos - 1])
        # A lost floor or ceiling is a close outside THIS box after it existed;
        # the move that formed the box (the collapse before it) is not a loss.
        box_start_pos = int(full.index.get_indexer([active.start])[0])
        window = closes[max(box_start_pos, pos - PUNCHBACK_LOOKBACK_SESSIONS) : pos]
        floor_lost = bool(window.size and (window < active.bottom).any())
        ceiling_lost = bool(window.size and (window > active.top).any())
        kind, flags = _classify(prev, close, active, floor_lost, ceiling_lost)
        if kind is None:
            continue
        direction = "bullish" if kind in BULLISH_KINDS else "bearish"
        key = (active.start, active.end, active.top, active.bottom)
        per_box = structure_cache.setdefault(key, {})
        if direction not in per_box:
            per_box[direction] = structure_beyond(full, active, direction)
        structure = per_box[direction]
        plan = build_plan(kind, close, active, structure)
        tradeable, reason = True, None
        if close < min_price:
            tradeable, reason = False, f"price below ${min_price:.2f}"
        elif kind in {"breakout", "breakdown"} and structure.level is None:
            tradeable, reason = False, "open_air_no_structure_target"
        depth = None
        if direction == "bullish" and floor_lost and window.size:
            depth = float((active.bottom - window.min()) / active.height)
        elif direction == "bearish" and ceiling_lost and window.size:
            depth = float((window.max() - active.top) / active.height)
        last_same = last_pos_by_direction.get(direction)
        overlapping = last_same is not None and (pos - last_same) <= hold_sessions
        full_close = float(closes[pos])
        triggers.append(
            Trigger(
                ticker=ticker,
                session=date,
                kind=kind,
                direction=direction,
                flags=flags,
                entry_price=close,
                prev_close=prev,
                full_close=full_close,
                confirmed_24h=_same_zone(kind, full_close, active),
                box=active,
                structure=structure,
                empty_space_score=empty_space_score(structure.space_over_height),
                plan=plan,
                tradeable=tradeable,
                untradeable_reason=reason,
                floor_loss_depth=depth,
                overlapping=overlapping,
                extra={"session_pos": pos, "box_age_sessions": pos - active_since},
            )
        )
        last_pos_by_direction[direction] = pos
    return triggers
