from types import SimpleNamespace

import pandas as pd

from scanner.data.options_data import select_options_contract


class DummyTicker:
    def __init__(self, options, chain_df):
        self._options = options
        self._chain_df = chain_df

    @property
    def options(self):
        return self._options

    def option_chain(self, _exp):
        return SimpleNamespace(calls=self._chain_df, puts=self._chain_df)


class DummyLogger:
    def error(self, *args, **kwargs):
        return None


def test_fails_empty_chain(monkeypatch):
    import yfinance as yf

    monkeypatch.setattr(yf, "Ticker", lambda _t: DummyTicker([], pd.DataFrame()))
    res = select_options_contract("TEST", "bullish", 100.0, DummyLogger())
    assert res.passed is False


def test_passes_valid_contract(monkeypatch):
    import yfinance as yf

    chain_df = pd.DataFrame(
        [
            {
                "strike": 100,
                "bid": 1.0,
                "ask": 1.1,
                "openInterest": 1000,
                "volume": 50,
                "impliedVolatility": 0.5,
            }
        ]
    )
    monkeypatch.setattr(yf, "Ticker", lambda _t: DummyTicker([(pd.Timestamp.now() + pd.Timedelta(days=35)).strftime("%Y-%m-%d")], chain_df))
    res = select_options_contract("TEST", "bullish", 100.0, DummyLogger())
    assert res.passed is True


def test_fails_spread_too_wide(monkeypatch):
    import yfinance as yf

    chain_df = pd.DataFrame(
        [
            {
                "strike": 100,
                "bid": 1.0,
                "ask": 2.0,
                "openInterest": 1000,
                "volume": 50,
                "impliedVolatility": 0.5,
            }
        ]
    )
    monkeypatch.setattr(yf, "Ticker", lambda _t: DummyTicker([(pd.Timestamp.now() + pd.Timedelta(days=35)).strftime("%Y-%m-%d")], chain_df))
    res = select_options_contract("TEST", "bullish", 100.0, DummyLogger())
    assert res.passed is False
