import logging

import pandas as pd

from scanner.edge.retrieval import EdgeRecord
from scanner.main import _build_edge_diagnostic_payload, _score_edge_for_bars


def _bars():
    rows = []
    for i in range(45):
        if i < 29:
            rows.append([100, 104, 96, 100 + (0.2 if i % 2 == 0 else -0.2), 1000])
        elif i < 44:
            rows.append([100, 101, 99, 100 + (0.05 if i % 2 == 0 else -0.05), 1200])
        else:
            rows.append([101, 104, 100.5, 103, 2600])
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D", tz="America/New_York")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close", "Volume"])


def _analog_records():
    base_features = {
        "ticker": "HIST",
        "timestamp": "2025-01-01T00:00:00-05:00",
        "direction": "bullish",
        "breakout_distance_pct": 2.0,
        "volume_expansion": 1.8,
        "rr_ratio": 2.0,
        "data_quality_score": 1.0,
        "feed_confidence": 0.9,
    }
    return [
        EdgeRecord("H1", "2025-01-01T00:00:00-05:00", "bullish", base_features, 3.0, "win", 1.2, -0.5, 4.0),
        EdgeRecord("H2", "2025-01-10T00:00:00-05:00", "bullish", base_features, 2.0, "win", 0.9, -0.7, 3.0),
        EdgeRecord("H3", "2025-01-20T00:00:00-05:00", "bullish", base_features, -0.5, "loss", -0.2, -1.2, 1.0),
    ]


def test_score_edge_for_bars_returns_scorecard_without_network():
    result = _score_edge_for_bars("TEST", _bars(), _analog_records(), logging.getLogger("test"))

    assert result["status"] == "candidate"
    assert result["ticker"] == "TEST"
    assert "edge_score" in result
    assert "scorecard" in result
    assert result["analog_summary"]["count"] > 0


def test_build_edge_diagnostic_payload_summarizes_state():
    payload = _build_edge_diagnostic_payload(
        index_records=_analog_records(),
        validation_report={"samples": 10, "thresholds": {"65": {"precision": 0.5}}},
        scan_report={"candidates": [{"recommendation": "research"}, {"recommendation": "promote"}]},
    )

    assert payload["index_records"] == 3
    assert payload["validation_samples"] == 10
    assert payload["recommendation_counts"]["promote"] == 1
