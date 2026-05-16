import pandas as pd

from scanner.strategy.empty_space import score_empty_space


def _bars():
    idx = pd.date_range("2025-01-01", periods=80, freq="D", tz="America/New_York")
    base = [100.0 for _ in range(80)]
    data = {
        "Open": base,
        "High": [101.0 for _ in range(80)],
        "Low": [99.0 for _ in range(80)],
        "Close": base,
        "Volume": [1000] * 80,
    }
    return pd.DataFrame(data, index=idx)


def test_score_zero_when_blocked():
    bars = _bars()
    bars.iloc[-2, bars.columns.get_loc("High")] = 110.1
    res = score_empty_space(bars, "bullish", breakout_close=110.0, cost_basis=109.7)
    assert res.score == 0
    assert res.passed is False


def test_score_two_rr_ge_15():
    bars = _bars()
    bars.iloc[:-1, bars.columns.get_loc("High")] = 120.0
    res = score_empty_space(bars, "bullish", breakout_close=110.0, cost_basis=106.0)
    assert res.rr_ratio >= 1.5
    assert res.score >= 2


def test_score_three_rr_ge_25():
    bars = _bars()
    bars.iloc[:-1, bars.columns.get_loc("Low")] = 90.0
    res = score_empty_space(bars, "bearish", breakout_close=100.0, cost_basis=104.0)
    assert res.rr_ratio >= 2.5
    assert res.score == 3
