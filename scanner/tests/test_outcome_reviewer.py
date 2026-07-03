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


def _ohlc_sessions():
    idx = pd.DatetimeIndex(
        [pd.Timestamp(f"2026-06-{day:02d} 00:00", tz="America/New_York") for day in (22, 23, 24, 25, 26, 29, 30)]
    )
    # Entry session close 10.0; path then runs to 13.0 without touching a
    # 2R-style target exit because the shipped plan has NO target.
    return pd.DataFrame(
        {
            "Open": [10.0, 10.2, 10.6, 11.2, 11.8, 12.4, 12.9],
            "High": [10.1, 10.7, 11.4, 12.0, 12.6, 13.1, 13.4],
            "Low": [9.9, 10.1, 10.5, 11.1, 11.7, 12.3, 12.8],
            "Close": [10.0, 10.6, 11.3, 11.9, 12.5, 13.0, 13.3],
        },
        index=idx,
    )


def test_journal_outcomes_follow_shipped_no_target_geometry(monkeypatch, tmp_path):
    # The reviewer used to hardcode a 2R target, so the adaptive policy
    # learned from an exit geometry the lab no longer trades. Under the
    # shipped no-target plan, this runaway winner must exit at the horizon,
    # not at a phantom target.
    records = [
        {
            "ticker": "TEST",
            "decision_ts": "2026-06-22T15:00:00-04:00",
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
        lambda intraday, anchor_hour, anchor_minute, source_interval, prepost_enabled: (_ohlc_sessions(), {}),
    )

    reviewed, summary = outcome_reviewer.review_pending_outcomes(records, logging.getLogger("test"))

    assert summary["resolved_now"] == 1
    assert reviewed[0]["outcome_method"] == "triple_barrier"
    assert reviewed[0]["outcome_target_mode"] == "none"
    assert reviewed[0]["outcome_exit_reason"] == "horizon"
    assert reviewed[0]["outcome_return_pct"] == 30.0
