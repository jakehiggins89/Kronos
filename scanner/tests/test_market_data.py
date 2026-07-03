import pandas as pd

from scanner.data import market_data


def _bars():
    idx = pd.date_range("2026-06-01", periods=2, freq="30min", tz="America/New_York")
    return pd.DataFrame(
        [[10, 11, 9, 10.5, 100], [10.5, 12, 10, 11.5, 200]],
        index=idx,
        columns=["Open", "High", "Low", "Close", "Volume"],
    )


def test_research_intraday_uses_delayed_sip(monkeypatch):
    seen = {}

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0, adjustment="raw"):
        seen.update(feed=feed, delay_minutes=delay_minutes, end=end, adjustment=adjustment)
        return _bars()

    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)
    now = pd.Timestamp("2026-06-05T12:00:00", tz="America/New_York")

    result = market_data.fetch_intraday_bars("TEST", research=True, now=now)

    assert seen["feed"] == "sip"
    assert seen["delay_minutes"] == 16
    assert seen["end"] == now - pd.Timedelta(minutes=16)
    # Splits inside the intraday window must not read as price gaps.
    assert seen["adjustment"] == "split"
    assert result.attrs["data_feed"] == "sip"
    assert result.attrs["data_delay_minutes"] == 16


def test_daily_research_passes_adjustment(monkeypatch):
    seen = {}

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0, adjustment="raw"):
        seen.update(feed=feed, delay_minutes=delay_minutes, adjustment=adjustment)
        return _bars()

    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)

    market_data.fetch_daily_bars("TEST", research=True, adjustment="split")

    assert seen["adjustment"] == "split"
    assert seen["feed"] == "sip"


def test_daily_default_adjustment_is_raw(monkeypatch):
    seen = {}

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0, adjustment="raw"):
        seen.update(adjustment=adjustment)
        return _bars()

    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)

    market_data.fetch_daily_bars("TEST")

    assert seen["adjustment"] == "raw"


def test_to_ny_index_keeps_naive_dates_on_same_day():
    # yfinance daily bars arrive as naive midnight DATES; treating them as
    # UTC instants used to shift every session to the prior NY evening.
    idx = pd.DatetimeIndex(["2026-06-01", "2026-06-02"])
    df = pd.DataFrame({"Open": [1.0, 2.0], "High": [1, 2], "Low": [1, 2], "Close": [1, 2], "Volume": [1, 2]}, index=idx)

    out = market_data._to_ny_index(df)

    assert str(out.index.tz) == "America/New_York"
    assert [ts.date().isoformat() for ts in out.index] == ["2026-06-01", "2026-06-02"]


def test_to_ny_index_treats_naive_timestamps_as_utc():
    idx = pd.DatetimeIndex(["2026-06-01 14:30:00", "2026-06-01 15:00:00"])
    df = pd.DataFrame({"Open": [1.0, 2.0], "High": [1, 2], "Low": [1, 2], "Close": [1, 2], "Volume": [1, 2]}, index=idx)

    out = market_data._to_ny_index(df)

    assert str(out.index.tz) == "America/New_York"
    assert out.index[0].hour == 10  # 14:30 UTC == 10:30 NY in June


def _daily_frame(dates):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="America/New_York") for d in dates])
    df = pd.DataFrame(
        {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000},
        index=idx,
    )
    df.attrs["data_provider"] = "alpaca"
    return df


def test_drop_in_progress_daily_bar_mid_session():
    df = _daily_frame(["2026-07-01", "2026-07-02"])
    now = pd.Timestamp("2026-07-02T14:30:00", tz="America/New_York")

    out = market_data.drop_in_progress_daily_bar(df, now=now)

    assert len(out) == 1
    assert out.index[-1].date().isoformat() == "2026-07-01"
    assert out.attrs["data_provider"] == "alpaca"
    assert "2026-07-02" in out.attrs["dropped_in_progress_bar"]


def test_drop_in_progress_daily_bar_keeps_completed_session():
    df = _daily_frame(["2026-07-01", "2026-07-02"])
    now = pd.Timestamp("2026-07-02T16:20:00", tz="America/New_York")

    out = market_data.drop_in_progress_daily_bar(df, now=now)

    assert len(out) == 2


def test_drop_in_progress_daily_bar_keeps_prior_day_bar():
    df = _daily_frame(["2026-06-30", "2026-07-01"])
    now = pd.Timestamp("2026-07-02T10:00:00", tz="America/New_York")

    out = market_data.drop_in_progress_daily_bar(df, now=now)

    assert len(out) == 2


def test_drop_in_progress_daily_bar_empty_frame():
    out = market_data.drop_in_progress_daily_bar(pd.DataFrame())

    assert out.empty


def test_current_intraday_keeps_configured_feed(monkeypatch):
    seen = {}

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0, adjustment="raw"):
        seen.update(feed=feed, delay_minutes=delay_minutes, adjustment=adjustment)
        return _bars()

    monkeypatch.setenv("ALPACA_FEED", "iex")
    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)

    result = market_data.fetch_intraday_bars("TEST")

    assert seen == {"feed": "iex", "delay_minutes": 0, "adjustment": "split"}
    assert result.attrs["data_feed"] == "iex"
    assert result.attrs["data_delay_minutes"] == 0
