"""Pre-registered evaluation of the Potter v3 index.

The cells, filters, statistics and acceptance rule below are fixed in
research/potter_v3/PREREGISTRATION.md before any outcome is read. One cell is
primary; every other cell is descriptive and logged for multiplicity.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from ..edge.stats import day_clustered_precision, day_clustered_t, wilson_lower_bound
from .pipeline import PRIMARY_HORIZON, output_dir

PRIMARY_CELL = "punchback_bull"
ACCEPTANCE = {
    "min_entry_days": 60,
    "min_hac_t_net_return": 2.0,
    "min_hac_t_vs_control": 2.0,
    "min_precision_lower_bound": 0.45,
}

CELLS: dict[str, dict] = {
    "punchback_bull": {"kinds": ["punchback_bull"], "direction": "bullish"},
    "cb_break_bull": {"kinds": ["cb_break_bull"], "direction": "bullish"},
    "breakout_es1plus": {"kinds": ["breakout"], "direction": "bullish", "min_empty_space_score": 1},
    "breakout_all": {"kinds": ["breakout"], "direction": "bullish"},
    "floor_reclaim": {"kinds": ["floor_reclaim"], "direction": "bullish"},
    "punchback_bear": {"kinds": ["punchback_bear"], "direction": "bearish"},
    "cb_break_bear": {"kinds": ["cb_break_bear"], "direction": "bearish"},
    "breakdown_es1plus": {"kinds": ["breakdown"], "direction": "bearish", "min_empty_space_score": 1},
    "breakdown_all": {"kinds": ["breakdown"], "direction": "bearish"},
    "ceiling_reject": {"kinds": ["ceiling_reject"], "direction": "bearish"},
    "punchback_bull_confirmed_24h": {"kinds": ["punchback_bull"], "direction": "bullish", "confirmed_24h": True},
    "all_bullish": {"kinds": ["breakout", "punchback_bull", "cb_break_bull", "floor_reclaim"], "direction": "bullish"},
    "all_bearish": {"kinds": ["breakdown", "punchback_bear", "cb_break_bear", "ceiling_reject"], "direction": "bearish"},
}


def _eligible(record: dict, horizon_key: str) -> bool:
    outcome = record.get("outcomes", {}).get(horizon_key)
    return bool(record.get("tradeable") and not record.get("overlapping") and outcome and outcome.get("resolved"))


def select_cell(records: list[dict], spec: dict, horizon_key: str) -> list[dict]:
    out = []
    for record in records:
        if not _eligible(record, horizon_key):
            continue
        if record.get("kind") not in spec["kinds"] or record.get("direction") != spec["direction"]:
            continue
        if "min_empty_space_score" in spec and int(record.get("empty_space_score") or 0) < spec["min_empty_space_score"]:
            continue
        if "confirmed_24h" in spec and bool(record.get("confirmed_24h")) != spec["confirmed_24h"]:
            continue
        out.append(record)
    return out


def _day_key(record: dict) -> str:
    return str(record["session"])[:10]


def _mean(values: list[float]) -> float | None:
    return float(statistics.fmean(values)) if values else None


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def cell_statistics(records: list[dict], horizon_key: str) -> dict:
    net = [float(r["outcomes"][horizon_key]["stock_return_net_pct"]) for r in records]
    gross = [float(r["outcomes"][horizon_key]["stock_return_pct"]) for r in records]
    r_mult = [float(r["outcomes"][horizon_key]["r_multiple"]) for r in records]
    wins = [1.0 if v > 0 else 0.0 for v in net]
    days = [_day_key(r) for r in records]
    contract = [r["outcomes"][horizon_key].get("contract_return_net_pct") for r in records]
    contract = [float(v) for v in contract if v is not None]
    contract_wins = [1.0 if v > 0 else 0.0 for v in contract]
    exits: dict[str, int] = {}
    for r in records:
        reason = str(r["outcomes"][horizon_key]["exit_reason"])
        exits[reason] = exits.get(reason, 0) + 1
    paired = []
    paired_days = []
    control_net = []
    for r in records:
        ctrl = r.get("control")
        if not ctrl:
            continue
        c_out = ctrl.get("outcomes", {}).get(horizon_key)
        if not c_out or not c_out.get("resolved"):
            continue
        control_net.append(float(c_out["stock_return_net_pct"]))
        paired.append(float(r["outcomes"][horizon_key]["stock_return_net_pct"]) - float(c_out["stock_return_net_pct"]))
        paired_days.append(_day_key(r))
    hac = day_clustered_t(net, days) if net else {"n_days": 0, "t_stat": 0.0, "mean_of_day_means": 0.0}
    precision = day_clustered_precision(wins, days) if wins else {"lower_bound": 0.0, "n_days": 0}
    paired_hac = day_clustered_t(paired, paired_days) if paired else {"n_days": 0, "t_stat": 0.0, "mean_of_day_means": 0.0}
    return {
        "n": len(records),
        "n_days": int(hac.get("n_days", 0)),
        "tickers": len({r["ticker"] for r in records}),
        "mean_net_return_pct": _mean(net),
        "median_net_return_pct": _median(net),
        "mean_gross_return_pct": _mean(gross),
        "mean_r_multiple": _mean(r_mult),
        "hac_t_net_return": float(hac.get("t_stat", 0.0)),
        "day_mean_net_return_pct": float(hac.get("mean_of_day_means", 0.0)),
        "win_rate": _mean(wins),
        "win_rate_wilson_lb": wilson_lower_bound(sum(wins), len(wins)) if wins else 0.0,
        "precision_lower_bound_day_clustered": float(precision.get("lower_bound", 0.0)),
        "contract_n": len(contract),
        "contract_mean_net_return_pct": _mean(contract),
        "contract_median_net_return_pct": _median(contract),
        "contract_win_rate": _mean(contract_wins),
        "control_n": len(control_net),
        "control_mean_net_return_pct": _mean(control_net),
        "paired_mean_diff_pct": _mean(paired),
        "hac_t_vs_control": float(paired_hac.get("t_stat", 0.0)),
        "exit_reasons": exits,
    }


def acceptance_verdict(stats: dict) -> dict:
    checks = {
        "entry_days": (stats["n_days"] >= ACCEPTANCE["min_entry_days"], stats["n_days"], ACCEPTANCE["min_entry_days"]),
        "hac_t_net_return": (stats["hac_t_net_return"] >= ACCEPTANCE["min_hac_t_net_return"], stats["hac_t_net_return"], ACCEPTANCE["min_hac_t_net_return"]),
        "hac_t_vs_control": (stats["hac_t_vs_control"] >= ACCEPTANCE["min_hac_t_vs_control"], stats["hac_t_vs_control"], ACCEPTANCE["min_hac_t_vs_control"]),
        "precision_lower_bound": (stats["precision_lower_bound_day_clustered"] >= ACCEPTANCE["min_precision_lower_bound"], stats["precision_lower_bound_day_clustered"], ACCEPTANCE["min_precision_lower_bound"]),
    }
    passed = all(ok for ok, _, _ in checks.values())
    return {
        "passed": passed,
        "checks": {name: {"ok": ok, "value": value, "required": req} for name, (ok, value, req) in checks.items()},
        "verdict": "PASS: primary cell clears every pre-registered gate" if passed else "FAIL: primary cell does not clear the pre-registered gates",
    }


def evaluate(payload: dict, *, horizons: tuple[int, ...] = (1, 3, 5)) -> dict:
    records = payload["records"]
    results: dict = {"cells": {}, "primary_cell": PRIMARY_CELL, "primary_horizon": PRIMARY_HORIZON, "acceptance": ACCEPTANCE}
    for name, spec in CELLS.items():
        per_h = {}
        for h in horizons:
            key = f"h{h}"
            selected = select_cell(records, spec, key)
            per_h[key] = cell_statistics(selected, key)
        results["cells"][name] = {"spec": spec, "by_horizon": per_h}
    primary = results["cells"][PRIMARY_CELL]["by_horizon"][f"h{PRIMARY_HORIZON}"]
    results["primary_stats"] = primary
    results["verdict"] = acceptance_verdict(primary)
    results["summary"] = payload.get("summary", {})
    results["multiplicity"] = {"cells_evaluated": len(CELLS) * len(horizons), "primary_cells": 1}
    return results


def _fmt(value, digits=2, suffix=""):
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def render_report(results: dict) -> str:
    lines = ["# Potter v3 evaluation", ""]
    verdict = results["verdict"]
    lines.append(f"**Verdict:** {verdict['verdict']}")
    lines.append("")
    lines.append(f"Primary cell `{results['primary_cell']}` at h{results['primary_horizon']}:")
    lines.append("")
    lines.append("| gate | value | required | ok |")
    lines.append("|---|---:|---:|---|")
    for name, check in verdict["checks"].items():
        lines.append(f"| {name} | {_fmt(check['value'])} | {check['required']} | {'yes' if check['ok'] else 'no'} |")
    lines.append("")
    summary = results.get("summary", {})
    lines.append(f"Index: {summary.get('records')} triggers, {summary.get('tradeable_non_overlapping')} tradeable non-overlapping, {summary.get('tickers_loaded')} tickers, sessions {summary.get('first_session')} to {summary.get('last_session')}, controls {summary.get('controls')}.")
    lines.append("")
    lines.append("## Cells (stock leg net of 25 bps/side; contract leg net of 10%/side spread)")
    lines.append("")
    lines.append("| cell | h | n | days | mean net % | HAC t | win | prec LB | mean R | contract mean % | contract median % | control mean % | paired diff % | HAC t vs ctrl | exits |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for name, cell in results["cells"].items():
        for key, st in cell["by_horizon"].items():
            exits = ",".join(f"{k}:{v}" for k, v in sorted(st["exit_reasons"].items()))
            lines.append(
                f"| {name} | {key} | {st['n']} | {st['n_days']} | {_fmt(st['mean_net_return_pct'])} | {_fmt(st['hac_t_net_return'])} | "
                f"{_fmt(st['win_rate'], 2)} | {_fmt(st['precision_lower_bound_day_clustered'], 2)} | {_fmt(st['mean_r_multiple'])} | "
                f"{_fmt(st['contract_mean_net_return_pct'], 0)} | {_fmt(st['contract_median_net_return_pct'], 0)} | {_fmt(st['control_mean_net_return_pct'])} | "
                f"{_fmt(st['paired_mean_diff_pct'])} | {_fmt(st['hac_t_vs_control'])} | {exits} |"
            )
    lines.append("")
    lines.append(f"Multiplicity: {results['multiplicity']['cells_evaluated']} cells evaluated, {results['multiplicity']['primary_cells']} primary.")
    return "\n".join(lines) + "\n"


def save_results(results: dict, directory: Path | None = None) -> tuple[Path, Path]:
    directory = directory or output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "evaluation.json"
    md_path = directory / "evaluation.md"
    json_path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    md_path.write_text(render_report(results), encoding="utf-8")
    return json_path, md_path
