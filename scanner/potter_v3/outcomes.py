"""Simulate a trigger's trade plan on the realised path, stock leg and contract leg.

Fidelity choices, each tied to a spec rule:
- Entry is the 16:00 close of the trigger session (R21).
- The stop is a 24-hour CLOSE back through the level that defined the trade
  (R39), checked each morning on the prior candle and executed at the regular
  session open. He does not react after hours (R41), so the trigger day's own
  20:00 close is first judged the next morning.
- Fills happen only during regular hours (options do not trade after 16:00),
  at the leg level when the session's regular-hours range reaches it.
- The hold is a few sessions; the remainder is sold at the 10:30 print on the
  last session (R40 "in the morning around 10:30").
- The stock leg is charged the project's round-trip cost floor; the contract
  leg carries its own spread haircut inside the pricing model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .. import config as scanner_config
from . import options_model as OM
from .sessions import RTH_CLOSE, RTH_OPEN, build_eth_sessions, rth_bars
from .triggers import Trigger

MORNING_EXIT = (10, 30)
CONTRACT_DTE_BULL = 10
CONTRACT_DTE_BEAR = 14
CONTRACT_SPREAD_BPS_PER_SIDE = 1000.0
CONTRACT_PREMIUM_FLOOR = 0.05
VOL_WINDOW = 20
VOL_MULTIPLE = 1.0


@dataclass
class Outcome:
    resolved: bool
    exit_reason: str
    exit_session: str | None
    sessions_held: int
    stock_return_pct: float
    stock_return_net_pct: float
    r_multiple: float
    legs_filled: list[str]
    mae_pct: float
    mfe_pct: float
    contract: dict | None
    contract_return_pct: float | None
    contract_return_net_pct: float | None
    stop_checked_on_entry_day: bool = True
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "resolved": self.resolved,
            "exit_reason": self.exit_reason,
            "exit_session": self.exit_session,
            "sessions_held": self.sessions_held,
            "stock_return_pct": self.stock_return_pct,
            "stock_return_net_pct": self.stock_return_net_pct,
            "r_multiple": self.r_multiple,
            "legs_filled": list(self.legs_filled),
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
            "contract": self.contract,
            "contract_return_pct": self.contract_return_pct,
            "contract_return_net_pct": self.contract_return_net_pct,
            **self.details,
        }


def build_day_table(intraday: pd.DataFrame) -> pd.DataFrame:
    """Per-date regular-session facts the simulator needs, from 30-minute bars.

    Columns: rth_open, rth_high, rth_low, rth_close, early_high, early_low
    (09:30 through the 10:30 print), price_1030 (close of the 10:00 bar).
    """
    cols = ["rth_open", "rth_high", "rth_low", "rth_close", "early_high", "early_low", "price_1030"]
    if intraday is None or intraday.empty:
        return pd.DataFrame(columns=cols)
    rth = rth_bars(intraday)
    if rth.empty:
        return pd.DataFrame(columns=cols)
    sessions = build_eth_sessions(rth)
    minute = rth.index.hour * 60 + rth.index.minute
    early_limit = MORNING_EXIT[0] * 60 + MORNING_EXIT[1]
    early = rth[minute < early_limit]
    early_sessions = build_eth_sessions(early) if not early.empty else pd.DataFrame()
    table = pd.DataFrame(index=sessions.index)
    table["rth_open"] = sessions["Open"]
    table["rth_high"] = sessions["High"]
    table["rth_low"] = sessions["Low"]
    table["rth_close"] = sessions["Close"]
    if not early_sessions.empty:
        table["early_high"] = early_sessions["High"].reindex(table.index)
        table["early_low"] = early_sessions["Low"].reindex(table.index)
        table["price_1030"] = early_sessions["Close"].reindex(table.index)
    else:
        table["early_high"] = float("nan")
        table["early_low"] = float("nan")
        table["price_1030"] = float("nan")
    table["early_high"] = table["early_high"].fillna(table["rth_open"])
    table["early_low"] = table["early_low"].fillna(table["rth_open"])
    table["price_1030"] = table["price_1030"].fillna(table["rth_open"])
    return table[cols]


def _stopped(direction: str, close: float, stop_level: float) -> bool:
    return close < stop_level if direction == "bullish" else close > stop_level


def _ret(direction: str, entry: float, price: float) -> float:
    sign = 1.0 if direction == "bullish" else -1.0
    return sign * (price - entry) / entry * 100.0


def _reached(direction: str, high: float, low: float, level: float) -> bool:
    return high >= level if direction == "bullish" else low <= level


def _contract_for(trigger: Trigger, full: pd.DataFrame, pos: int, *, vol_window: int, vol_multiple: float, spread_bps: float) -> tuple[OM.ContractSpec | None, dict]:
    closes = full["Close"].iloc[: pos + 1]
    sigma = OM.realized_volatility(closes, window=vol_window)
    notes: dict = {"sigma_source": f"realized_{vol_window}x{vol_multiple:g}"}
    if sigma is None:
        return None, {**notes, "contract_skip": "insufficient_history_for_volatility"}
    sigma *= vol_multiple
    levels = [leg.level for leg in trigger.plan.legs]
    target = max(levels) if trigger.direction == "bullish" else min(levels)
    dte = CONTRACT_DTE_BULL if trigger.direction == "bullish" else CONTRACT_DTE_BEAR
    spec = OM.select_contract_at_strike(
        trigger.direction,
        trigger.entry_price,
        sigma,
        strike=OM.snap_strike(target),
        dte_calendar_days=dte,
        spread_bps_per_side=spread_bps,
        premium_floor=CONTRACT_PREMIUM_FLOOR,
    )
    if spec is None:
        return None, {**notes, "contract_skip": "no_priceable_contract"}
    return spec, notes


def simulate(
    trigger: Trigger,
    full: pd.DataFrame,
    day_table: pd.DataFrame,
    *,
    cost_bps_per_side: float | None = None,
    vol_window: int = VOL_WINDOW,
    vol_multiple: float = VOL_MULTIPLE,
    contract_spread_bps: float = CONTRACT_SPREAD_BPS_PER_SIDE,
) -> Outcome:
    cost_bps = float(scanner_config.EDGE_COST_BPS_PER_SIDE if cost_bps_per_side is None else cost_bps_per_side)
    direction = trigger.direction
    entry = float(trigger.entry_price)
    plan = trigger.plan
    horizon = int(plan.horizon_sessions)
    positions = full.index.get_indexer([trigger.session])
    pos = int(positions[0]) if positions.size and positions[0] >= 0 else -1
    if pos < 0 or pos + horizon >= len(full):
        return Outcome(False, "insufficient_forward_sessions", None, 0, 0.0, 0.0, 0.0, [], 0.0, 0.0, None, None, None)

    spec, contract_notes = _contract_for(trigger, full, pos, vol_window=vol_window, vol_multiple=vol_multiple, spread_bps=contract_spread_bps)
    entry_day = pd.Timestamp(trigger.session).normalize()

    legs = sorted(plan.legs, key=lambda leg: abs(leg.level - entry))
    unfilled = list(legs)
    remaining = 1.0
    realized = 0.0
    contract_realized = 0.0 if spec is not None else None
    filled: list[str] = []
    exit_reason = "horizon"
    exit_session: pd.Timestamp | None = None
    highs: list[float] = []
    lows: list[float] = []

    def book(price: float, weight: float, when: pd.Timestamp) -> None:
        nonlocal realized, contract_realized
        realized += weight * _ret(direction, entry, price)
        if spec is not None and contract_realized is not None:
            elapsed = (pd.Timestamp(when).normalize() - entry_day).days
            contract_realized += weight * OM.contract_return_pct(spec, price, elapsed)

    for k in range(1, horizon + 1):
        date = full.index[pos + k]
        prior_close = float(full["Close"].iloc[pos + k - 1])
        day = day_table.loc[date] if date in day_table.index else None
        if _stopped(direction, prior_close, plan.stop_level):
            price = float(day["rth_open"]) if day is not None else float(full["Open"].iloc[pos + k])
            book(price, remaining, date)
            remaining = 0.0
            exit_reason = "stop_close"
            exit_session = date
            if day is not None:
                highs.append(float(day["rth_open"]))
                lows.append(float(day["rth_open"]))
            break
        if day is None:
            if k == horizon:
                price = float(full["Close"].iloc[pos + k])
                book(price, remaining, date)
                remaining = 0.0
                exit_session = date
            continue
        last_day = k == horizon
        high = float(day["early_high"] if last_day else day["rth_high"])
        low = float(day["early_low"] if last_day else day["rth_low"])
        highs.append(high)
        lows.append(low)
        for leg in list(unfilled):
            if _reached(direction, high, low, leg.level):
                weight = min(leg.weight, remaining)
                book(leg.level, weight, date)
                remaining -= weight
                filled.append(leg.name)
                unfilled.remove(leg)
        if remaining <= 1e-9:
            remaining = 0.0
            exit_reason = "target"
            exit_session = date
            break
        if last_day:
            book(float(day["price_1030"]), remaining, date)
            remaining = 0.0
            exit_reason = "horizon"
            exit_session = date

    net = realized - 2.0 * cost_bps / 100.0
    risk = max(float(plan.risk_pct), 1e-9)
    r_multiple = max(min(net / risk, 10.0), -10.0)
    sign = 1.0 if direction == "bullish" else -1.0
    mfe = max([sign * (h - entry) / entry * 100.0 for h in highs] + [sign * (l - entry) / entry * 100.0 for l in lows] + [0.0])
    mae = min([sign * (l - entry) / entry * 100.0 for l in lows] + [sign * (h - entry) / entry * 100.0 for h in highs] + [0.0])
    contract_dict = None
    contract_net = None
    if spec is not None:
        contract_dict = {
            "option_type": spec.option_type,
            "strike": spec.strike,
            "dte_calendar_days": spec.dte_calendar_days,
            "sigma": spec.sigma,
            "entry_premium": spec.entry_premium,
            "entry_delta": spec.entry_delta,
            "spread_bps_per_side": spec.spread_bps_per_side,
            **spec.notes,
        }
        contract_net = contract_realized
    sessions_held = int((full.index.get_indexer([exit_session])[0] - pos)) if exit_session is not None else horizon
    return Outcome(
        resolved=True,
        exit_reason=exit_reason,
        exit_session=pd.Timestamp(exit_session).isoformat() if exit_session is not None else None,
        sessions_held=sessions_held,
        stock_return_pct=float(realized),
        stock_return_net_pct=float(net),
        r_multiple=float(r_multiple),
        legs_filled=filled,
        mae_pct=float(mae),
        mfe_pct=float(mfe),
        contract=contract_dict,
        contract_return_pct=contract_realized,
        contract_return_net_pct=contract_net,
        details={"cost_bps_per_side": cost_bps, **contract_notes},
    )
