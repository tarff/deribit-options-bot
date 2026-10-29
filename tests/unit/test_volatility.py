"""Tests for volatility calculations."""

import pytest

from src.data.volatility import (
    calculate_realized_volatility,
    annualize_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
    calculate_term_structure_ratio,
    calculate_risk_reversal_skew,
)


def test_calculate_realized_volatility_from_prices() -> None:
    """Test RV calculation from daily close prices."""
    # 7 days of prices with ~1% daily moves
    prices = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.5]

    rv = calculate_realized_volatility(prices)

    # Should be roughly 15-20% annualized for ~1% daily moves
    assert 10.0 < rv < 30.0


def test_calculate_realized_volatility_flat_prices() -> None:
    """Test RV is near zero for flat prices."""
    prices = [100.0, 100.0, 100.0, 100.0, 100.0]

    rv = calculate_realized_volatility(prices)

    assert rv < 1.0  # Near zero


def test_calculate_realized_volatility_insufficient_data() -> None:
    """Test RV returns None with insufficient data."""
    prices = [100.0]  # Need at least 2 prices

    rv = calculate_realized_volatility(prices)

    assert rv is None


def test_annualize_volatility() -> None:
    """Test annualization of daily volatility."""
    daily_vol = 0.01  # 1% daily

    annual_vol = annualize_volatility(daily_vol, periods_per_year=365)

    # sqrt(365) * 0.01 ≈ 0.191 (19.1%)
    assert 18.0 < annual_vol < 20.0


def test_calculate_iv_rank() -> None:
    """Test IV Rank calculation (current vs 52-week high/low)."""
    # 52 weeks of DVOL data
    historical_iv = [40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0]  # min=40, max=70
    current_iv = 55.0

    iv_rank = calculate_iv_rank(current_iv, historical_iv)

    # (55 - 40) / (70 - 40) = 15/30 = 0.50
    assert iv_rank == pytest.approx(0.50, abs=0.01)


def test_calculate_iv_rank_at_extremes() -> None:
    """Test IV Rank at min and max."""
    historical_iv = [40.0, 50.0, 60.0]

    assert calculate_iv_rank(40.0, historical_iv) == pytest.approx(0.0)
    assert calculate_iv_rank(60.0, historical_iv) == pytest.approx(1.0)


def test_calculate_iv_rank_insufficient_data() -> None:
    """Test IV Rank returns None with no historical data."""
    assert calculate_iv_rank(50.0, []) is None
    assert calculate_iv_rank(50.0, [50.0]) is None  # Need range


def test_calculate_iv_percentile() -> None:
    """Test IV Percentile (% of days below current)."""
    historical_iv = [40.0, 45.0, 50.0, 55.0, 60.0]
    current_iv = 52.0

    percentile = calculate_iv_percentile(current_iv, historical_iv)

    # 3 out of 5 values are below 52 = 60%
    assert percentile == pytest.approx(0.60, abs=0.01)


def test_calculate_term_structure_ratio_backwardation() -> None:
    """Test term structure in backwardation (near > far)."""
    near_term_iv = 55.0  # 30 DTE
    far_term_iv = 50.0   # 90 DTE

    ratio = calculate_term_structure_ratio(near_term_iv, far_term_iv)

    # 55/50 = 1.10 (backwardation)
    assert ratio == pytest.approx(1.10, abs=0.01)


def test_calculate_term_structure_ratio_contango() -> None:
    """Test term structure in contango (far > near)."""
    near_term_iv = 48.0
    far_term_iv = 52.0

    ratio = calculate_term_structure_ratio(near_term_iv, far_term_iv)

    # 48/52 = 0.923 (contango)
    assert ratio == pytest.approx(0.923, abs=0.01)


def test_calculate_term_structure_zero_far() -> None:
    """Test term structure handles zero far-term IV."""
    assert calculate_term_structure_ratio(50.0, 0.0) is None


def test_calculate_risk_reversal_skew_call_skew() -> None:
    """Test RR skew when calls are expensive (bullish)."""
    call_iv_25d = 52.0
    put_iv_25d = 48.0

    skew = calculate_risk_reversal_skew(call_iv_25d, put_iv_25d)

    # 52 - 48 = +4 (call skew, bullish)
    assert skew == pytest.approx(4.0, abs=0.01)


def test_calculate_risk_reversal_skew_put_skew() -> None:
    """Test RR skew when puts are expensive (bearish)."""
    call_iv_25d = 48.0
    put_iv_25d = 55.0

    skew = calculate_risk_reversal_skew(call_iv_25d, put_iv_25d)

    # 48 - 55 = -7 (put skew, bearish)
    assert skew == pytest.approx(-7.0, abs=0.01)
