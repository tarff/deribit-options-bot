"""Volatility calculations for market analysis."""

import math
from typing import Optional

import numpy as np


def calculate_realized_volatility(
    prices: list[float],
    annualize: bool = True,
    periods_per_year: int = 365,
) -> Optional[float]:
    """Calculate realized volatility from price series.

    Uses log returns and standard deviation method.

    Args:
        prices: List of prices (oldest first).
        annualize: Whether to annualize the result.
        periods_per_year: Number of periods per year (365 for daily).

    Returns:
        Realized volatility as percentage (e.g., 45.0 for 45%), or None if insufficient data.
    """
    if len(prices) < 2:
        return None

    # Validate all prices are positive (log returns require p > 0)
    if any(p <= 0 for p in prices):
        return None

    # Calculate log returns
    prices_array = np.array(prices)
    log_returns = np.diff(np.log(prices_array))

    # Calculate standard deviation of returns
    daily_vol = float(np.std(log_returns, ddof=1))

    if annualize:
        return annualize_volatility(daily_vol, periods_per_year)

    return daily_vol * 100


def annualize_volatility(
    periodic_vol: float,
    periods_per_year: int = 365,
) -> float:
    """Annualize a periodic volatility figure.

    Args:
        periodic_vol: Volatility for one period (as decimal, e.g., 0.01 for 1%).
        periods_per_year: Number of periods per year.

    Returns:
        Annualized volatility as percentage.
    """
    return periodic_vol * math.sqrt(periods_per_year) * 100


def calculate_iv_rank(
    current_iv: float,
    historical_iv: list[float],
) -> Optional[float]:
    """Calculate IV Rank (current IV position in historical range).

    IV Rank = (Current IV - Low) / (High - Low)

    Note: We use 252-day (1 year) lookback, which differs from Deribit's ~90-day.
    Analysis in scripts/analyze_strategy_thresholds.py (2026-01-23) showed:
        - 252-day: Better forward returns (+1.24% vs +1.16%)
        - 252-day: Higher avg DVOL at 30% threshold (50.7 vs 47.9)
        - 252-day: Tighter range, more consistent signal quality
    The 90-day lookback can trigger at DVOL as low as 35.9, which provides
    less premium for selling strategies.

    Args:
        current_iv: Current implied volatility.
        historical_iv: Historical IV values (recommend 252 days for trading).

    Returns:
        IV Rank as decimal (0.0 to 1.0), or None if insufficient data.
    """
    if len(historical_iv) < 2:
        return None

    iv_min = min(historical_iv)
    iv_max = max(historical_iv)

    if (iv_max - iv_min) < 1e-6:
        return 0.5  # No meaningful range, return middle

    return (current_iv - iv_min) / (iv_max - iv_min)


def calculate_iv_percentile(
    current_iv: float,
    historical_iv: list[float],
) -> Optional[float]:
    """Calculate IV Percentile (% of historical readings below current).

    Args:
        current_iv: Current implied volatility.
        historical_iv: Historical IV values.

    Returns:
        IV Percentile as decimal (0.0 to 1.0), or None if insufficient data.
    """
    if not historical_iv:
        return None

    count_below = sum(1 for iv in historical_iv if iv < current_iv)
    return count_below / len(historical_iv)


def calculate_term_structure_ratio(
    near_term_iv: float,
    far_term_iv: float,
) -> Optional[float]:
    """Calculate term structure ratio.

    Ratio = IV(near-term) / IV(far-term)
    - > 1.10: Backwardation (near-term stress)
    - < 0.95: Contango (normal market)
    - 0.95-1.05: Flat

    Args:
        near_term_iv: IV for near-term expiry (e.g., 30 DTE ATM).
        far_term_iv: IV for far-term expiry (e.g., 90 DTE ATM).

    Returns:
        Term structure ratio, or None if far_term_iv is zero.
    """
    if far_term_iv <= 0:
        return None

    return near_term_iv / far_term_iv


def calculate_risk_reversal_skew(
    call_iv_25d: float,
    put_iv_25d: float,
) -> float:
    """Calculate risk reversal skew.

    RR Skew = 25-delta Call IV - 25-delta Put IV
    - > +3: Call skew (bullish sentiment)
    - < -3: Put skew (bearish sentiment)

    Args:
        call_iv_25d: 25-delta call implied volatility.
        put_iv_25d: 25-delta put implied volatility.

    Returns:
        Risk reversal skew in volatility points.
    """
    return call_iv_25d - put_iv_25d
