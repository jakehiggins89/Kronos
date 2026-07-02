import logging

import pandas as pd

from scanner.learning import outcome_reviewer


def test_review_pending_outcomes_anchors_after_hours_decision_to_signal_session(monkeypatch, tmp_path):
    synthetic = pd.DataFrame(
        {"Close": [10.0, 10.5, 11.0, 11.5, 12.0, 12.5]},
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-06-24 00:00", tz="America/New_York"),
                pd.Timestamp("2026-06-25 00:00", tz="America/New_York"),
                pd.Timestamp("2026-06-26 00:00", tz="America/New_York"),
                pd.Timestamp("2026-06-29 00:00", tz="America/New_York"),
                pd.Timestamp("2026-06-30 00:00", tz="America/New_York"),
                pd.Timestamp("2026-07-01 00:00", tz="America/New_York"),
            ]
        ),
    )
    records = [
        {
            "ticker": "TEST",
            "decision_ts": "2026-06-24T19:03:00-04:00",
            "direction": "bullish",
            "entry_price": 10.0,
            "outcome_status": "pending",
            "counterfactual": True,
        }
    ]

    monkeypatch.setattr(outcome_reviewer, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(outcome_reviewer, "OUTCOME_MIN_AGE_DAYS", -1_000_000)
    monkeypatch.setattr(outcome_reviewer, "fetch_intraday_bars", lambda ticker: pd.DataFrame())
    monkeypatch.setattr(
        outcome_reviewer,
        "build_synthetic_sessions",
        lambda intraday, anchor_hour, anchor_minute, source_interval, prepost_enabled: (synthetic, {}),
    )

    reviewed, summary = outcome_reviewer.review_pending_outcomes(records, logging.getLogger("test"))

    assert summary["resolved_now"] == 1
    assert summary["resolved_counterfactual"] == 1
    assert reviewed[0]["outcome_status"] == "resolved"
    assert reviewed[0]["outcome_label"] == "win"
    assert reviewed[0]["outcome_ret_5bar_pct"] == 25.0
