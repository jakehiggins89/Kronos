from __future__ import annotations

import math

import pandas as pd
import pytest

from scanner.potter_v3 import options_model as M


def test_black_scholes_matches_textbook_value():
    # Hull: S=42, K=40, r=10%, sigma=20%, T=0.5 -> call 4.76, put 0.81
    call = M.black_scholes_price(42, 40, 0.5, 0.20, "call", rate=0.10)
    put = M.black_scholes_price(42, 40, 0.5, 0.20, "put", rate=0.10)
    assert call == pytest.approx(4.76, abs=0.01)
    assert put == pytest.approx(0.81, abs=0.01)


def test_put_call_parity_holds():
    s, k, t, sigma, r = 50.0, 55.0, 0.25, 0.4, 0.04
    call = M.black_scholes_price(s, k, t, sigma, "call", rate=r)
    put = M.black_scholes_price(s, k, t, sigma, "put", rate=r)
    assert call - put == pytest.approx(s - k * math.exp(-r * t), abs=1e-9)


def test_expiry_and_zero_vol_return_intrinsic():
    assert M.black_scholes_price(30, 25, 0.0, 0.5, "call") == 5.0
    assert M.black_scholes_price(30, 25, 0.0, 0.5, "put") == 0.0
    assert M.black_scholes_price(20, 25, 0.3, 0.0, "put") == 5.0


def test_delta_bounds_and_direction():
    assert 0.4 < M.black_scholes_delta(100, 100, 0.12, 0.5, "call") < 0.6
    assert -0.6 < M.black_scholes_delta(100, 100, 0.12, 0.5, "put") < -0.4
    assert M.black_scholes_delta(100, 100, 0.0, 0.5, "call") == 0.0
    assert M.black_scholes_delta(120, 100, 0.0, 0.5, "call") == 1.0


def test_strike_snapping_uses_listed_increments():
    assert M.snap_strike(19.80) == 20.0
    assert M.snap_strike(19.80, offset_steps=1) == 20.5
    assert M.snap_strike(19.80, offset_steps=-1) == 19.5
    assert M.snap_strike(101.3) == 101.0
    assert M.snap_strike(412.0) == 410.0


def test_realized_volatility_needs_full_window():
    assert M.realized_volatility(pd.Series([100.0] * 10), window=20) is None
    assert M.realized_volatility(pd.Series([100.0] * 30), window=20) is None
    moving = pd.Series([100.0 * (1.01 ** (i % 2)) for i in range(40)])
    vol = M.realized_volatility(moving, window=20)
    assert vol is not None and vol > 0


def test_select_contract_is_call_for_bullish_put_for_bearish():
    call = M.select_contract("bullish", 19.80, 0.6, dte_calendar_days=45)
    put = M.select_contract("bearish", 19.80, 0.6, dte_calendar_days=45)
    assert call.option_type == "call" and call.strike == 20.0
    assert put.option_type == "put" and put.strike == 20.0
    assert call.entry_premium > 0 and put.entry_premium > 0
    assert 0.3 < call.entry_delta < 0.7
    assert M.select_contract("bullish", 19.80, 0.6, strike_offset_steps=1).strike == 20.5
    assert M.select_contract("bearish", 19.80, 0.6, strike_offset_steps=1).strike == 19.5
    assert M.select_contract("sideways", 19.80, 0.6) is None
    assert M.select_contract("bullish", 19.80, None) is None


def test_contract_return_rises_with_spot_and_decays_with_time():
    spec = M.select_contract("bullish", 100.0, 0.5, dte_calendar_days=45)
    up = M.contract_return_pct(spec, 110.0, 5)
    flat = M.contract_return_pct(spec, 100.0, 5)
    down = M.contract_return_pct(spec, 90.0, 5)
    assert up > flat > down
    assert flat < 0  # theta
    assert M.contract_return_pct(spec, 100.0, 20) < flat


def test_spread_haircut_reduces_return_both_ways():
    clean = M.select_contract("bullish", 100.0, 0.5, dte_calendar_days=45, spread_bps_per_side=0)
    costly = M.select_contract("bullish", 100.0, 0.5, dte_calendar_days=45, spread_bps_per_side=300)
    assert M.contract_return_pct(costly, 110.0, 5) < M.contract_return_pct(clean, 110.0, 5)
    assert M.contract_return_pct(clean, 100.0, 0) == pytest.approx(0.0)
    assert M.contract_return_pct(costly, 100.0, 0) < 0


def test_contract_path_uses_calendar_days_from_entry():
    spec = M.select_contract("bullish", 100.0, 0.5, dte_calendar_days=45)
    idx = pd.to_datetime(["2026-06-02", "2026-06-03", "2026-06-08"]).tz_localize("America/New_York")
    path = pd.DataFrame({"Close": [101.0, 102.0, 105.0]}, index=idx)
    entry = pd.Timestamp("2026-06-01", tz="America/New_York")
    out = M.contract_path(spec, path, entry)
    assert list(out["days_elapsed"]) == [1.0, 2.0, 7.0]
    assert out["return_pct"].iloc[-1] > out["return_pct"].iloc[0]
    assert M.contract_path(spec, pd.DataFrame(), entry).empty
