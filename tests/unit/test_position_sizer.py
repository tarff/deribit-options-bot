"""Tests for position sizer with Half Kelly criterion."""

import pytest
from datetime import datetime, timezone

from src.risk.position_sizer import PositionSizer, SizingConfig
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def sizer_config() -> SizingConfig:
    """Create position sizer config."""
    return SizingConfig(
        max_position_pct=0.10,  # 10% max per position
        max_total_exposure_pct=0.30,  # 30% max total
        base_win_rate=0.65,
        base_avg_win=0.02,
        base_avg_loss=0.01,
        min_trade_amount=0.0,  # Disable guard for non-guard tests
    )


@pytest.fixture
def normal_metrics() -> MarketMetrics:
    """Normal market conditions (DVOL < 60)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def stressed_metrics() -> MarketMetrics:
    """Stressed market (60 <= DVOL < 80)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=68.0,
        iv_rank=0.75,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def extreme_metrics() -> MarketMetrics:
    """Extreme fear (DVOL >= 80)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        iv_rank=0.92,
        timestamp=datetime.now(timezone.utc),
    )


def test_half_kelly_calculation(sizer_config: SizingConfig) -> None:
    """Test Half Kelly formula: f* = (p - q/b) / 2."""
    sizer = PositionSizer(sizer_config)

    # win_rate=0.65, avg_win=0.02, avg_loss=0.01
    # kelly = 0.65 - (0.35 / 2.0) = 0.65 - 0.175 = 0.475
    # half_kelly = 0.475 / 2 = 0.2375
    # capped at 0.10
    result = sizer.calculate_kelly()

    assert result == pytest.approx(0.10, abs=0.001)  # Capped at max


def test_size_position_normal_market(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test full size in normal market conditions."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, normal_metrics, current_exposure=0.0)

    assert result.size_coins > 0
    assert result.size_pct <= sizer_config.max_position_pct
    assert result.regime_multiplier == 1.0
    assert result.approved is True


def test_size_position_stressed_market_50pct_reduction(
    sizer_config: SizingConfig,
    stressed_metrics: MarketMetrics,
) -> None:
    """Test 50% size reduction when DVOL 60-80."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, stressed_metrics, current_exposure=0.0)

    assert result.regime_multiplier == 0.5
    assert result.size_pct <= sizer_config.max_position_pct * 0.5
    assert result.approved is True


def test_size_position_extreme_market_blocked(
    sizer_config: SizingConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test undefined-risk position blocked when DVOL >= 80."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, extreme_metrics, current_exposure=0.0)

    assert result.approved is False
    assert result.size_coins == 0.0
    assert result.regime_multiplier == 0.0
    assert "extreme" in result.reason.lower()


def test_size_position_extreme_market_defined_risk_allowed(
    sizer_config: SizingConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test defined-risk position allowed at 0.5x when DVOL >= 80.

    IC has capped max loss via wings, so high DVOL doesn't increase risk
    beyond the spread width. Session 61 analysis shows DVOL 70-80 is the
    best IC environment: 100% win rate, Sharpe 20.00, 33% richer premiums.
    """
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(
        capital, extreme_metrics, current_exposure=0.0, is_defined_risk=True
    )

    assert result.approved is True
    assert result.size_coins > 0
    assert result.regime_multiplier == 0.5
    assert result.size_pct <= sizer_config.max_position_pct * 0.5


def test_size_position_respects_exposure_limit(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position reduced when near exposure limit."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    # Already at 25% exposure, limit is 30%
    result = sizer.size_position(capital, normal_metrics, current_exposure=0.25)

    # Can only add 5% more
    assert result.size_pct <= 0.05
    assert result.approved is True


def test_size_position_blocked_at_exposure_limit(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position blocked when at exposure limit."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    # Already at 30% exposure
    result = sizer.size_position(capital, normal_metrics, current_exposure=0.30)

    assert result.approved is False
    assert "exposure limit" in result.reason.lower()


def test_size_position_rejected_zero_capital(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position rejected when capital is zero."""
    sizer = PositionSizer(sizer_config)

    result = sizer.size_position(capital=0.0, metrics=normal_metrics, current_exposure=0.0)

    assert result.approved is False
    assert result.size_coins == 0.0
    assert "invalid capital" in result.reason.lower()


def test_size_position_rejected_negative_capital(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position rejected when capital is negative."""
    sizer = PositionSizer(sizer_config)

    result = sizer.size_position(capital=-50000.0, metrics=normal_metrics, current_exposure=0.0)

    assert result.approved is False
    assert result.size_coins == 0.0
    assert "invalid capital" in result.reason.lower()


def test_size_position_rejected_below_min_trade_amount(
    normal_metrics: MarketMetrics,
) -> None:
    """Test position rejected when calculated size < min_trade_amount.

    With low capital, sizer output rounds below Deribit's 0.1 ETH minimum.
    Should reject instead of letting order_executor floor up to 0.1
    (which would bypass risk management).
    """
    config = SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
        base_win_rate=0.65,
        base_avg_win=0.02,
        base_avg_loss=0.01,
        min_trade_amount=0.1,
    )
    sizer = PositionSizer(config)

    # $500 capital, 10% max = $50, at BTC=$97k → 0.0005 BTC (way below 0.1)
    result = sizer.size_position(capital=500.0, metrics=normal_metrics, current_exposure=0.0)

    assert result.approved is False
    assert result.size_coins == 0.0
    assert "below minimum trade" in result.reason.lower()


def test_size_position_approved_at_min_trade_amount(
    normal_metrics: MarketMetrics,
) -> None:
    """Test position approved when calculated size >= min_trade_amount."""
    config = SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
        base_win_rate=0.65,
        base_avg_win=0.02,
        base_avg_loss=0.01,
        min_trade_amount=0.1,
    )
    sizer = PositionSizer(config)

    # $100k capital, 10% max = $10k, at BTC=$97k → ~0.103 BTC (above 0.1)
    result = sizer.size_position(capital=100000.0, metrics=normal_metrics, current_exposure=0.0)

    assert result.approved is True
    assert result.size_coins >= 0.1
