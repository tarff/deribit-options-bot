"""Tests for market regime detection."""

import pytest
from datetime import datetime, timezone

from src.data.market_metrics import MarketMetrics
from src.brain.regime_detector import MarketRegime, RegimeDetector


@pytest.fixture
def detector() -> RegimeDetector:
    """Create regime detector with default thresholds."""
    return RegimeDetector()


def test_high_dvol_without_iv_conditions_is_neutral(detector: RegimeDetector) -> None:
    """Test high DVOL without IV conditions falls to NEUTRAL (not EXTREME_FEAR).

    Regime detector no longer triggers EXTREME_FEAR on DVOL alone.
    DVOL-based risk is handled by PositionSizer (0.0x for undefined-risk,
    0.5x for defined-risk like IC).
    """
    metrics = MarketMetrics(
        btc_price=90000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    # No IV rank or spread data -> can't match HIGH_IV_OVERPRICED -> NEUTRAL
    assert regime == MarketRegime.NEUTRAL


def test_regime_high_iv_overpriced(detector: RegimeDetector) -> None:
    """Test HIGH_IV_OVERPRICED when IV Rank > 50% and spread > 15."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=55.0,
        iv_rank=0.65,
        iv_rv_spread=18.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.HIGH_IV_OVERPRICED


def test_regime_low_iv_underpriced(detector: RegimeDetector) -> None:
    """Test LOW_IV_UNDERPRICED when IV Rank < 30% and spread < -10."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=35.0,
        iv_rank=0.20,
        iv_rv_spread=-12.0,
        rv_7d=48.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.LOW_IV_UNDERPRICED


def test_regime_volatile_fair(detector: RegimeDetector) -> None:
    """Test VOLATILE_FAIR when RV(7d) > RV(30d) * 1.3 and spread near zero."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        rv_7d=60.0,
        rv_30d=42.0,  # 60 > 42 * 1.3 = 54.6
        iv_rv_spread=3.0,  # Near zero (< 5)
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.VOLATILE_FAIR


def test_regime_neutral_default(detector: RegimeDetector) -> None:
    """Test NEUTRAL when no other conditions match."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        rv_7d=45.0,
        rv_30d=43.0,
        iv_rv_spread=5.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.NEUTRAL


def test_high_dvol_with_iv_conditions_is_high_iv_overpriced(detector: RegimeDetector) -> None:
    """Test high DVOL with IV conditions correctly detects HIGH_IV_OVERPRICED.

    Previously this would be EXTREME_FEAR (DVOL > 80 overrode everything).
    Now regime detector classifies market conditions, and PositionSizer
    handles DVOL-based risk policy.
    """
    metrics = MarketMetrics(
        btc_price=85000.0,
        dvol=90.0,  # Very high DVOL
        iv_rank=0.95,  # High IV rank -> IC should sell premium
        iv_rv_spread=25.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    # High IV rank + positive spread = sell premium via IC
    assert regime == MarketRegime.HIGH_IV_OVERPRICED


def test_get_recommended_strategy_extreme_fear(detector: RegimeDetector) -> None:
    """Test no strategy recommended during extreme fear."""
    recommendation = detector.get_recommendation(MarketRegime.EXTREME_FEAR)

    assert recommendation.strategy is None
    assert recommendation.action == "close_all"
    assert "halt" in recommendation.reason.lower()


def test_get_recommended_strategy_high_iv(detector: RegimeDetector) -> None:
    """Test iron condor recommended for high IV."""
    recommendation = detector.get_recommendation(MarketRegime.HIGH_IV_OVERPRICED)

    assert recommendation.strategy == "iron_condor"
    assert recommendation.size_multiplier == 1.0


def test_get_recommended_strategy_neutral(detector: RegimeDetector) -> None:
    """Test calendar spread strategy for neutral regime."""
    recommendation = detector.get_recommendation(MarketRegime.NEUTRAL)

    assert recommendation.strategy == "calendar_spread"
    assert recommendation.size_multiplier == 1.0
