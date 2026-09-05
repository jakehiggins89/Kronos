"""24-hour extended-hours session bars for the Potter v3 research path.

The method is read off a TradingView "24h" chart with extended trading hours
on: one candle per trading date spanning 04:00-20:00 ET. The retired index
used regular-session daily bars (``prepost=False``), so its box levels were
not the levels the method draws. This module builds the right candle from
Alpaca's SIP 30-minute bars (which cover 04:00-19:30 ET, two years back,
split-adjusted) and caches the raw intraday frame per ticker per day so a
research run never re-downloads the universe.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pandas as pd

from .. import config as scanner_config
from ..data.market_data import fetch_intraday_bars
from ..data.synthetic_sessions import build_synthetic_sessions

logger = logging.getLogger("scanner.potter_v3.sessions")

CACHE_DIR_NAME = "potter_v3_cache"
INTRADAY_INTERVAL = "30m"
INTRADAY_DAYS = 740
# 04:00 ET is the pre-market open. Anchoring there labels each session with
# its own trading date (a bar at 19:30 on the 12th belongs to the 12th),
# matching how the chart labels the candle.
ETH_ANCHOR_HOUR = 4
ETH_ANCHOR_MINUTE = 0
# A session whose last bar starts before this ET time is still forming.
SESSION_COMPLETE_HOUR = 19
SESSION_COMPLETE_MINUTE = 30
EXTENDED_SESSION_START = (4, 0)
EXTENDED_SESSION_END = (20, 0)


def cache_dir() -> Path:
    # Resolved at call time so the test suite's REPORT_DIR isolation applies.
    return Path(scanner_config.REPORT_DIR) / CACHE_DIR_NAME


def cache_path(ticker: str) -> Path:
    return cache_dir() / f"{ticker.upper()}_{INTRADAY_INTERVAL}.pkl"


def _now(as_of: pd.Timestamp | None) -> pd.Timestamp:
    now = pd.Timestamp.now(tz=scanner_config.TIMEZONE) if as_of is None else pd.Timestamp(as_of)
    return now.tz_localize(scanner_config.TIMEZONE) if now.tzinfo is None else now.tz_convert(scanner_config.TIMEZONE)


def _fetch(ticker: str, days: int, now: pd.Timestamp) -> pd.DataFrame:
    df = fetch_intraday_bars(
        ticker,
        interval=INTRADAY_INTERVAL,
        period=f"{days}d",
        research=True,
        now=now,
        adjustment="split",
    )
    # Two years of extended-hours 30-minute bars only exist on the Alpaca
    # route. Yahoo caps intraday history at 60 days, so a fallback there would
    # quietly hand back a truncated or empty frame; refuse instead of
    # pretending. Credentials come from scanner/.env (load it first).
    if df.attrs.get("data_provider") != "alpaca":
        raise RuntimeError(
            f"{ticker}: Potter v3 extended-hours bars require the Alpaca SIP route "
            f"(got provider={df.attrs.get('data_provider')!r}); check ALPACA_API_KEY/ALPACA_SECRET_KEY in scanner/.env"
        )
    return _clean_intraday(df)


def load_intraday_eth(
    ticker: str,
    *,
    days: int = INTRADAY_DAYS,
    as_of: pd.Timestamp | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Raw 30-minute extended-hours bars, New York index, split-adjusted.

    Uses the research (delayed SIP) route so the bars are consolidated tape,
    never the IEX slice. One cache file per ticker; a later call fetches only
    the bars after the cached tail (with a two-day overlap for corrections),
    so a daily run costs one small request per name. ``as_of`` truncates the
    result to bars at or before that time, which makes a research build
    reproducible against a cache that has since grown.
    """
    now = _now(as_of)
    window_start = now - pd.Timedelta(days=days)
    path = cache_path(ticker)
    cached: pd.DataFrame | None = None
    if use_cache and path.exists():
        with path.open("rb") as fh:
            loaded = pickle.load(fh)
        if isinstance(loaded, pd.DataFrame) and not loaded.empty:
            cached = loaded

    if cached is None:
        frame = _fetch(ticker, days, now)
    else:
        last = pd.Timestamp(cached.index[-1])
        frame = cached
        complete_minute = SESSION_COMPLETE_HOUR * 60 + SESSION_COMPLETE_MINUTE
        last_session_done = last.hour * 60 + last.minute >= complete_minute
        newer_day = now.normalize() > last.normalize()
        same_day_stale = (not last_session_done) and (now - last > pd.Timedelta(hours=1))
        if newer_day or same_day_stale:
            tail_days = max(1, int((now - last).days) + 2)
            tail = _fetch(ticker, tail_days, now)
            if not tail.empty:
                frame = pd.concat([cached, tail])
                frame = frame[~frame.index.duplicated(keep="last")].sort_index()
                frame.attrs.update(tail.attrs)
    frame = frame[frame.index >= window_start]
    if use_cache and not frame.empty and (cached is None or len(frame) != len(cached) or frame.index[-1] != cached.index[-1]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(frame, fh)
    if as_of is not None:
        frame = frame[frame.index <= now]
    return frame


def _clean_intraday(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    out = df.copy().sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    minute = out.index.hour * 60 + out.index.minute
    start = EXTENDED_SESSION_START[0] * 60 + EXTENDED_SESSION_START[1]
    end = EXTENDED_SESSION_END[0] * 60 + EXTENDED_SESSION_END[1]
    out = out[(minute >= start) & (minute < end)]
    bad = (out["High"] < out["Low"]) | (out["Low"] <= 0)
    if bad.any():
        out = out[~bad]
    out.attrs.update(df.attrs)
    return out


def build_eth_sessions(intraday: pd.DataFrame) -> pd.DataFrame:
    """One 04:00-20:00 ET candle per trading date from 30-minute bars."""
    if intraday is None or intraday.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    sessions, diagnostics = build_synthetic_sessions(
        intraday,
        ETH_ANCHOR_HOUR,
        ETH_ANCHOR_MINUTE,
        INTRADAY_INTERVAL,
        prepost_enabled=True,
    )
    if sessions.empty:
        return sessions
    last_bar = intraday.groupby(intraday.index.normalize()).apply(lambda g: g.index.max())
    sessions.index = sessions.index.normalize()
    sessions["session_last_bar"] = last_bar.reindex(sessions.index)
    sessions["bar_count"] = intraday.groupby(intraday.index.normalize()).size().reindex(sessions.index).fillna(0).astype(int)
    sessions.attrs.update(intraday.attrs)
    sessions.attrs["session_diagnostics"] = diagnostics
    sessions.attrs["session_kind"] = "eth_24h"
    return sessions


def drop_in_progress_session(sessions: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the last session if the extended session has not ended yet.

    Completion is judged by the clock (20:00 ET has passed), not by whether a
    19:30 bar printed: thin names often show no prints in the last half hour
    and must not lose their whole day for it.
    """
    if sessions is None or sessions.empty:
        return sessions
    current = _now(now)
    last_date = pd.Timestamp(sessions.index[-1])
    session_end = last_date.normalize() + pd.Timedelta(hours=EXTENDED_SESSION_END[0], minutes=EXTENDED_SESSION_END[1])
    if current < session_end:
        return sessions.iloc[:-1]
    return sessions


def resample_eth(intraday: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Lower-timeframe extended-hours candles (e.g. "1h", "4h") aligned to 04:00 ET.

    Midnight-origin bins of 1h/2h/4h all land on 04:00, 08:00, 12:00, 16:00,
    so the 4h candles match the chart's extended-session 4h bars.
    """
    if intraday is None or intraday.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    out = intraday.resample(rule, origin="start_day", closed="left", label="left").agg(agg)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out.attrs.update(intraday.attrs)
    out.attrs["session_kind"] = f"eth_{rule}"
    return out


def load_eth_sessions(
    ticker: str,
    *,
    days: int = INTRADAY_DAYS,
    as_of: pd.Timestamp | None = None,
    use_cache: bool = True,
    drop_partial: bool = True,
) -> pd.DataFrame:
    intraday = load_intraday_eth(ticker, days=days, as_of=as_of, use_cache=use_cache)
    sessions = build_eth_sessions(intraday)
    if drop_partial:
        sessions = drop_in_progress_session(sessions, now=as_of)
    return sessions


def research_universe() -> list[str]:
    seen: list[str] = []
    for symbol in list(scanner_config.DEFAULT_WATCHLIST) + list(scanner_config.EDGE_INDEX_EXTRA_UNIVERSE):
        if symbol not in seen:
            seen.append(symbol)
    return seen


RTH_OPEN = (9, 30)
RTH_CLOSE = (16, 0)


def _minute_of_day(index: pd.DatetimeIndex) -> pd.Index:
    return index.hour * 60 + index.minute


def build_partial_sessions(intraday: pd.DataFrame, cutoff: tuple[int, int] = RTH_CLOSE) -> pd.DataFrame:
    """The 24h candle as it looks at the cutoff time (default 16:00 ET).

    He reads the signal and buys at 3:50-4:15 pm while the extended-hours
    candle is still forming (R21). This is that candle: bars from 04:00 up to
    the cutoff, so the close is the regular-session close.
    """
    if intraday is None or intraday.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    limit = cutoff[0] * 60 + cutoff[1]
    early = intraday[_minute_of_day(intraday.index) < limit]
    sessions = build_eth_sessions(early)
    sessions.attrs["session_kind"] = f"eth_partial_{cutoff[0]:02d}{cutoff[1]:02d}"
    return sessions


def rth_bars(intraday: pd.DataFrame) -> pd.DataFrame:
    """Regular-session bars only (09:30-16:00 ET), where options can actually be traded."""
    if intraday is None or intraday.empty:
        return intraday
    minute = _minute_of_day(intraday.index)
    return intraday[(minute >= RTH_OPEN[0] * 60 + RTH_OPEN[1]) & (minute < RTH_CLOSE[0] * 60 + RTH_CLOSE[1])]
