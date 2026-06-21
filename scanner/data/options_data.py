from __future__ import annotations

from datetime import datetime
import logging
import os
import pandas as pd
import yfinance as yf

from ..config import MAX_ATM_BID_ASK_SPREAD_PCT, MIN_ATM_OPEN_INTEREST
from .market_data import _alpaca_credentials, _alpaca_get
from ..utils.validation import OptionsContractResult


def _spread_pct(bid: float, ask: float) -> float:
    if ask <= 0:
        return 1.0
    return (ask - bid) / ask


def _pick_contract_row(chain_df: pd.DataFrame, underlying_price: float) -> pd.Series | None:
    if chain_df is None or chain_df.empty:
        return None
    df = chain_df.copy()
    df = df.dropna(subset=["strike", "bid", "ask", "openInterest"], how="any")
    if df.empty:
        return None
    df["dist"] = (df["strike"] - underlying_price).abs()
    df = df.sort_values(["dist", "openInterest"], ascending=[True, False])
    return df.iloc[0]


def _fetch_alpaca_option_snapshots(ticker: str, logger: logging.Logger) -> dict:
    key, secret = _alpaca_credentials()
    if not key or not secret:
        return {}
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    feed = os.getenv("ALPACA_OPTIONS_FEED", "indicative").strip().lower() or "indicative"
    snapshots: dict = {}
    page_token = None
    while True:
        params = {"feed": feed, "limit": 1000}
        if page_token:
            params["page_token"] = page_token
        response = _alpaca_get(
            f"https://data.alpaca.markets/v1beta1/options/snapshots/{ticker}",
            headers=headers,
            params=params,
            timeout=30,
            retries=3,
        )
        if response.status_code != 200:
            logger.warning("%s Alpaca options snapshot unavailable: %s", ticker, response.status_code)
            return {}
        payload = response.json()
        snapshots.update(payload.get("snapshots", {}) or {})
        page_token = payload.get("next_page_token")
        if not page_token:
            return snapshots


def _quote_age_minutes(timestamp) -> float | None:
    if not timestamp:
        return None
    try:
        quote_ts = pd.Timestamp(timestamp)
        if quote_ts.tzinfo is None:
            quote_ts = quote_ts.tz_localize("UTC")
        return max(0.0, float((pd.Timestamp.now(tz="UTC") - quote_ts.tz_convert("UTC")).total_seconds() / 60.0))
    except Exception:
        return None


def _relative_disagreement(first: float | None, second: float | None) -> float | None:
    if first is None or second is None or first <= 0 or second <= 0:
        return None
    return abs(first - second) / max(first, second)


def _options_quality(feed: str, quote_age: float | None, disagreement: float | None) -> float:
    quality = 1.0 if feed == "opra" else 0.6 if feed == "indicative" else 0.45
    if quote_age is None or quote_age > 30:
        quality -= 0.2
    if disagreement is not None:
        quality -= min(disagreement, 0.3)
    return round(max(0.0, min(1.0, quality)), 4)


def select_options_contract(
    ticker: str,
    direction: str,
    breakout_price: float,
    logger: logging.Logger,
    min_dte: int = 30,
    max_dte: int = 60,
) -> OptionsContractResult:
    try:
        yf_ticker = yf.Ticker(ticker)
        alpaca_snapshots = _fetch_alpaca_option_snapshots(ticker, logger)
        alpaca_feed = os.getenv("ALPACA_OPTIONS_FEED", "indicative").strip().lower() or "indicative"
        expirations = list(yf_ticker.options or [])
        if not expirations:
            return OptionsContractResult(False, None, None, None, None, None, None, None, None, None, None, None, "empty options chain")

        today = pd.Timestamp.now().date()
        valid_exp = []
        for exp in expirations:
            exp_dt = pd.Timestamp(exp).date()
            dte = (exp_dt - today).days
            if min_dte <= dte <= max_dte:
                valid_exp.append((exp, dte))

        if not valid_exp:
            return OptionsContractResult(False, None, None, None, None, None, None, None, None, None, None, None, "no expirations in 30-60 DTE")

        contract_type = "call" if direction == "bullish" else "put"

        best: OptionsContractResult | None = None
        for exp, dte in valid_exp:
            chain = yf_ticker.option_chain(exp)
            chain_df = chain.calls if contract_type == "call" else chain.puts
            row = _pick_contract_row(chain_df, breakout_price)
            if row is None:
                continue

            yf_bid = float(row["bid"])
            yf_ask = float(row["ask"])
            contract_symbol = str(row.get("contractSymbol", ""))
            snapshot = alpaca_snapshots.get(contract_symbol, {}) if contract_symbol else {}
            quote = snapshot.get("latestQuote", {}) or {}
            alpaca_bid = float(quote.get("bp", 0.0) or 0.0)
            alpaca_ask = float(quote.get("ap", 0.0) or 0.0)
            has_alpaca_quote = alpaca_bid > 0 and alpaca_ask > alpaca_bid
            bid = alpaca_bid if has_alpaca_quote else yf_bid
            ask = alpaca_ask if has_alpaca_quote else yf_ask
            oi = int(row.get("openInterest", 0))
            vol_val = row.get("volume", 0)
            yf_volume = int(vol_val) if pd.notna(vol_val) else 0
            alpaca_volume = int((snapshot.get("dailyBar", {}) or {}).get("v", 0) or 0)
            volume = max(yf_volume, alpaca_volume)

            if bid <= 0:
                continue
            if ask <= bid:
                continue
            spread = _spread_pct(bid, ask)
            if spread > MAX_ATM_BID_ASK_SPREAD_PCT:
                continue
            if oi < MIN_ATM_OPEN_INTEREST:
                continue

            yf_midpoint = (yf_bid + yf_ask) / 2.0 if yf_bid > 0 and yf_ask > yf_bid else None
            midpoint = (bid + ask) / 2.0
            disagreement = _relative_disagreement(midpoint, yf_midpoint) if has_alpaca_quote else None
            quote_age = _quote_age_minutes(quote.get("t")) if has_alpaca_quote else None
            data_feed = alpaca_feed if has_alpaca_quote else "yfinance"
            candidate = OptionsContractResult(
                passed=True,
                expiration=exp,
                dte=dte,
                contract_type=contract_type,
                strike=float(row["strike"]),
                bid=bid,
                ask=ask,
                midpoint=midpoint,
                spread_pct=spread,
                open_interest=oi,
                volume=volume,
                implied_volatility=(
                    float(snapshot["impliedVolatility"])
                    if snapshot.get("impliedVolatility") is not None
                    else float(row["impliedVolatility"])
                    if pd.notna(row.get("impliedVolatility"))
                    else None
                ),
                skip_reason=None,
                data_provider="alpaca+yfinance" if has_alpaca_quote else "yfinance",
                data_feed=data_feed,
                quote_source="alpaca" if has_alpaca_quote else "yfinance",
                open_interest_source="yfinance",
                quote_timestamp=quote.get("t") if has_alpaca_quote else None,
                quote_age_minutes=quote_age,
                greeks_available=bool(snapshot.get("greeks")) if has_alpaca_quote else False,
                source_disagreement_pct=disagreement,
                options_data_quality=_options_quality(data_feed, quote_age, disagreement),
            )
            best = candidate
            break

        if best is None:
            return OptionsContractResult(
                passed=False,
                expiration=None,
                dte=None,
                contract_type=contract_type,
                strike=None,
                bid=None,
                ask=None,
                midpoint=None,
                spread_pct=None,
                open_interest=None,
                volume=None,
                implied_volatility=None,
                skip_reason=(
                    f"no {contract_type} contract passed: bid>0, ask>bid, "
                    f"spread<={MAX_ATM_BID_ASK_SPREAD_PCT:.0%}, OI>={MIN_ATM_OPEN_INTEREST}"
                ),
            )

        return best
    except Exception as exc:
        logger.error("%s options error: %s", ticker, exc)
        return OptionsContractResult(
            passed=False,
            expiration=None,
            dte=None,
            contract_type="call" if direction == "bullish" else "put",
            strike=None,
            bid=None,
            ask=None,
            midpoint=None,
            spread_pct=None,
            open_interest=None,
            volume=None,
            implied_volatility=None,
            skip_reason=f"options lookup error: {exc}",
        )
