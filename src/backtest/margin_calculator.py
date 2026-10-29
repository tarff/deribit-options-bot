"""Margin calculation and tracking for backtesting.

This module provides margin requirement calculations for different position types
and tracks margin usage over the course of a backtest to determine minimum
capital requirements.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from src.backtest.position_tracker import BacktestPosition


@dataclass
class MarginConfig:
    """Configuration for margin calculations.

    Calibrated via scripts/calibrate_margin_pct.py (2026-01-30) using
    Deribit's published margin formula on live option chain data.

    Deribit formula: Margin = max(15% * index, 10% * index + mark) + mark

    Attributes:
        naked_short_pct: Margin requirement as percentage of notional for naked shorts.
            Calibrated: OTM median 15.7%, ATM median 18.7%, overall median 17.9%
            Using 18% for conservative backtesting.
        spread_margin_type: How to calculate spread margin ("max_loss").
        maintenance_ratio: Maintenance margin as fraction of initial margin.
    """

    # Calibrated 2026-01-30: OTM median 15.7%, ATM 18.7%, overall 17.9%
    # Using 18% for conservative backtesting (covers ATM scenarios)
    naked_short_pct: float = 0.18
    spread_margin_type: str = "max_loss"
    maintenance_ratio: float = 0.80


@dataclass
class MarginRequirement:
    """Margin requirement for a single position.

    Attributes:
        initial_margin: Required margin to open position.
        maintenance_margin: Required margin to maintain position.
        margin_type: Type of margin calculation used.
    """

    initial_margin: float
    maintenance_margin: float
    margin_type: str


@dataclass
class MarginSnapshot:
    """Point-in-time margin state.

    Attributes:
        timestamp: When snapshot was taken.
        total_margin_required: Total initial margin across all positions.
        total_maintenance: Total maintenance margin across all positions.
        available_capital: Capital after margin requirements.
        margin_utilization: Margin used as fraction of capital.
    """

    timestamp: datetime
    total_margin_required: float
    total_maintenance: float
    available_capital: float
    margin_utilization: float


@dataclass
class MarginMetrics:
    """Summary metrics for margin usage over a backtest.

    Attributes:
        min_capital_required: Minimum capital to avoid margin breaches.
        peak_margin_used: Highest total margin requirement observed.
        avg_margin_utilization: Average margin utilization over backtest.
        margin_breach_count: Number of times margin exceeded capital.
        peak_margin_timestamp: When peak margin occurred.
    """

    min_capital_required: float = 0.0
    peak_margin_used: float = 0.0
    avg_margin_utilization: float = 0.0
    margin_breach_count: int = 0
    peak_margin_timestamp: Optional[datetime] = None


def infer_margin_type(position: BacktestPosition) -> str:
    """Infer the margin type for a position based on its legs.

    Margin types:
    - "long_premium": All legs are buys (margin = premium paid)
    - "naked_short": All legs are sells (margin = % of notional)
    - "spread": Mixed buy/sell legs (margin = max loss of spread)

    Args:
        position: The backtest position to analyze.

    Returns:
        One of "long_premium", "naked_short", or "spread".
    """
    if not position.legs_direction:
        return "long_premium"

    all_buy = all(d == "buy" for d in position.legs_direction)
    all_sell = all(d == "sell" for d in position.legs_direction)

    if all_buy:
        return "long_premium"
    elif all_sell:
        return "naked_short"
    else:
        return "spread"


class MarginCalculator:
    """Calculate margin requirements for backtest positions.

    Supports three margin calculation methods based on position type:
    1. Long positions: Margin = premium paid (full cost upfront)
    2. Naked short: Margin = percentage of notional value
    3. Spreads: Margin = maximum loss of the spread
    """

    def __init__(self, config: Optional[MarginConfig] = None) -> None:
        """Initialize margin calculator.

        Args:
            config: Margin configuration. Uses defaults if not provided.
        """
        self.config = config or MarginConfig()

    def calculate(
        self,
        position: BacktestPosition,
        spot_price: float,
    ) -> MarginRequirement:
        """Calculate margin requirement for a position.

        Args:
            position: The position to calculate margin for.
            spot_price: Current spot price for notional calculation.

        Returns:
            MarginRequirement with initial and maintenance margin.
        """
        margin_type = infer_margin_type(position)

        if margin_type == "long_premium":
            initial_margin = self._calculate_long_margin(position)
        elif margin_type == "naked_short":
            initial_margin = self._calculate_naked_short_margin(position, spot_price)
        else:  # spread
            initial_margin = self._calculate_spread_margin(position, spot_price)

        maintenance_margin = initial_margin * self.config.maintenance_ratio

        return MarginRequirement(
            initial_margin=initial_margin,
            maintenance_margin=maintenance_margin,
            margin_type=margin_type,
        )

    def _calculate_long_margin(self, position: BacktestPosition) -> float:
        """Calculate margin for long positions (all buys).

        For long options, margin = premium paid (full cost upfront).

        Args:
            position: The long position.

        Returns:
            Margin requirement in USD.
        """
        # Premium is already stored as negative for long positions
        # We need the absolute value of what was paid
        total_premium = 0.0
        for contract, direction in zip(
            position.contracts, position.legs_direction, strict=True
        ):
            if direction == "buy":
                mid = contract.mid_price or 0.0
                # Convert from BTC to USD using entry price
                total_premium += mid * position.entry_price

        return total_premium * position.quantity

    def _calculate_naked_short_margin(
        self,
        position: BacktestPosition,
        spot_price: float,
    ) -> float:
        """Calculate margin for naked short positions.

        Naked short margin = percentage of notional value.

        Args:
            position: The naked short position.
            spot_price: Current spot price.

        Returns:
            Margin requirement in USD.
        """
        # Notional = quantity * spot_price
        notional = position.quantity * spot_price

        # PLACEHOLDER: naked_short_pct needs Deribit calibration
        return notional * self.config.naked_short_pct

    def _calculate_spread_margin(
        self,
        position: BacktestPosition,
        spot_price: float,
    ) -> float:
        """Calculate margin for spread positions (mixed buy/sell).

        Spread margin = maximum loss of the spread.
        If max_loss is not set, falls back to notional-based calculation.

        Args:
            position: The spread position.
            spot_price: Current spot price.

        Returns:
            Margin requirement in USD.
        """
        if position.max_loss is not None and position.max_loss > 0:
            # max_loss is in BTC, convert to USD
            return position.max_loss * spot_price * position.quantity

        # Fallback: use reduced notional if max_loss not available
        # This is a conservative estimate
        notional = position.quantity * spot_price
        return notional * self.config.naked_short_pct * 0.5


class MarginTracker:
    """Track margin usage over time during a backtest.

    Records margin snapshots at each bar and calculates summary metrics
    at the end of the backtest.
    """

    def __init__(
        self,
        initial_capital: float,
        config: Optional[MarginConfig] = None,
    ) -> None:
        """Initialize margin tracker.

        Args:
            initial_capital: Starting capital for the backtest.
            config: Margin configuration.
        """
        self.initial_capital = initial_capital
        self.calculator = MarginCalculator(config)
        self.snapshots: list[MarginSnapshot] = []
        self._peak_margin = 0.0
        self._peak_margin_timestamp: Optional[datetime] = None
        self._breach_count = 0

    def record_snapshot(
        self,
        positions: dict[str, BacktestPosition],
        capital: float,
        spot_price: float,
        timestamp: datetime,
    ) -> MarginSnapshot:
        """Record a margin snapshot for the current state.

        Args:
            positions: Current open positions.
            capital: Current capital.
            spot_price: Current spot price.
            timestamp: Current timestamp.

        Returns:
            The recorded margin snapshot.
        """
        total_initial = 0.0
        total_maintenance = 0.0

        for position in positions.values():
            req = self.calculator.calculate(position, spot_price)
            total_initial += req.initial_margin
            total_maintenance += req.maintenance_margin

        # Calculate utilization
        margin_utilization = total_initial / capital if capital > 0 else 0.0
        available_capital = capital - total_initial

        # Track peak margin
        if total_initial > self._peak_margin:
            self._peak_margin = total_initial
            self._peak_margin_timestamp = timestamp

        # Track breaches (margin exceeds capital)
        if total_initial > capital:
            self._breach_count += 1

        snapshot = MarginSnapshot(
            timestamp=timestamp,
            total_margin_required=total_initial,
            total_maintenance=total_maintenance,
            available_capital=available_capital,
            margin_utilization=margin_utilization,
        )
        self.snapshots.append(snapshot)

        return snapshot

    def get_margin_for_signal(
        self,
        contracts: list[Any],
        legs_direction: list[str],
        quantity: float,
        spot_price: float,
        max_loss: Optional[float] = None,
    ) -> float:
        """Calculate margin that would be required for a potential trade.

        Used for pre-trade validation to check if there's enough margin
        before opening a position.

        Args:
            contracts: Option contracts in the signal.
            legs_direction: Direction for each leg.
            quantity: Position size.
            spot_price: Current spot price.
            max_loss: Maximum loss if known (for spreads).

        Returns:
            Estimated margin requirement in USD.
        """
        # Infer margin type from directions
        all_buy = all(d == "buy" for d in legs_direction)
        all_sell = all(d == "sell" for d in legs_direction)

        if all_buy:
            # Long premium: margin = premium paid
            total_premium = 0.0
            for contract in contracts:
                mid = contract.mid_price or 0.0
                total_premium += mid * spot_price
            return total_premium * quantity

        elif all_sell:
            # Naked short: margin = % of notional
            notional = quantity * spot_price
            return notional * self.calculator.config.naked_short_pct

        else:
            # Spread: margin = max loss
            if max_loss is not None and max_loss > 0:
                return max_loss * spot_price * quantity
            # Fallback
            notional = quantity * spot_price
            return notional * self.calculator.config.naked_short_pct * 0.5

    def get_current_margin_required(
        self,
        positions: dict[str, BacktestPosition],
        spot_price: float,
    ) -> float:
        """Get total margin required for current positions.

        Args:
            positions: Current open positions.
            spot_price: Current spot price.

        Returns:
            Total margin required in USD.
        """
        total = 0.0
        for position in positions.values():
            req = self.calculator.calculate(position, spot_price)
            total += req.initial_margin
        return total

    def calculate_metrics(self) -> MarginMetrics:
        """Calculate summary metrics from recorded snapshots.

        Returns:
            MarginMetrics with min_capital_required, peak_margin, etc.
        """
        if not self.snapshots:
            return MarginMetrics()

        # Average margin utilization
        avg_utilization = sum(s.margin_utilization for s in self.snapshots) / len(
            self.snapshots
        )

        # Min capital required = peak margin (to never breach)
        # Add a small buffer for safety
        min_capital = self._peak_margin * 1.05 if self._peak_margin > 0 else 0.0

        return MarginMetrics(
            min_capital_required=min_capital,
            peak_margin_used=self._peak_margin,
            avg_margin_utilization=avg_utilization,
            margin_breach_count=self._breach_count,
            peak_margin_timestamp=self._peak_margin_timestamp,
        )

    def reset(self) -> None:
        """Reset tracker state for a new backtest."""
        self.snapshots.clear()
        self._peak_margin = 0.0
        self._peak_margin_timestamp = None
        self._breach_count = 0
