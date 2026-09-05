from __future__ import annotations

import pandas as pd
import pytest

from scanner.potter_v3 import outcomes as O
from scanner.potter_v3 import triggers as T
from scanner.potter_v3.boxes import Box, Structure

TOP, BOTTOM = 20.7, 19.0
CB = (TOP + BOTTOM) / 2
TZ = "America/New_York"


def _full(closes, start="2026-02-02"):
    idx = pd.bdate_range(start, periods=len(closes), tz=TZ)
    opens = [closes[0]] + list(closes[:-1])
    return pd.DataFrame(
        {"Open": opens, "High": [max(o, c) + 0.1 for o, c in zip(opens, closes)], "Low": [min(o, c) - 0.1 for o, c in zip(opens, closes)], "Close": closes, "Volume": 1000},
        index=idx,
    )


def _day_table(full, rows):
    """rows: {date_pos: (open, high, low, close, early_high, early_low, price_1030)}"""
    table = pd.DataFrame(index=full.index, columns=["rth_open", "rth_high", "rth_low", "rth_close", "early_high", "early_low", "price_1030"], dtype=float)
    for pos, vals in rows.items():
        table.iloc[pos] = vals
    return table.dropna(how="all")


def _trigger(full, pos, kind="breakout", entry=21.3, structure=22.4, direction=None):
    box = Box(start=full.index[max(0, pos - 12)], end=full.index[pos - 1], length=12, top=TOP, bottom=BOTTOM, top_waves=3, bottom_waves=3)
    struct = Structure(level=structure, kind="prior_body" if structure is not None else "open_air", session=None, distance_pct=None, space_over_height=None)
    plan = T.build_plan(kind, entry, box, struct)
    direction = direction or ("bullish" if kind in T.BULLISH_KINDS else "bearish")
    return T.Trigger(
        ticker="TST", session=full.index[pos], kind=kind, direction=direction, flags=[kind], entry_price=entry, prev_close=TOP, full_close=entry,
        confirmed_24h=True, box=box, structure=struct, empty_space_score=2, plan=plan, tradeable=True, untradeable_reason=None,
    )


def test_both_legs_fill_on_the_first_regular_session():
    closes = [20.0] * 25 + [21.3, 21.6, 21.8, 21.9]
    full = _full(closes)
    pos = 25
    table = _day_table(full, {26: (21.4, 22.6, 21.2, 22.0, 21.5, 21.3, 21.45)})
    out = O.simulate(_trigger(full, pos), full, table, cost_bps_per_side=25)
    assert out.resolved and out.exit_reason == "target"
    assert out.legs_filled == ["trim_50pct_empty_space", "structure"]
    trim = TOP + 0.5 * (22.4 - TOP)
    expected = 0.5 * (trim - 21.3) / 21.3 * 100 + 0.5 * (22.4 - 21.3) / 21.3 * 100
    assert out.stock_return_pct == pytest.approx(expected)
    assert out.stock_return_net_pct == pytest.approx(expected - 0.5)
    assert out.r_multiple == pytest.approx((expected - 0.5) / ((21.3 - TOP) / 21.3 * 100))
    assert out.sessions_held == 1
    assert out.mfe_pct == pytest.approx((22.6 - 21.3) / 21.3 * 100)
    assert out.contract is not None and out.contract["option_type"] == "call"
    assert out.contract["strike"] == pytest.approx(22.5)  # target-based strike snapped to $0.50 grid
    assert out.contract_return_net_pct is not None and out.contract_return_net_pct > 0


def test_close_back_inside_the_box_stops_next_morning_at_the_open():
    closes = [20.0] * 25 + [20.4, 20.1, 20.0, 19.9]  # 24h candle on trigger day closed back inside
    full = _full(closes)
    table = _day_table(full, {26: (20.5, 20.9, 20.3, 20.6, 20.6, 20.4, 20.55)})
    out = O.simulate(_trigger(full, 25), full, table, cost_bps_per_side=0)
    assert out.exit_reason == "stop_close" and out.sessions_held == 1
    assert out.legs_filled == []
    assert out.stock_return_pct == pytest.approx((20.5 - 21.3) / 21.3 * 100)
    assert out.r_multiple < 0
    assert out.contract_return_net_pct < 0


def test_horizon_exit_uses_the_1030_print_and_only_early_range_on_last_day():
    closes = [20.0] * 25 + [21.3, 21.35, 21.4, 21.45]
    full = _full(closes)
    table = _day_table(
        full,
        {
            26: (21.3, 21.5, 21.2, 21.35, 21.4, 21.25, 21.3),
            27: (21.35, 21.5, 21.3, 21.4, 21.4, 21.3, 21.35),
            28: (21.4, 22.9, 21.3, 22.8, 21.5, 21.35, 21.45),  # runs to 22.9 after 10:30: must not count
        },
    )
    out = O.simulate(_trigger(full, 25), full, table, cost_bps_per_side=0)
    assert out.exit_reason == "horizon" and out.sessions_held == 3
    assert out.legs_filled == []
    assert out.stock_return_pct == pytest.approx((21.45 - 21.3) / 21.3 * 100)
    assert out.mfe_pct == pytest.approx((21.5 - 21.3) / 21.3 * 100)


def test_bearish_plan_mirrors_fills_and_stops():
    closes = [20.0] * 25 + [18.4, 18.3, 18.2, 18.1]
    full = _full(closes)
    table = _day_table(full, {26: (18.3, 18.5, 16.9, 17.2, 18.4, 17.9, 18.0)})
    trig = _trigger(full, 25, kind="breakdown", entry=18.4, structure=17.0)
    out = O.simulate(trig, full, table, cost_bps_per_side=0)
    assert out.exit_reason == "target"
    trim = BOTTOM + 0.5 * (17.0 - BOTTOM)
    expected = 0.5 * (18.4 - trim) / 18.4 * 100 + 0.5 * (18.4 - 17.0) / 18.4 * 100
    assert out.stock_return_pct == pytest.approx(expected)
    assert out.contract["option_type"] == "put" and out.contract["dte_calendar_days"] == O.CONTRACT_DTE_BEAR
    stopped = _full([20.0] * 25 + [19.4, 19.5, 19.6, 19.7])
    out2 = O.simulate(_trigger(stopped, 25, kind="breakdown", entry=18.4, structure=17.0), stopped, _day_table(stopped, {26: (19.3, 19.6, 19.1, 19.5, 19.4, 19.2, 19.3)}), cost_bps_per_side=0)
    assert out2.exit_reason == "stop_close" and out2.stock_return_pct == pytest.approx((18.4 - 19.3) / 18.4 * 100)


def test_unresolved_when_not_enough_forward_sessions_and_no_contract_without_history():
    closes = [20.0] * 5 + [21.3, 21.5]
    full = _full(closes)
    out = O.simulate(_trigger(full, 5), full, _day_table(full, {}))
    assert out.resolved is False and out.exit_reason == "insufficient_forward_sessions"
    short = _full([20.0] * 5 + [21.3, 21.5, 21.6, 21.7])
    table = _day_table(short, {6: (21.4, 21.5, 21.3, 21.45, 21.45, 21.35, 21.4), 7: (21.5, 21.6, 21.4, 21.55, 21.55, 21.45, 21.5), 8: (21.6, 21.7, 21.5, 21.65, 21.65, 21.55, 21.6)})
    out = O.simulate(_trigger(short, 5), short, table, cost_bps_per_side=0)
    assert out.resolved and out.contract is None and out.contract_return_net_pct is None
    assert out.details["contract_skip"] == "insufficient_history_for_volatility"


def test_missing_regular_session_falls_back_to_24h_candle_on_last_day():
    closes = [20.0] * 25 + [21.3, 21.4, 21.5, 21.6]
    full = _full(closes)
    out = O.simulate(_trigger(full, 25), full, _day_table(full, {}), cost_bps_per_side=0)
    assert out.resolved and out.exit_reason == "horizon"
    assert out.stock_return_pct == pytest.approx((21.6 - 21.3) / 21.3 * 100)


def test_build_day_table_from_intraday_bars():
    rows = []
    for d in range(2):
        date = pd.Timestamp("2026-06-01", tz=TZ) + pd.Timedelta(days=d)
        minute = 4 * 60
        price = 100.0 + d
        while minute < 20 * 60:
            ts = date + pd.Timedelta(minutes=minute)
            hi = price + (5.0 if minute == 14 * 60 else 0.2)  # spike at 14:00
            rows.append({"ts": ts, "Open": price, "High": hi, "Low": price - 0.2, "Close": price + 0.05, "Volume": 10})
            price += 0.05
            minute += 30
    intraday = pd.DataFrame(rows).set_index("ts")
    table = O.build_day_table(intraday)
    assert len(table) == 2
    first = table.iloc[0]
    rth = intraday[(intraday.index.date == intraday.index[0].date()) & (intraday.index.hour >= 9) & (intraday.index.hour < 16)]
    rth = rth[~((rth.index.hour == 9) & (rth.index.minute < 30))]
    assert first["rth_open"] == rth["Open"].iloc[0]
    assert first["rth_high"] == rth["High"].max()
    assert first["rth_close"] == rth["Close"].iloc[-1]
    early = rth[(rth.index.hour * 60 + rth.index.minute) < 10 * 60 + 30]
    assert first["early_high"] == early["High"].max() and first["early_high"] < first["rth_high"]
    assert first["price_1030"] == early["Close"].iloc[-1]
    assert O.build_day_table(pd.DataFrame()).empty
