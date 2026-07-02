import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd

from scanner import main as scanner_main
from scanner.learning.adaptive_policy import build_adaptive_policy_report
from scanner.models.kronos_adapter import KronosAdapter


def _fake_kronos(calls, fail=False):
    def evaluate(ticker, bars, direction):
        calls.append((ticker, direction))
        if fail:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(
            passed=True,
            directional_agreement=0.7,
            median_forecast_return_pct=1.1,
            worst_sampled_return_pct=-2.2,
            skip_reason=None,
        )

    return SimpleNamespace(evaluate=evaluate)


def _patch_research_scan(monkeypatch, captured, kronos_calls, kronos_fail=False):
    bars = pd.DataFrame(
        {"Open": [10.0], "High": [10.5], "Low": [9.8], "Close": [10.2], "Volume": [1000]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-07-01", tz="America/New_York")]),
    )
    monkeypatch.setattr(scanner_main, "validate_ticker", lambda ticker, logger: SimpleNamespace(skip_reason=None))
    monkeypatch.setattr(scanner_main, "_resolve_calibrated_anchor", lambda ticker: (20, 0))
    monkeypatch.setattr(scanner_main, "fetch_intraday_bars", lambda ticker, research=False: bars)
    monkeypatch.setattr(
        scanner_main,
        "build_synthetic_sessions",
        lambda **kwargs: (bars, {}),
    )
    monkeypatch.setattr(scanner_main, "detect_potter_box", lambda ticker, synthetic: SimpleNamespace(passed=False, direction=None, skip_reason="not near box edge"))
    monkeypatch.setattr(
        scanner_main,
        "score_potter_research_candidate",
        lambda pb, synthetic: {
            "passed": True,
            "direction": "bullish",
            "entry_price": 10.2,
            "score": 70,
            "reason": "research_candidate",
        },
    )
    monkeypatch.setattr(scanner_main, "score_potter_doctrine_v2", lambda ticker, synthetic, pb, es: None)
    monkeypatch.setattr(scanner_main, "append_decision", lambda rec: captured.append(rec) or True)
    return _fake_kronos(kronos_calls, fail=kronos_fail)


def test_research_scan_journals_kronos_fields(monkeypatch):
    captured, kronos_calls = [], []
    kronos = _patch_research_scan(monkeypatch, captured, kronos_calls)

    result = scanner_main._run_single_ticker(
        "TEST", "research_scan", {}, kronos, SimpleNamespace(), logging.getLogger("test")
    )

    assert result["status"] == "pass"
    assert kronos_calls == [("TEST", "bullish")]
    assert len(captured) == 1
    record = captured[0]
    assert record["kronos_directional_agreement"] == 0.7
    assert record["kronos_median_forecast_return_pct"] == 1.1
    assert record["kronos_passed"] is True
    assert record["outcome_status"] == "pending"


def test_research_scan_survives_kronos_failure(monkeypatch):
    captured, kronos_calls = [], []
    kronos = _patch_research_scan(monkeypatch, captured, kronos_calls, kronos_fail=True)

    result = scanner_main._run_single_ticker(
        "TEST", "research_scan", {}, kronos, SimpleNamespace(), logging.getLogger("test")
    )

    assert result["status"] == "pass"
    assert kronos_calls == [("TEST", "bullish")]
    record = captured[0]
    assert "kronos_directional_agreement" not in record
    assert record["kronos_eval_error"] == "model unavailable"
    assert record["outcome_status"] == "pending"


def test_research_scan_respects_kronos_disable_flag(monkeypatch):
    captured, kronos_calls = [], []
    kronos = _patch_research_scan(monkeypatch, captured, kronos_calls)
    monkeypatch.setattr(scanner_main.scanner_config, "KRONOS_RESEARCH_ENABLED", False)

    scanner_main._run_single_ticker(
        "TEST", "research_scan", {}, kronos, SimpleNamespace(), logging.getLogger("test")
    )

    assert kronos_calls == []
    assert "kronos_directional_agreement" not in captured[0]


def test_model_failure_is_not_journaled_as_disagreement(monkeypatch):
    # An adapter error yields passed=False with agreement None; journaling
    # that as kronos_passed=False would poison the lift measurement.
    captured, kronos_calls = [], []
    _patch_research_scan(monkeypatch, captured, kronos_calls)
    errored = SimpleNamespace(
        evaluate=lambda ticker, bars, direction: SimpleNamespace(
            passed=False,
            directional_agreement=None,
            median_forecast_return_pct=None,
            worst_sampled_return_pct=None,
            skip_reason="Kronos error: model exploded",
        )
    )

    scanner_main._run_single_ticker(
        "TEST", "research_scan", {}, errored, SimpleNamespace(), logging.getLogger("test")
    )

    record = captured[0]
    assert "kronos_passed" not in record
    assert "kronos_directional_agreement" not in record
    assert record["kronos_eval_error"] == "Kronos error: model exploded"


def _adapter_bars(rows=90):
    rng = np.random.default_rng(3)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": np.full(rows, 1000.0),
        },
        index=pd.date_range("2026-01-01", periods=rows, freq="D", tz="America/New_York"),
    )


def test_adapter_passes_series_timestamps_to_predictor():
    # KronosPredictor uses the .dt accessor; a raw DatetimeIndex crashed
    # every inference (latent until research candidates started running it).
    captured = {}

    class FakePredictor:
        def predict(self, df, x_timestamp, y_timestamp, pred_len, **kwargs):
            captured["x"] = x_timestamp
            captured["y"] = y_timestamp
            idx = pd.date_range("2026-07-03", periods=pred_len, freq="D")
            return pd.DataFrame({"close": [float(df["close"].iloc[-1])] * pred_len}, index=idx)

    adapter = KronosAdapter(logging.getLogger("test"))
    adapter._predictor = FakePredictor()

    result = adapter.evaluate("TEST", _adapter_bars(), "bullish")

    assert isinstance(captured["x"], pd.Series)
    assert isinstance(captured["y"], pd.Series)
    assert result.output_mode == "multi_path_agreement"
    assert result.directional_agreement is not None


def test_adapter_accepts_research_sized_windows():
    # The research path yields ~42 synthetic sessions (60 calendar days);
    # demanding a full 60-bar lookback made Kronos unrunnable there.
    class FakePredictor:
        def predict(self, df, x_timestamp, y_timestamp, pred_len, **kwargs):
            idx = pd.date_range("2026-07-03", periods=pred_len, freq="D")
            return pd.DataFrame({"close": [float(df["close"].iloc[-1])] * pred_len}, index=idx)

    adapter = KronosAdapter(logging.getLogger("test"))
    adapter._predictor = FakePredictor()

    ok = adapter.evaluate("TEST", _adapter_bars(rows=42), "bullish")
    assert ok.output_mode == "multi_path_agreement"

    too_thin = adapter.evaluate("TEST", _adapter_bars(rows=20), "bullish")
    assert too_thin.passed is False
    assert too_thin.output_mode == "insufficient_context"


def _research_record(ticker, label, ret, agreement=None):
    record = {
        "ticker": ticker,
        "mode": "research_scan",
        "decision_ts": "2026-06-01T10:00:00-04:00",
        "final_pass": False,
        "stage_failed": "potter_box_research",
        "skip_reason": "research_candidate",
        "outcome_status": "resolved",
        "outcome_label": label,
        "outcome_ret_5bar_pct": ret,
        "research_score": 70,
        "research_diagnostics": {"passed": True, "score": 70},
    }
    if agreement is not None:
        record["kronos_directional_agreement"] = agreement
    return record


def test_adaptive_report_measures_kronos_lift():
    records = [
        _research_record("A", "win", 2.0, agreement=0.8),
        _research_record("B", "win", 1.5, agreement=0.9),
        _research_record("C", "loss", -1.0, agreement=0.4),
        _research_record("D", "loss", -2.0, agreement=0.3),
        _research_record("E", "win", 1.0),  # no kronos data
    ]

    report = build_adaptive_policy_report(records, current_research_score=62, min_research_samples=99)

    lift = report["kronos_lift"]
    assert lift["rows_with_kronos"] == 4
    assert lift["agree"]["signal_count"] == 2
    assert lift["agree"]["win_rate"] == 1.0
    assert lift["disagree"]["signal_count"] == 2
    assert lift["disagree"]["win_rate"] == 0.0
    assert lift["lift_win_rate"] == 1.0
    assert lift["lift_average_return_pct"] > 0
