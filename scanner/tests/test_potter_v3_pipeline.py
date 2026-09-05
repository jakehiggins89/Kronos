from __future__ import annotations

import json

import pandas as pd
import pytest

from scanner.potter_v3 import cli as CLI
from scanner.potter_v3 import evaluate as E
from scanner.potter_v3 import pipeline as P
from scanner.potter_v3.outcomes import build_day_table

TZ = "America/New_York"
TOP, BOTTOM = 20.7, 19.0


def _intraday_from_sessions(rows, start="2026-01-05"):
    """Expand (open, close@16:00, close@20:00, high, low) session rows into 30-minute bars.

    Regular-session bars carry the 16:00 close; the 16:00-19:30 bars drift to
    the 20:00 close so the partial and full candles differ as in real data.
    """
    dates = pd.bdate_range(start, periods=len(rows), tz=TZ)
    bars = []
    for date, (o, c16, c20, hi, lo) in zip(dates, rows):
        minute = 4 * 60
        while minute < 20 * 60:
            ts = date + pd.Timedelta(minutes=minute)
            if minute < 16 * 60:
                px = o + (c16 - o) * (minute - 4 * 60) / (12 * 60)
            else:
                px = c16 + (c20 - c16) * (minute - 16 * 60) / (4 * 60)
            bar_hi = max(px, hi) if 10 * 60 <= minute < 15 * 60 else px + 0.02
            bar_lo = min(px, lo) if 10 * 60 <= minute < 15 * 60 else px - 0.02
            bars.append({"ts": ts, "Open": px, "High": bar_hi, "Low": bar_lo, "Close": px, "Volume": 100})
            minute += 30
    df = pd.DataFrame(bars).set_index("ts")
    df.index.name = None
    df.attrs["data_provider"] = "alpaca"
    return df


def _box_rows(scenario):
    prior = [(26.5, 26.0, 26.0, 26.6, 25.9), (26.0, 24.0, 24.0, 26.1, 23.9), (24.0, 22.4, 22.4, 24.1, 22.3)]
    box = []
    for w in range(6):
        level = BOTTOM if w % 2 == 0 else TOP
        box.extend([(19.3, level, level, level + 0.1, level - 0.1)] * 2)
    # hold the top for two more sessions so the last cost-basis crossing sits
    # outside the hold window of the scenario's first session
    box.extend([(20.6, TOP, TOP, TOP + 0.1, TOP - 0.1)] * 2)
    return prior + box + list(scenario)


def _ticker_data(ticker, scenario):
    intraday = _intraday_from_sessions(_box_rows(scenario))
    from scanner.potter_v3 import sessions as S

    full = S.build_eth_sessions(intraday)
    partial = S.build_partial_sessions(intraday)
    return P.TickerData(ticker=ticker, intraday=intraday, full=full, partial=partial, day_table=build_day_table(intraday))


SCENARIOS = {
    # breakout that runs to the structure
    "AAA": [(20.6, 21.3, 21.4, 21.4, 20.5), (21.4, 21.9, 22.0, 22.5, 21.3), (22.0, 22.3, 22.3, 22.6, 21.9), (22.3, 22.2, 22.2, 22.4, 22.0), (22.2, 22.1, 22.1, 22.3, 22.0)],
    # no trigger at all: keeps drifting inside the upper half
    "BBB": [(20.5, 20.4, 20.4, 20.6, 20.3), (20.4, 20.3, 20.3, 20.5, 20.2), (20.3, 20.4, 20.4, 20.5, 20.2), (20.4, 20.5, 20.5, 20.6, 20.3), (20.5, 20.4, 20.4, 20.6, 20.3)],
    # also quiet, second control candidate
    "CCC": [(20.5, 20.4, 20.4, 20.6, 20.3), (20.4, 20.3, 20.3, 20.5, 20.2), (20.3, 20.4, 20.4, 20.5, 20.2), (20.4, 20.5, 20.5, 20.6, 20.3), (20.5, 20.4, 20.4, 20.6, 20.3)],
}


def _loader(ticker, *, as_of=None, use_cache=True):
    return _ticker_data(ticker, SCENARIOS[ticker])


def test_build_records_produces_outcomes_controls_and_summary():
    payload = P.build_records(list(SCENARIOS), loader=_loader)
    summary = payload["summary"]
    records = payload["records"]
    assert summary["tickers_loaded"] == 3 and summary["failures"] == {}
    scenario_start = pd.bdate_range("2026-01-05", periods=18, tz=TZ)[17]
    breakouts = [r for r in records if r["ticker"] == "AAA" and r["kind"] == "breakout" and pd.Timestamp(r["session"]) >= scenario_start]
    assert len(breakouts) == 1
    rec = breakouts[0]
    assert set(rec["outcomes"]) == {"h1", "h3", "h5"}
    assert rec["outcomes"]["h3"]["resolved"] is True
    assert rec["outcomes"]["h3"]["exit_reason"] == "target"
    assert rec["control"] is not None and rec["control"]["ticker"] in {"BBB", "CCC"}
    assert set(rec["control"]["outcomes"]) == {"h1", "h3", "h5"}
    assert rec["control"]["outcomes"]["h3"]["resolved"] is True
    assert summary["records"] == len(records) and summary["controls"] >= 1
    assert "breakout" in summary["by_kind"]


def test_build_records_is_deterministic_and_survives_a_bad_ticker():
    def flaky(ticker, *, as_of=None, use_cache=True):
        if ticker == "BBB":
            raise RuntimeError("boom")
        return _loader(ticker, as_of=as_of, use_cache=use_cache)

    first = P.build_records(list(SCENARIOS), loader=flaky)
    second = P.build_records(list(SCENARIOS), loader=flaky)
    assert first["summary"]["failures"] == {"BBB": "RuntimeError: boom"}
    assert [r["control"] and r["control"]["ticker"] for r in first["records"]] == [r["control"] and r["control"]["ticker"] for r in second["records"]]
    assert all((r["control"] or {}).get("ticker") != "BBB" for r in first["records"])


def test_save_load_roundtrip_and_evaluate_report(tmp_path, monkeypatch):
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    payload = P.build_records(list(SCENARIOS), loader=_loader)
    path = P.save_records(payload)
    assert path == tmp_path / "potter_v3" / "records.json" and path.exists()
    loaded = P.load_records()
    assert loaded["summary"]["records"] == payload["summary"]["records"]
    results = E.evaluate(loaded)
    assert set(results["cells"]) == set(E.CELLS)
    assert results["primary_cell"] == "punchback_bull"
    assert results["verdict"]["passed"] is False  # far too few entry days on a toy fixture
    assert results["verdict"]["checks"]["entry_days"]["ok"] is False
    breakout = results["cells"]["breakout_all"]["by_horizon"]["h3"]
    assert breakout["n"] >= 1 and breakout["control_n"] >= 1 and breakout["paired_mean_diff_pct"] is not None
    json_path, md_path = E.save_results(results)
    assert json_path.exists() and "Verdict" in md_path.read_text(encoding="utf-8")
    report = E.render_report(results)
    assert "| breakout_all | h3 |" in report


def test_acceptance_verdict_requires_every_gate():
    good = {"n_days": 80, "hac_t_net_return": 2.5, "hac_t_vs_control": 2.2, "precision_lower_bound_day_clustered": 0.5}
    assert E.acceptance_verdict(good)["passed"] is True
    for key, bad in [("n_days", 59), ("hac_t_net_return", 1.99), ("hac_t_vs_control", 1.0), ("precision_lower_bound_day_clustered", 0.44)]:
        verdict = E.acceptance_verdict({**good, key: bad})
        names = {"n_days": "entry_days", "hac_t_net_return": "hac_t_net_return", "hac_t_vs_control": "hac_t_vs_control", "precision_lower_bound_day_clustered": "precision_lower_bound"}
        assert verdict["passed"] is False and verdict["checks"][names[key]]["ok"] is False


def test_select_cell_filters_untradeable_overlapping_and_unresolved():
    base = {"kind": "breakout", "direction": "bullish", "tradeable": True, "overlapping": False, "empty_space_score": 2, "confirmed_24h": True, "outcomes": {"h3": {"resolved": True}}}
    spec = E.CELLS["breakout_es1plus"]
    assert len(E.select_cell([base], spec, "h3")) == 1
    assert E.select_cell([{**base, "tradeable": False}], spec, "h3") == []
    assert E.select_cell([{**base, "overlapping": True}], spec, "h3") == []
    assert E.select_cell([{**base, "outcomes": {"h3": {"resolved": False}}}], spec, "h3") == []
    assert E.select_cell([{**base, "empty_space_score": 0}], spec, "h3") == []
    assert E.select_cell([{**base, "kind": "breakdown"}], spec, "h3") == []
    assert E.select_cell([{**base, "confirmed_24h": False}], E.CELLS["punchback_bull_confirmed_24h"], "h3") == []


def test_cli_scan_prints_banner_and_writes_research_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    monkeypatch.setattr(CLI, "load_ticker", _loader)
    assert CLI.main(["--mode", "scan", "--tickers", "AAA,BBB"]) == 0
    out = capsys.readouterr().out
    assert CLI.RESEARCH_BANNER in out
    written = json.loads((tmp_path / "potter_v3" / "latest_scan.json").read_text(encoding="utf-8"))
    assert written["banner"] == CLI.RESEARCH_BANNER
    assert {row["ticker"] for row in written["rows"]} == {"AAA", "BBB"}


def test_cli_hash_inputs_reports_missing_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    assert CLI.main(["--mode", "hash-inputs", "--tickers", "ZZZ"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ZZZ": "missing"}
    assert P.input_hashes(["ZZZ"]) == {"ZZZ": "missing"}


def test_cli_build_and_evaluate_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scanner.config.REPORT_DIR", tmp_path)
    monkeypatch.setattr(CLI, "build_records", lambda tickers, as_of, use_cache: P.build_records(tickers, loader=_loader))
    assert CLI.main(["--mode", "build", "--tickers", "AAA,BBB,CCC"]) == 0
    assert (tmp_path / "potter_v3" / "records.json").exists()
    assert CLI.main(["--mode", "evaluate"]) == 3  # toy fixture cannot pass the gates
    assert (tmp_path / "potter_v3" / "evaluation.md").exists()
