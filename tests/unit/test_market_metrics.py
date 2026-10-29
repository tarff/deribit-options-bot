"""Tests for MarketMetrics data class."""

from datetime import datetime, timezone

from src.data.market_metrics import MarketMetrics


def test_market_metrics_creation() -> None:
    """Test creating MarketMetrics with all fields."""
    metrics = MarketMetrics(
        btc_price=97432.50,
        dvol=52.3,
        iv_rank=0.67,
        iv_percentile=0.72,
        rv_7d=48.2,
        rv_30d=45.1,
        iv_rv_spread=7.2,
        term_structure_ratio=1.05,
        rr_skew=-2.1,
        timestamp=datetime.now(timezone.utc),
    )

    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank == 0.67


def test_market_metrics_iv_rv_spread_property() -> None:
    """Test IV-RV spread calculation."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=55.0,
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )

    # IV-RV spread should be dvol - rv_30d = 10.0
    assert metrics.calculated_iv_rv_spread == 10.0


def test_market_metrics_defaults() -> None:
    """Test MarketMetrics with minimal required fields."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert metrics.dvol is None
    assert metrics.iv_rank is None
    assert metrics.rv_7d is None


def test_market_metrics_is_high_iv() -> None:
    """Test high IV detection helper."""
    high_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.67,
        iv_rv_spread=16.0,
        timestamp=datetime.now(timezone.utc),
    )
    low_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.25,
        iv_rv_spread=5.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert high_iv.is_high_iv is True
    assert low_iv.is_high_iv is False


def test_market_metrics_is_low_iv() -> None:
    """Test low IV detection helper."""
    low_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.20,
        iv_rv_spread=-12.0,
        timestamp=datetime.now(timezone.utc),
    )
    high_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.67,
        iv_rv_spread=16.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert low_iv.is_low_iv is True
    assert high_iv.is_low_iv is False