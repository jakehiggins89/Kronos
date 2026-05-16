import pandas as pd

from scanner.strategy.potter_box import detect_potter_box, score_potter_research_candidate


def _make_synthetic_df():
    rows = []
    price = 100.0
    for i in range(40):
        if i < 24:
            high = price + 3.0
            low = price - 3.0
            close = price + (0.2 if i % 2 == 0 else -0.2)
        elif i < 39:
            high = 101.0
            low = 99.0
            close = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        else:
            high = 103.0
            low = 100.5
            close = 102.5
        rows.append([price, high, low, close, 1000])
    idx = pd.date_range("2025-01-01", periods=40, freq="D", tz="America/New_York")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])


def test_consolidation_excludes_breakout_candle():
    df = _make_synthetic_df()
    result = detect_potter_box("TEST", df)
    assert result.box_top == 101.0
    assert result.breakout_close > result.box_top


def test_bullish_requires_prior_close_above_cost_basis():
    df = _make_synthetic_df()
    df.iloc[-2, df.columns.get_loc("Close")] = 99.0
    result = detect_potter_box("TEST", df)
    assert result.passed is False


def test_research_candidate_scores_near_breakout():
    df = _make_synthetic_df()
    df.iloc[-1, df.columns.get_loc("Close")] = 100.7
    df.iloc[-1, df.columns.get_loc("High")] = 101.0
    df.iloc[-1, df.columns.get_loc("Volume")] = 2000
    result = detect_potter_box("TEST", df)
    candidate = score_potter_research_candidate(result, df)
    assert candidate["direction"] == "bullish"
    assert candidate["score"] > 0
    assert candidate["breakout_state"] in {"near_breakout", "confirmed_breakout"}
