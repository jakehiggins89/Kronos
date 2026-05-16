import pandas as pd

from scanner.edge.features import extract_edge_features
from scanner.strategy.empty_space import score_empty_space
from scanner.strategy.potter_box import detect_potter_box


def _bars():
    rows = []
    for i in range(40):
        if i < 24:
            rows.append([100, 104, 96, 100 + (0.2 if i % 2 == 0 else -0.2), 1000])
        elif i < 39:
            rows.append([100, 101, 99, 100 + (0.05 if i % 2 == 0 else -0.05), 1200])
        else:
            rows.append([101, 104, 100.5, 103, 2500])
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D", tz="America/New_York")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])


def test_extract_edge_features_has_stable_numeric_fields():
    bars = _bars()
    pb = detect_potter_box("TEST", bars)
    es = score_empty_space(bars, "bullish", pb.breakout_close, pb.cost_basis)

    features = extract_edge_features("TEST", bars, pb, es)

    assert features["ticker"] == "TEST"
    assert features["direction"] == "bullish"
    assert features["potter_passed"] == 1.0
    assert features["breakout_distance_pct"] > 0
    assert features["volume_expansion"] > 1
    assert "feature_version" in features
