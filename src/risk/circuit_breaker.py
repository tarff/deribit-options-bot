"""Circuit breaker for emergency trading halts."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from src.data.market_metrics import MarketMetrics


class BreakerStatus(str, Enum):
    """Circuit breaker status."""

    ACTIVE = "active"
    TRIPPED = "tripped"


@dataclass
class BreakerConfig:
    """Configuration for circuit breaker.

    Attributes:
        daily_loss_limit_pct: Trip when daily loss exceeds this %.
        dvol_halt_threshold: Trip when DVOL exceeds this.
        dvol_resume_threshold: Can resume when DVOL falls below this.
        api_error_threshold: Trip after this many errors in window.
        api_error_window_seconds: Time window for counting API errors.
        cooldown_hours: Minimum hours before auto-resume.
        api_recovery_base_seconds: Base wait time before attempting API recovery.
        api_recovery_max_seconds: Maximum wait time between recovery attempts.
    """

    daily_loss_limit_pct: float = 0.05
    dvol_halt_threshold: float = 80.0
    dvol_resume_threshold: float = 70.0
    api_error_threshold: int = 3
    api_error_window_seconds: int = 300
    cooldown_hours: int = 24
    api_recovery_base_seconds: int = 300  # 5 minutes
    api_recovery_max_seconds: int = 1800  # 30 minutes


@dataclass
class BreakerEvent:
    """Record of a circuit breaker event.

    Attributes:
        trigger: What triggered the event.
        message: Description of the event.
        timestamp: When it occurred.
        severity: 'warning' or 'critical'.
    """

    trigger: str
    message: str
    timestamp: datetime
    severity: str = "critical"


class CircuitBreaker:
    """Circuit breaker for emergency trading halts.

    Triggers on:
    - Daily loss exceeding limit
    - DVOL spike above threshold
    - Too many API errors in time window
    """

    def __init__(self, config: BreakerConfig) -> None:
        """Initialize circuit breaker.

        Args:
            config: Breaker configuration.
        """
        self.config = config
        self._status = BreakerStatus.ACTIVE
        self._trip_time: Optional[datetime] = None
        self._trip_reason: Optional[str] = None
        self._events: list[BreakerEvent] = []
        self._api_errors: list[datetime] = []
        self._last_recovery_attempt: Optional[datetime] = None
        self._recovery_attempt_count: int = 0

    @property
    def status(self) -> BreakerStatus:
        """Get current breaker status."""
        return self._status

    @property
    def trip_reason(self) -> Optional[str]:
        """Get the reason for the current trip, or None if not tripped."""
        return self._trip_reason

    def can_trade(self) -> bool:
        """Check if trading is allowed.

        Returns:
            True if breaker is active, False if tripped.
        """
        return self._status == BreakerStatus.ACTIVE

    def trip(self, trigger: str, message: str) -> BreakerEvent:
        """Trip the circuit breaker.

        Args:
            trigger: What triggered the trip.
            message: Description.

        Returns:
            BreakerEvent recording the trip.
        """
        self._status = BreakerStatus.TRIPPED
        self._trip_time = datetime.now(timezone.utc)
        self._trip_reason = trigger

        event = BreakerEvent(
            trigger=trigger,
            message=message,
            timestamp=self._trip_time,
            severity="critical",
        )
        self._events.append(event)
        return event

    def reset(self, force: bool = False) -> bool:
        """Reset circuit breaker to active state.

        Args:
            force: If True, ignore cooldown period.

        Returns:
            True if reset successful, False if still in cooldown.
        """
        if not force and self._trip_time is not None:
            cooldown_end = self._trip_time + timedelta(hours=self.config.cooldown_hours)
            if datetime.now(timezone.utc) < cooldown_end:
                return False

        self._status = BreakerStatus.ACTIVE
        self._trip_time = None
        self._trip_reason = None
        return True

    def get_events(self) -> list[BreakerEvent]:
        """Get history of breaker events.

        Returns:
            List of BreakerEvent objects.
        """
        return list(self._events)

    def check_daily_loss(
        self,
        daily_pnl: float,
        capital: float,
    ) -> Optional[BreakerEvent]:
        """Check if daily loss limit is breached.

        Args:
            daily_pnl: Today's P&L (negative for loss).
            capital: Current capital.

        Returns:
            BreakerEvent if tripped, None otherwise.
        """
        if capital <= 0 or daily_pnl >= 0:
            return None

        loss_pct = abs(daily_pnl) / capital

        if loss_pct >= self.config.daily_loss_limit_pct:
            return self.trip(
                "daily_loss",
                f"Daily loss {loss_pct:.1%} exceeds limit {self.config.daily_loss_limit_pct:.1%}",
            )

        return None

    def check_dvol(self, metrics: MarketMetrics) -> Optional[BreakerEvent]:
        """Check if DVOL exceeds halt threshold.

        Args:
            metrics: Current market metrics.

        Returns:
            BreakerEvent if tripped, None otherwise.
        """
        if metrics.dvol is None:
            return None

        if metrics.dvol >= self.config.dvol_halt_threshold:
            return self.trip(
                "dvol_spike",
                f"DVOL {metrics.dvol:.1f} exceeds halt threshold {self.config.dvol_halt_threshold}",
            )

        return None

    def can_resume_dvol(self, metrics: MarketMetrics) -> bool:
        """Check if DVOL has fallen enough to resume.

        Args:
            metrics: Current market metrics.

        Returns:
            True if DVOL below resume threshold.
        """
        if metrics.dvol is None:
            return False

        return metrics.dvol < self.config.dvol_resume_threshold

    def record_api_error(self, timestamp: Optional[datetime] = None) -> Optional[BreakerEvent]:
        """Record an API error and check threshold.

        Args:
            timestamp: When error occurred (default: now).

        Returns:
            BreakerEvent if threshold exceeded, None otherwise.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self._api_errors.append(timestamp)

        # Clean old errors outside window
        cutoff = timestamp - timedelta(seconds=self.config.api_error_window_seconds)
        self._api_errors = [t for t in self._api_errors if t > cutoff]

        if len(self._api_errors) >= self.config.api_error_threshold:
            return self.trip(
                "api_errors",
                f"{len(self._api_errors)} API errors in {self.config.api_error_window_seconds}s window",
            )

        return None

    def can_attempt_api_recovery(self) -> bool:
        """Check if enough time has passed to attempt API recovery.

        Uses exponential backoff: base * 2^attempts, capped at max.

        Returns:
            True if recovery attempt is allowed.
        """
        if self._status != BreakerStatus.TRIPPED:
            return False

        if self._trip_reason != "api_errors":
            return False

        now = datetime.now(timezone.utc)

        # First attempt allowed after base cooldown from trip time
        if self._last_recovery_attempt is None:
            if self._trip_time is None:
                return True
            wait_seconds = self.config.api_recovery_base_seconds
            return now >= self._trip_time + timedelta(seconds=wait_seconds)

        # Subsequent attempts use exponential backoff
        backoff = min(
            self.config.api_recovery_base_seconds * (2 ** self._recovery_attempt_count),
            self.config.api_recovery_max_seconds,
        )
        next_attempt = self._last_recovery_attempt + timedelta(seconds=backoff)
        return now >= next_attempt

    def record_recovery_attempt(self, success: bool) -> None:
        """Record an API recovery attempt.

        Args:
            success: Whether the recovery attempt succeeded.
        """
        self._last_recovery_attempt = datetime.now(timezone.utc)

        if success:
            # Reset on success
            self._api_errors.clear()
            self._recovery_attempt_count = 0
            self._last_recovery_attempt = None
            self.reset(force=True)

            event = BreakerEvent(
                trigger="api_recovery",
                message="API recovered successfully, circuit breaker reset",
                timestamp=datetime.now(timezone.utc),
                severity="warning",
            )
            self._events.append(event)
        else:
            # Increment attempt count for exponential backoff
            self._recovery_attempt_count += 1

    def get_next_recovery_wait(self) -> int:
        """Get seconds until next recovery attempt is allowed.

        Returns:
            Seconds to wait, or 0 if attempt is allowed now.
        """
        if self.can_attempt_api_recovery():
            return 0

        if self._trip_reason != "api_errors":
            return -1  # Not applicable

        now = datetime.now(timezone.utc)

        if self._last_recovery_attempt is None:
            if self._trip_time is None:
                return 0
            wait_seconds = self.config.api_recovery_base_seconds
            next_attempt = self._trip_time + timedelta(seconds=wait_seconds)
        else:
            backoff = min(
                self.config.api_recovery_base_seconds * (2 ** self._recovery_attempt_count),
                self.config.api_recovery_max_seconds,
            )
            next_attempt = self._last_recovery_attempt + timedelta(seconds=backoff)

        remaining = (next_attempt - now).total_seconds()
        return max(0, int(remaining))
