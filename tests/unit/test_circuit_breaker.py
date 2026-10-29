"""Tests for circuit breaker."""

import pytest
from datetime import datetime, timezone, timedelta

from src.risk.circuit_breaker import (
    CircuitBreaker,
    BreakerConfig,
    BreakerStatus,
)
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def breaker_config() -> BreakerConfig:
    """Create circuit breaker config."""
    return BreakerConfig(
        daily_loss_limit_pct=0.05,
        dvol_halt_threshold=80.0,
        dvol_resume_threshold=70.0,
        api_error_threshold=3,
        api_error_window_seconds=300,
        cooldown_hours=24,
    )


def test_initial_status_active(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker starts in active state."""
    breaker = CircuitBreaker(breaker_config)

    assert breaker.status == BreakerStatus.ACTIVE
    assert breaker.can_trade() is True


def test_trip_on_daily_loss(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on daily loss."""
    breaker = CircuitBreaker(breaker_config)

    event = breaker.check_daily_loss(
        daily_pnl=-5500.0,
        capital=100000.0,
    )

    assert event is not None
    assert event.trigger == "daily_loss"
    assert breaker.status == BreakerStatus.TRIPPED
    assert breaker.can_trade() is False


def test_no_trip_within_daily_loss_limit(breaker_config: BreakerConfig) -> None:
    """Test no trip when within daily loss limit."""
    breaker = CircuitBreaker(breaker_config)

    event = breaker.check_daily_loss(
        daily_pnl=-4000.0,  # -4%, under 5% limit
        capital=100000.0,
    )

    assert event is None
    assert breaker.status == BreakerStatus.ACTIVE


def test_trip_on_dvol_spike(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on DVOL spike."""
    breaker = CircuitBreaker(breaker_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,  # Above 80 threshold
        timestamp=datetime.now(timezone.utc),
    )

    event = breaker.check_dvol(metrics)

    assert event is not None
    assert event.trigger == "dvol_spike"
    assert breaker.status == BreakerStatus.TRIPPED


def test_no_resume_until_dvol_below_resume_threshold(
    breaker_config: BreakerConfig,
) -> None:
    """Test no auto-resume until DVOL falls below resume threshold."""
    breaker = CircuitBreaker(breaker_config)

    # Trip on high DVOL
    metrics_high = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )
    breaker.check_dvol(metrics_high)
    assert breaker.status == BreakerStatus.TRIPPED

    # Still high but below trip threshold
    metrics_mid = MarketMetrics(
        btc_price=97000.0,
        dvol=75.0,  # Below 80 but above 70 resume threshold
        timestamp=datetime.now(timezone.utc),
    )

    # Shouldn't auto-resume
    assert breaker.can_resume_dvol(metrics_mid) is False

    # Below resume threshold
    metrics_low = MarketMetrics(
        btc_price=97000.0,
        dvol=65.0,  # Below 70 resume threshold
        timestamp=datetime.now(timezone.utc),
    )

    assert breaker.can_resume_dvol(metrics_low) is True


def test_trip_on_api_errors(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on too many API errors."""
    breaker = CircuitBreaker(breaker_config)

    # Record 3 errors (threshold)
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now - timedelta(seconds=60))
    breaker.record_api_error(now - timedelta(seconds=30))
    event = breaker.record_api_error(now)

    assert event is not None
    assert event.trigger == "api_errors"
    assert breaker.status == BreakerStatus.TRIPPED


def test_api_errors_expire_outside_window(breaker_config: BreakerConfig) -> None:
    """Test old API errors don't count toward threshold."""
    breaker = CircuitBreaker(breaker_config)

    now = datetime.now(timezone.utc)

    # Old errors outside 5-minute window
    breaker.record_api_error(now - timedelta(seconds=400))
    breaker.record_api_error(now - timedelta(seconds=350))

    # Only 1 recent error
    event = breaker.record_api_error(now)

    assert event is None
    assert breaker.status == BreakerStatus.ACTIVE


def test_manual_trip_and_reset(breaker_config: BreakerConfig) -> None:
    """Test manual trip and force reset."""
    breaker = CircuitBreaker(breaker_config)

    breaker.trip("manual_test", "Testing manual trip")
    assert breaker.status == BreakerStatus.TRIPPED

    # Force reset ignores cooldown
    result = breaker.reset(force=True)
    assert result is True
    assert breaker.status == BreakerStatus.ACTIVE


def test_reset_blocked_during_cooldown(breaker_config: BreakerConfig) -> None:
    """Test reset fails during cooldown period."""
    breaker = CircuitBreaker(breaker_config)

    breaker.trip("test", "Testing cooldown")
    assert breaker.status == BreakerStatus.TRIPPED

    # Non-forced reset should fail during cooldown
    result = breaker.reset(force=False)
    assert result is False
    assert breaker.status == BreakerStatus.TRIPPED


def test_get_events_history(breaker_config: BreakerConfig) -> None:
    """Test event history is maintained."""
    breaker = CircuitBreaker(breaker_config)

    breaker.check_daily_loss(-6000.0, 100000.0)
    breaker.reset(force=True)  # Force reset to bypass cooldown
    breaker.trip("test", "Another test")

    events = breaker.get_events()

    assert len(events) == 2
    assert events[0].trigger == "daily_loss"
    assert events[1].trigger == "test"


# =============================================================================
# API RECOVERY TESTS
# =============================================================================


@pytest.fixture
def recovery_config() -> BreakerConfig:
    """Create config with short recovery intervals for testing."""
    return BreakerConfig(
        daily_loss_limit_pct=0.05,
        dvol_halt_threshold=80.0,
        dvol_resume_threshold=70.0,
        api_error_threshold=3,
        api_error_window_seconds=300,
        cooldown_hours=24,
        api_recovery_base_seconds=60,  # 1 minute for testing
        api_recovery_max_seconds=300,  # 5 minutes max
    )


def test_can_attempt_api_recovery_not_tripped(recovery_config: BreakerConfig) -> None:
    """Test recovery not allowed when not tripped."""
    breaker = CircuitBreaker(recovery_config)

    assert breaker.can_attempt_api_recovery() is False


def test_can_attempt_api_recovery_wrong_reason(recovery_config: BreakerConfig) -> None:
    """Test recovery not allowed when tripped for non-API reason."""
    breaker = CircuitBreaker(recovery_config)

    breaker.trip("daily_loss", "Daily loss exceeded")

    assert breaker.can_attempt_api_recovery() is False


def test_can_attempt_api_recovery_after_cooldown(recovery_config: BreakerConfig) -> None:
    """Test recovery allowed after base cooldown."""
    breaker = CircuitBreaker(recovery_config)

    # Trip for API errors
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now - timedelta(seconds=2))
    breaker.record_api_error(now - timedelta(seconds=1))
    breaker.record_api_error(now)

    assert breaker.status == BreakerStatus.TRIPPED
    assert breaker._trip_reason == "api_errors"

    # Immediately after trip - should not allow recovery
    assert breaker.can_attempt_api_recovery() is False

    # Simulate time passing (modify trip time)
    breaker._trip_time = now - timedelta(seconds=61)  # Past 60s base cooldown

    assert breaker.can_attempt_api_recovery() is True


def test_record_recovery_attempt_success(recovery_config: BreakerConfig) -> None:
    """Test successful recovery resets breaker."""
    breaker = CircuitBreaker(recovery_config)

    # Trip for API errors
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now)
    breaker.record_api_error(now)
    breaker.record_api_error(now)

    assert breaker.status == BreakerStatus.TRIPPED

    # Record successful recovery
    breaker.record_recovery_attempt(success=True)

    assert breaker.status == BreakerStatus.ACTIVE
    assert breaker._recovery_attempt_count == 0
    assert breaker._last_recovery_attempt is None

    # Should have recorded recovery event
    events = breaker.get_events()
    assert events[-1].trigger == "api_recovery"


def test_record_recovery_attempt_failure_exponential_backoff(
    recovery_config: BreakerConfig,
) -> None:
    """Test failed recovery uses exponential backoff."""
    breaker = CircuitBreaker(recovery_config)

    # Trip for API errors
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now)
    breaker.record_api_error(now)
    breaker.record_api_error(now)

    # Move trip time back to allow first attempt
    breaker._trip_time = now - timedelta(seconds=61)

    # First failed attempt
    breaker.record_recovery_attempt(success=False)
    assert breaker._recovery_attempt_count == 1
    assert breaker.status == BreakerStatus.TRIPPED

    # Wait time should be 60 * 2^1 = 120 seconds
    wait = breaker.get_next_recovery_wait()
    assert 119 <= wait <= 121  # Allow for timing variance


def test_recovery_backoff_capped_at_max(recovery_config: BreakerConfig) -> None:
    """Test backoff is capped at max value."""
    breaker = CircuitBreaker(recovery_config)

    # Trip for API errors
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now)
    breaker.record_api_error(now)
    breaker.record_api_error(now)

    breaker._trip_time = now - timedelta(seconds=61)

    # Simulate many failed attempts
    for i in range(10):
        breaker.record_recovery_attempt(success=False)

    # Wait should be capped at 300 seconds (max)
    wait = breaker.get_next_recovery_wait()
    assert wait <= 301  # Max + small timing tolerance


def test_get_next_recovery_wait_not_applicable(recovery_config: BreakerConfig) -> None:
    """Test wait returns -1 for non-API error trips."""
    breaker = CircuitBreaker(recovery_config)

    breaker.trip("daily_loss", "Daily loss exceeded")

    assert breaker.get_next_recovery_wait() == -1
