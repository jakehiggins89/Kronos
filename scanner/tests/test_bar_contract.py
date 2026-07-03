import pandas as pd

from scanner.data.bar_contract import check_ohlcv_contract


def _frame(rows, start="2026-06-01"):
    idx = pd.date_range(start, periods=len(rows), freq="D", tz="America/New_York")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])


def test_clean_bars_pass():
    df = _frame([[10, 11, 9, 10.5, 100], [10.5, 12, 10, 11.5, 200]])
    violations, warnings = check_ohlcv_contract(df)
    assert violations == []
    assert warnings == []


def test_empty_frame_fails():
    violations, _ = check_ohlcv_contract(pd.DataFrame())
    assert violations == ["empty bar frame"]


def test_high_below_body_fails():
    df = _frame([[10, 9.5, 9, 10.5, 100]])
    violations, _ = check_ohlcv_contract(df)
    assert any("High below" in v for v in violations)


def test_low_above_body_fails():
    df = _frame([[10, 11, 10.2, 10.5, 100]])
    violations, _ = check_ohlcv_contract(df)
    assert any("Low above" in v for v in violations)


def test_nonpositive_price_fails():
    df = _frame([[0.0, 11, 9, 10.5, 100]])
    violations, _ = check_ohlcv_contract(df)
    assert any("non-positive" in v for v in violations)


def test_negative_volume_fails():
    df = _frame([[10, 11, 9, 10.5, -5]])
    violations, _ = check_ohlcv_contract(df)
    assert any("negative volume" in v for v in violations)


def test_nan_ohlc_fails():
    df = _frame([[10, 11, 9, float("nan"), 100]])
    violations, _ = check_ohlcv_contract(df)
    assert any("NaN OHLC" in v for v in violations)


def test_duplicate_timestamps_fail():
    idx = pd.DatetimeIndex(["2026-06-01", "2026-06-01"]).tz_localize("America/New_York")
    df = pd.DataFrame(
        [[10, 11, 9, 10.5, 100], [10.5, 12, 10, 11.5, 200]],
        index=idx,
        columns=["Open", "High", "Low", "Close", "Volume"],
    )
    violations, _ = check_ohlcv_contract(df)
    assert any("duplicate timestamps" in v for v in violations)


def test_unsorted_timestamps_fail():
    idx = pd.DatetimeIndex(["2026-06-02", "2026-06-01"]).tz_localize("America/New_York")
    df = pd.DataFrame(
        [[10, 11, 9, 10.5, 100], [10.5, 12, 10, 11.5, 200]],
        index=idx,
        columns=["Open", "High", "Low", "Close", "Volume"],
    )
    violations, _ = check_ohlcv_contract(df)
    assert any("not sorted" in v for v in violations)


def test_suspect_split_sized_move_warns_but_passes():
    # A 50% one-day drop is the fingerprint of a missed corporate action on
    # raw bars; it must be surfaced without deleting the ticker outright.
    df = _frame([[100, 101, 99, 100, 100], [50, 51, 49, 50, 100]])
    violations, warnings = check_ohlcv_contract(df)
    assert violations == []
    assert len(warnings) == 1
    assert "suspect one-bar move" in warnings[0]
