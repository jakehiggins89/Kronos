"""Build the Potter v3 research index: every trigger the method would have read,
its simulated outcome at three hold lengths, and a same-day drift control.

Outputs live under ``<REPORT_DIR>/potter_v3/`` (resolved at call time), never in
the retired lab's report paths.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from .. import config as scanner_config
from . import sessions as S
from .boxes import Box, Structure
from .outcomes import Outcome, build_day_table, simulate
from .triggers import Leg, Plan, Trigger, scan_triggers

logger = logging.getLogger("scanner.potter_v3.pipeline")

HORIZONS = (1, 3, 5)
PRIMARY_HORIZON = 3
RECORDS_FILENAME = "records.json"
PLACEBO_SEED = 20260905


def output_dir() -> Path:
    return Path(scanner_config.REPORT_DIR) / "potter_v3"


def records_path() -> Path:
    return output_dir() / RECORDS_FILENAME


@dataclass
class TickerData:
    ticker: str
    intraday: pd.DataFrame
    full: pd.DataFrame
    partial: pd.DataFrame
    day_table: pd.DataFrame


def load_ticker(ticker: str, *, as_of: pd.Timestamp | None = None, use_cache: bool = True) -> TickerData:
    intraday = S.load_intraday_eth(ticker, as_of=as_of, use_cache=use_cache)
    full = S.drop_in_progress_session(S.build_eth_sessions(intraday), now=as_of)
    partial = S.build_partial_sessions(intraday)
    partial = partial[partial.index.isin(full.index)]
    return TickerData(ticker=ticker, intraday=intraday, full=full, partial=partial, day_table=build_day_table(intraday))


def _with_horizon(trigger: Trigger, horizon: int) -> Trigger:
    plan = Plan(legs=list(trigger.plan.legs), stop_rule=trigger.plan.stop_rule, stop_level=trigger.plan.stop_level, risk_pct=trigger.plan.risk_pct, horizon_sessions=horizon)
    return replace(trigger, plan=plan)


def simulate_all_horizons(trigger: Trigger, data: TickerData, horizons: tuple[int, ...] = HORIZONS) -> dict[str, Outcome]:
    return {f"h{h}": simulate(_with_horizon(trigger, h), data.full, data.day_table) for h in horizons}


def control_trigger(trigger: Trigger, control: TickerData) -> Trigger | None:
    """Same day, same direction, same percent geometry, on a name with no setup.

    The retirement record demands a same-day ticker-universe drift control:
    if arbitrary entries with this geometry do as well as the method's
    triggers, the box added nothing.
    """
    date = pd.Timestamp(trigger.session)
    if date not in control.partial.index or date not in control.full.index:
        return None
    entry = float(control.partial.loc[date, "Close"])
    if entry <= 0:
        return None
    ratio = entry / trigger.entry_price
    legs = [Leg(level=leg.level * ratio, weight=leg.weight, name=leg.name) for leg in trigger.plan.legs]
    plan = Plan(legs=legs, stop_rule=trigger.plan.stop_rule, stop_level=trigger.plan.stop_level * ratio, risk_pct=trigger.plan.risk_pct, horizon_sessions=trigger.plan.horizon_sessions)
    box = Box(start=trigger.box.start, end=trigger.box.end, length=trigger.box.length, top=trigger.box.top * ratio, bottom=trigger.box.bottom * ratio, top_waves=0, bottom_waves=0)
    structure = Structure(level=trigger.structure.level * ratio if trigger.structure.level is not None else None, kind="control_scaled", session=None, distance_pct=trigger.structure.distance_pct, space_over_height=trigger.structure.space_over_height)
    return replace(trigger, ticker=control.ticker, entry_price=entry, prev_close=float(control.full["Close"].shift(1).loc[date]) if date in control.full.index else entry, full_close=float(control.full.loc[date, "Close"]), box=box, structure=structure, plan=plan, extra={**trigger.extra, "control_of": trigger.ticker})


def _input_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_hashes(tickers: list[str], *, as_of: pd.Timestamp | None = None) -> dict[str, str]:
    """SHA-256 of each ticker's cached bar file; ``as_of`` is accepted for CLI symmetry."""
    out: dict[str, str] = {}
    for ticker in tickers:
        path = S.cache_path(ticker)
        out[ticker] = _input_hash(path) if path.exists() else "missing"
    return out


def build_records(
    tickers: list[str] | None = None,
    *,
    as_of: pd.Timestamp | None = None,
    use_cache: bool = True,
    horizons: tuple[int, ...] = HORIZONS,
    seed: int = PLACEBO_SEED,
    loader=load_ticker,
) -> dict:
    tickers = list(tickers or S.research_universe())
    data: dict[str, TickerData] = {}
    triggers: dict[str, list[Trigger]] = {}
    failures: dict[str, str] = {}
    for ticker in tickers:
        try:
            td = loader(ticker, as_of=as_of, use_cache=use_cache)
        except Exception as exc:  # one bad ticker must not sink the run
            failures[ticker] = f"{type(exc).__name__}: {exc}"
            logger.warning("potter_v3 load failed for %s: %s", ticker, exc)
            continue
        if td.full.empty or td.partial.empty:
            failures[ticker] = "no sessions"
            continue
        data[ticker] = td
        triggers[ticker] = scan_triggers(ticker, td.full, td.partial)

    trigger_dates: dict[str, set] = {t: {pd.Timestamp(x.session) for x in trig} for t, trig in triggers.items()}
    rng = random.Random(seed)
    records: list[dict] = []
    for ticker in tickers:
        if ticker not in data:
            continue
        td = data[ticker]
        for trigger in triggers[ticker]:
            outcomes = simulate_all_horizons(trigger, td, horizons)
            record = trigger.to_dict()
            record["outcomes"] = {key: out.to_dict() for key, out in outcomes.items()}
            record["control"] = None
            if trigger.tradeable and not trigger.overlapping:
                date = pd.Timestamp(trigger.session)
                candidates = [
                    c for c in tickers
                    if c != ticker and c in data and date not in trigger_dates.get(c, set())
                    and date in data[c].partial.index and date in data[c].full.index
                ]
                if candidates:
                    rng.seed(f"{seed}:{ticker}:{date.date()}")
                    control_name = rng.choice(sorted(candidates))
                    ctrl = control_trigger(trigger, data[control_name])
                    if ctrl is not None:
                        ctrl_out = simulate_all_horizons(ctrl, data[control_name], horizons)
                        record["control"] = {
                            "ticker": control_name,
                            "entry_price": ctrl.entry_price,
                            "outcomes": {key: out.to_dict() for key, out in ctrl_out.items()},
                        }
            records.append(record)

    summary = {
        "tickers_requested": len(tickers),
        "tickers_loaded": len(data),
        "failures": failures,
        "sessions": {t: int(len(td.full)) for t, td in data.items()},
        "first_session": min((str(td.full.index[0].date()) for td in data.values()), default=None),
        "last_session": max((str(td.full.index[-1].date()) for td in data.values()), default=None),
        "records": len(records),
        "by_kind": _count(records, "kind"),
        "tradeable_non_overlapping": sum(1 for r in records if r["tradeable"] and not r["overlapping"]),
        "resolved_primary": sum(1 for r in records if r["outcomes"].get(f"h{PRIMARY_HORIZON}", {}).get("resolved")),
        "controls": sum(1 for r in records if r["control"]),
        "horizons": list(horizons),
        "placebo_seed": seed,
        "as_of": (pd.Timestamp.now(tz=scanner_config.TIMEZONE) if as_of is None else pd.Timestamp(as_of)).isoformat(),
    }
    return {"summary": summary, "records": records}


def _count(records: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        value = str(record.get(key))
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def save_records(payload: dict, path: Path | None = None) -> Path:
    path = path or records_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return path


def load_records(path: Path | None = None) -> dict:
    path = path or records_path()
    return json.loads(path.read_text(encoding="utf-8"))
