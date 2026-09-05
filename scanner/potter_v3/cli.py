"""Command line for the Potter v3 research path.

    python -m scanner.potter_v3 --mode build      # fetch/cached bars -> records.json
    python -m scanner.potter_v3 --mode evaluate   # records.json -> evaluation.json/.md
    python -m scanner.potter_v3 --mode scan       # today's triggers on the watchlist (research print only)
    python -m scanner.potter_v3 --mode hash-inputs

Nothing here sends an alert, reads the retirement marker, or writes to the
retired lab's report paths. The scan mode prints a research summary and
writes it beside the records; it is not a trade signal.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from .. import config as scanner_config
from . import sessions as S
from .env import load_project_env
from .evaluate import evaluate, render_report, save_results
from .pipeline import build_records, input_hashes, load_records, load_ticker, output_dir, records_path, save_records
from .triggers import scan_triggers

RESEARCH_BANNER = "POTTER V3 RESEARCH OUTPUT - not a trade signal; the scanner strategy remains retired."


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="scanner.potter_v3", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["build", "evaluate", "scan", "hash-inputs"], default="scan")
    parser.add_argument("--tickers", default="", help="comma-separated override of the research universe")
    parser.add_argument("--as-of", default=None, help="ISO date/time in New York for cache keying and the scan date")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--out", default=None, help="records path override for build/evaluate")
    return parser.parse_args(argv)


def _tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers.strip():
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    return S.research_universe()


def _as_of(args: argparse.Namespace) -> pd.Timestamp | None:
    if not args.as_of:
        return None
    ts = pd.Timestamp(args.as_of)
    return ts.tz_localize(scanner_config.TIMEZONE) if ts.tzinfo is None else ts.tz_convert(scanner_config.TIMEZONE)


def run_build(args: argparse.Namespace) -> int:
    payload = build_records(_tickers(args), as_of=_as_of(args), use_cache=not args.no_cache)
    path = save_records(payload, Path(args.out) if args.out else None)
    print(json.dumps(payload["summary"], indent=1, default=str))
    print(f"records written: {path}")
    return 0


def run_evaluate(args: argparse.Namespace) -> int:
    payload = load_records(Path(args.out) if args.out else None)
    results = evaluate(payload)
    json_path, md_path = save_results(results)
    print(render_report(results))
    print(f"written: {json_path}, {md_path}")
    return 0 if results["verdict"]["passed"] else 3


def run_scan(args: argparse.Namespace) -> int:
    print(RESEARCH_BANNER)
    as_of = _as_of(args)
    rows = []
    for ticker in _tickers(args):
        try:
            data = load_ticker(ticker, as_of=as_of, use_cache=not args.no_cache)
        except Exception as exc:
            rows.append({"ticker": ticker, "status": f"load_failed: {exc}"})
            continue
        if data.full.empty:
            rows.append({"ticker": ticker, "status": "no_sessions"})
            continue
        triggers = scan_triggers(ticker, data.full, data.partial)
        last_session = data.full.index[-1]
        todays = [t for t in triggers if pd.Timestamp(t.session) == last_session]
        if not todays:
            rows.append({"ticker": ticker, "status": "no_trigger", "session": str(last_session.date())})
            continue
        for t in todays:
            rows.append(
                {
                    "ticker": ticker,
                    "status": "trigger",
                    "session": str(last_session.date()),
                    "kind": t.kind,
                    "direction": t.direction,
                    "entry": round(t.entry_price, 2),
                    "box": [round(t.box.bottom, 2), round(t.box.top, 2)],
                    "cost_basis": round(t.box.cost_basis, 2),
                    "structure_target": round(t.structure.level, 2) if t.structure.level else None,
                    "empty_space_score": t.empty_space_score,
                    "legs": [(leg.name, round(leg.level, 2), leg.weight) for leg in t.plan.legs],
                    "stop": (t.plan.stop_rule, round(t.plan.stop_level, 2)),
                    "tradeable": t.tradeable,
                    "reason": t.untradeable_reason,
                    "confirmed_24h": t.confirmed_24h if data.last_session_complete else "pending (24h candle still forming)",
                }
            )
    hits = [r for r in rows if r["status"] == "trigger"]
    for row in hits:
        print(json.dumps(row, default=str))
    print(f"{len(hits)} trigger(s) across {len(rows)} names")
    out = output_dir() / "latest_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"banner": RESEARCH_BANNER, "rows": rows}, indent=1, default=str), encoding="utf-8")
    print(f"written: {out}")
    return 0


def run_hash_inputs(args: argparse.Namespace) -> int:
    hashes = input_hashes(_tickers(args), as_of=_as_of(args))
    print(json.dumps(hashes, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    load_project_env()
    args = _parse(argv)
    if args.mode == "build":
        return run_build(args)
    if args.mode == "evaluate":
        return run_evaluate(args)
    if args.mode == "hash-inputs":
        return run_hash_inputs(args)
    return run_scan(args)


if __name__ == "__main__":
    sys.exit(main())
