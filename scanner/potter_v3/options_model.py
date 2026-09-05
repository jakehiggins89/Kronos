"""Option-contract outcome model for Potter v3.

The method is traded through calls and puts, and its own performance
language ("up 130% on the contract") is contract return. The retired index
measured the stock path only, so every expectancy it reported was for a
trade nobody in the method takes. This module marks a plausible contract
along the realised stock path so the research index can carry BOTH numbers.

Honesty notes, because they bound what the model can claim:
- Black-Scholes with a CONSTANT volatility per trade. There is no two-year
  implied-volatility history in this project, so sigma is realised
  volatility over a trailing window times a configurable premium multiple.
  Vega P&L (IV crush or expansion) is therefore not modelled; the number is
  a delta/gamma/theta approximation, not a fill.
- No bid/ask: a spread haircut (bps of premium, both sides) stands in for it.
- Strikes snap to a plausible listed increment; the live chain may differ.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

RISK_FREE_RATE = 0.04
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.0


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(
    spot: float,
    strike: float,
    years_to_expiry: float,
    sigma: float,
    option_type: str,
    rate: float = RISK_FREE_RATE,
) -> float:
    """European option price. Degenerate inputs fall back to intrinsic value."""
    if spot <= 0 or strike <= 0:
        return 0.0
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    if years_to_expiry <= 0 or sigma <= 0:
        return intrinsic
    vol_sqrt_t = sigma * math.sqrt(years_to_expiry)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years_to_expiry) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    discount = math.exp(-rate * years_to_expiry)
    if option_type == "call":
        price = spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    else:
        price = strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return max(price, intrinsic, 0.0)


def black_scholes_delta(
    spot: float,
    strike: float,
    years_to_expiry: float,
    sigma: float,
    option_type: str,
    rate: float = RISK_FREE_RATE,
) -> float:
    if spot <= 0 or strike <= 0 or years_to_expiry <= 0 or sigma <= 0:
        if option_type == "call":
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    vol_sqrt_t = sigma * math.sqrt(years_to_expiry)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years_to_expiry) / vol_sqrt_t
    return norm_cdf(d1) if option_type == "call" else norm_cdf(d1) - 1.0


def strike_increment(spot: float) -> float:
    """Typical listed strike spacing for liquid US equity options."""
    if spot < 25:
        return 0.5
    if spot < 200:
        return 1.0
    return 5.0


def snap_strike(spot: float, *, offset_steps: int = 0) -> float:
    inc = strike_increment(spot)
    base = round(spot / inc) * inc
    return round(base + offset_steps * inc, 2)


def realized_volatility(closes: pd.Series, window: int = 20) -> float | None:
    """Annualised close-to-close realised volatility over the trailing window."""
    if closes is None or len(closes) < window + 1:
        return None
    rets = closes.astype(float).pct_change().dropna().tail(window)
    if len(rets) < window:
        return None
    std = float(rets.std(ddof=1))
    if not math.isfinite(std) or std <= 0:
        return None
    return std * math.sqrt(TRADING_DAYS_PER_YEAR)


@dataclass
class ContractSpec:
    option_type: str
    strike: float
    dte_calendar_days: int
    sigma: float
    entry_spot: float
    entry_premium: float
    entry_delta: float
    spread_bps_per_side: float = 0.0
    notes: dict = field(default_factory=dict)


def select_contract(
    direction: str,
    entry_spot: float,
    sigma: float | None,
    *,
    dte_calendar_days: int = 45,
    strike_offset_steps: int = 0,
    spread_bps_per_side: float = 0.0,
) -> ContractSpec | None:
    """Pick the modelled contract for a setup: a call for bullish, a put for bearish.

    A positive ``strike_offset_steps`` moves the strike out of the money in
    the direction of the trade; negative moves it in the money.
    """
    if direction not in {"bullish", "bearish"} or entry_spot <= 0 or sigma is None or sigma <= 0:
        return None
    option_type = "call" if direction == "bullish" else "put"
    sign = 1 if option_type == "call" else -1
    strike = snap_strike(entry_spot, offset_steps=sign * strike_offset_steps)
    years = dte_calendar_days / CALENDAR_DAYS_PER_YEAR
    premium = black_scholes_price(entry_spot, strike, years, sigma, option_type)
    if premium <= 0.01:
        return None
    delta = black_scholes_delta(entry_spot, strike, years, sigma, option_type)
    return ContractSpec(
        option_type=option_type,
        strike=strike,
        dte_calendar_days=int(dte_calendar_days),
        sigma=float(sigma),
        entry_spot=float(entry_spot),
        entry_premium=float(premium),
        entry_delta=float(delta),
        spread_bps_per_side=float(spread_bps_per_side),
    )


def mark_contract(spec: ContractSpec, spot: float, calendar_days_elapsed: float) -> float:
    years = max(spec.dte_calendar_days - calendar_days_elapsed, 0.0) / CALENDAR_DAYS_PER_YEAR
    return black_scholes_price(spot, spec.strike, years, spec.sigma, spec.option_type)


def contract_return_pct(spec: ContractSpec, spot: float, calendar_days_elapsed: float) -> float:
    """Percent return on the premium after the spread haircut on both sides."""
    if spec.entry_premium <= 0:
        return 0.0
    haircut = spec.spread_bps_per_side / 10_000.0
    paid = spec.entry_premium * (1.0 + haircut)
    received = mark_contract(spec, spot, calendar_days_elapsed) * (1.0 - haircut)
    return (received - paid) / paid * 100.0


def contract_path(spec: ContractSpec, path: pd.DataFrame, entry_timestamp: pd.Timestamp) -> pd.DataFrame:
    """Contract mark and return at each session close after entry.

    ``path`` holds the sessions AFTER entry (New York index). Time decay uses
    calendar days between the entry session and each later session.
    """
    if path is None or path.empty:
        return pd.DataFrame(columns=["spot", "days_elapsed", "mark", "return_pct"])
    rows = []
    entry_day = pd.Timestamp(entry_timestamp).normalize()
    for ts, row in path.iterrows():
        elapsed = (pd.Timestamp(ts).normalize() - entry_day).days
        spot = float(row["Close"])
        rows.append(
            {
                "spot": spot,
                "days_elapsed": float(elapsed),
                "mark": mark_contract(spec, spot, elapsed),
                "return_pct": contract_return_pct(spec, spot, elapsed),
            }
        )
    return pd.DataFrame(rows, index=path.index)


def select_contract_at_strike(
    direction: str,
    entry_spot: float,
    sigma: float | None,
    *,
    strike: float,
    dte_calendar_days: int = 10,
    spread_bps_per_side: float = 0.0,
    premium_floor: float = 0.0,
) -> ContractSpec | None:
    """The target-based contract he describes (R43): strike at the target level.

    ``premium_floor`` stands in for the minimum price a far out-of-the-money
    weekly actually trades at; a Black-Scholes premium below it is lifted to
    the floor and the spec notes it, so no contract is modelled as costing
    less than a real fill could.
    """
    if direction not in {"bullish", "bearish"} or entry_spot <= 0 or sigma is None or sigma <= 0 or strike <= 0:
        return None
    option_type = "call" if direction == "bullish" else "put"
    years = dte_calendar_days / CALENDAR_DAYS_PER_YEAR
    premium = black_scholes_price(entry_spot, strike, years, sigma, option_type)
    floored = False
    if premium < premium_floor:
        premium = premium_floor
        floored = True
    if premium <= 0.0:
        return None
    delta = black_scholes_delta(entry_spot, strike, years, sigma, option_type)
    return ContractSpec(
        option_type=option_type,
        strike=float(strike),
        dte_calendar_days=int(dte_calendar_days),
        sigma=float(sigma),
        entry_spot=float(entry_spot),
        entry_premium=float(premium),
        entry_delta=float(delta),
        spread_bps_per_side=float(spread_bps_per_side),
        notes={"premium_floored": floored, "strike_rule": "target_based"},
    )
