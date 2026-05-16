from __future__ import annotations

from datetime import datetime
import logging
import pandas as pd
import yfinance as yf

from ..config import MAX_ATM_BID_ASK_SPREAD_PCT, MIN_ATM_OPEN_INTEREST
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

            bid = float(row["bid"])
            ask = float(row["ask"])
            oi = int(row.get("openInterest", 0))
            vol_val = row.get("volume", 0)
            volume = int(vol_val) if pd.notna(vol_val) else 0

            if bid <= 0:
                continue
            if ask <= bid:
                continue
            spread = _spread_pct(bid, ask)
            if spread > MAX_ATM_BID_ASK_SPREAD_PCT:
                continue
            if oi < MIN_ATM_OPEN_INTEREST:
                continue

            candidate = OptionsContractResult(
                passed=True,
                expiration=exp,
                dte=dte,
                contract_type=contract_type,
                strike=float(row["strike"]),
                bid=bid,
                ask=ask,
                midpoint=(bid + ask) / 2.0,
                spread_pct=spread,
                open_interest=oi,
                volume=volume,
                implied_volatility=float(row["impliedVolatility"]) if pd.notna(row.get("impliedVolatility")) else None,
                skip_reason=None,
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
