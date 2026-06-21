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

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0):
        seen.update(feed=feed, delay_minutes=delay_minutes, end=end)
        return _bars()

    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)
    now = pd.Timestamp("2026-06-05T12:00:00", tz="America/New_York")

    result = market_data.fetch_intraday_bars("TEST", research=True, now=now)

    assert seen["feed"] == "sip"
    assert seen["delay_minutes"] == 16
    assert seen["end"] == now - pd.Timedelta(minutes=16)
    assert result.attrs["data_feed"] == "sip"
    assert result.attrs["data_delay_minutes"] == 16


def test_current_intraday_keeps_configured_feed(monkeypatch):
    seen = {}

    def fake_fetch(ticker, interval, start, end, *, feed=None, delay_minutes=0):
        seen.update(feed=feed, delay_minutes=delay_minutes)
        return _bars()

    monkeypatch.setenv("ALPACA_FEED", "iex")
    monkeypatch.setattr(market_data, "_alpaca_enabled", lambda: True)
    monkeypatch.setattr(market_data, "_provider_choice", lambda: "alpaca")
    monkeypatch.setattr(market_data, "_fetch_alpaca_bars", fake_fetch)

    result = market_data.fetch_intraday_bars("TEST")

    assert seen == {"feed": "iex", "delay_minutes": 0}
    assert result.attrs["data_feed"] == "iex"
    assert result.attrs["data_delay_minutes"] == 0
