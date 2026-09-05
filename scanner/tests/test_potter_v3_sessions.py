from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.potter_v3 import sessions as S


def _intraday(days: int, *, start_hour: int = 4, end_hour: int = 20, last_day_end_hour: int | None = None) -> pd.DataFrame:
    """Synthetic 30-minute extended-hours bars, one NY trading date per day."""
    rows = []
    price = 100.0
    for d in range(days):
        date = pd.Timestamp("2026-06-01", tz="America/New_York") + pd.Timedelta(days=d)
        end = end_hour if (last_day_end_hour is None or d < days - 1) else last_day_end_hour
        minute = start_hour * 60
        while minute < end * 60:
            ts = date + pd.Timedelta(minutes=minute)
            o = price
            c = price + 0.1
            rows.append({"ts": ts, "Open": o, "High": max(o, c) + 0.2, "Low": min(o, c) - 0.2, "Close": c, "Volume": 1000})
            price = c
            minute += 30
    df = pd.DataFrame(rows).set_index("ts")
    df.index.name = None
    return df


def test_build_eth_sessions_one_candle_per_trading_date():
    intraday = _intraday(3)
    sessions = S.build_eth_sessions(intraday)
    assert len(sessions) == 3
    assert list(sessions.index.date) == sorted(set(intraday.index.date))
    first_day = intraday[intraday.index.date == sessions.index[0].date()]
    assert sessions["Open"].iloc[0] == first_day["Open"].iloc[0]
    assert sessions["Close"].iloc[0] == first_day["Close"].iloc[-1]
    assert sessions["High"].iloc[0] == first_day["High"].max()
    assert sessions["Low"].iloc[0] == first_day["Low"].min()
    assert sessions["Volume"].iloc[0] == first_day["Volume"].sum()
    assert int(sessions["bar_count"].iloc[0]) == 32
    assert sessions.attrs["session_kind"] == "eth_24h"


def test_pre_market_bars_belong_to_their_own_date_not_the_prior_session():
    intraday = _intraday(2)
    sessions = S.build_eth_sessions(intraday)
    day2 = sessions.index[1].date()
    premarket = intraday[(intraday.index.date == day2) & (intraday.index.hour < 9)]
    assert not premarket.empty
    assert sessions.loc[sessions.index[1], "Open"] == premarket["Open"].iloc[0]


def test_drop_in_progress_session_is_judged_by_the_clock_not_the_last_bar():
    intraday = _intraday(3, last_day_end_hour=18)  # thin name: no prints after 18:00
    sessions = S.build_eth_sessions(intraday)
    last_day = sessions.index[-1]
    before_close = last_day + pd.Timedelta(hours=18, minutes=30)
    after_close = last_day + pd.Timedelta(hours=20, minutes=5)
    assert len(S.drop_in_progress_session(sessions, now=before_close)) == 2
    assert len(S.drop_in_progress_session(sessions, now=after_close)) == 3
    next_day = last_day + pd.Timedelta(days=1)
    assert len(S.drop_in_progress_session(sessions, now=next_day)) == 3


def test_clean_intraday_drops_bars_outside_extended_session_and_bad_rows():
    intraday = _intraday(1, start_hour=2, end_hour=22)
    assert intraday.index.hour.min() == 2
    cleaned = S._clean_intraday(intraday)
    assert cleaned.index.hour.min() == 4
    assert cleaned.index.max().hour == 19
    broken = cleaned.copy()
    broken.iloc[0, broken.columns.get_loc("High")] = broken.iloc[0]["Low"] - 1
    assert len(S._clean_intraday(broken)) == len(cleaned) - 1


def test_resample_4h_aligns_to_extended_session_boundaries():
    intraday = _intraday(1)
    four_hour = S.resample_eth(intraday, "4h")
    assert [ts.hour for ts in four_hour.index] == [4, 8, 12, 16]
    first = intraday[(intraday.index.hour >= 4) & (intraday.index.hour < 8)]
    assert four_hour["Open"].iloc[0] == first["Open"].iloc[0]
    assert four_hour["Close"].iloc[0] == first["Close"].iloc[-1]
    assert four_hour["High"].iloc[0] == first["High"].max()
    assert four_hour.attrs["session_kind"] == "eth_4h"


def test_load_intraday_eth_caches_per_ticker_and_fetches_only_the_tail(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(ticker, interval, period, *, research, now, adjustment):
        calls.append({"ticker": ticker, "interval": interval, "period": period, "research": research, "adjustment": adjustment, "now": now})
        days = 3 if period == f"{S.INTRADAY_DAYS}d" else 1
        frame = _intraday(days)
        if days == 1:  # the tail: bars for the day after the cached ones
            frame.index = frame.index + pd.Timedelta(days=3)
        frame.attrs["data_provider"] = "alpaca"
        return frame

    monkeypatch.setattr(S, "fetch_intraday_bars", fake_fetch)
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    as_of = pd.Timestamp("2026-06-03 21:00", tz="America/New_York")
    first = S.load_intraday_eth("SOFI", as_of=as_of)
    second = S.load_intraday_eth("SOFI", as_of=as_of)
    assert len(calls) == 1
    assert calls[0]["research"] is True and calls[0]["adjustment"] == "split" and calls[0]["interval"] == "30m"
    assert calls[0]["period"] == f"{S.INTRADAY_DAYS}d"
    pd.testing.assert_frame_equal(first, second)
    assert S.cache_path("SOFI").exists()
    later = S.load_intraday_eth("SOFI", as_of=as_of + pd.Timedelta(days=1))
    assert len(calls) == 2
    assert calls[1]["period"] == "3d"  # only the missing tail, with overlap
    assert len(later) == len(first) + 32
    assert later.index.is_monotonic_increasing and not later.index.duplicated().any()
    # as_of slices a grown cache back to the requested time without a fetch
    sliced = S.load_intraday_eth("SOFI", as_of=as_of)
    assert len(calls) == 2 and len(sliced) == len(first)


def test_research_universe_is_deduplicated_and_complete():
    universe = S.research_universe()
    assert len(universe) == len(set(universe))
    assert "SOFI" in universe and "AGNC" in universe


def test_empty_inputs_are_safe():
    assert S.build_eth_sessions(pd.DataFrame()).empty
    assert S.resample_eth(pd.DataFrame(), "4h").empty
    assert S.drop_in_progress_session(pd.DataFrame()).empty


def test_load_intraday_eth_refuses_non_alpaca_provider(monkeypatch, tmp_path):
    def yahoo_fetch(ticker, interval, period, *, research, now, adjustment):
        frame = _intraday(1)
        frame.attrs["data_provider"] = "yfinance"
        return frame

    monkeypatch.setattr(S, "fetch_intraday_bars", yahoo_fetch)
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="Alpaca"):
        S.load_intraday_eth("SOFI", as_of=pd.Timestamp("2026-06-03 21:00", tz="America/New_York"))
    assert not any(tmp_path.rglob("*.pkl"))
