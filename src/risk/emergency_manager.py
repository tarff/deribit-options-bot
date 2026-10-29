"""Emergency manager for extreme market conditions."""

from dataclasses import dataclass
from typing import Optional

from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.persistence.models import Position, PositionStatus


@dataclass
class EmergencyConfig:
    """Configuration for emergency manager.

    Attributes:
        dvol_emergency_threshold: DVOL level triggering emergency close (default 100).
    """

    # TODO(backtest): Validate threshold - DVOL 100 may be too conservative for crypto.
    # Historical DVOL exceeds 100 during normal stress, not just crashes.
    # Analyze frequency and P&L impact of closes at 100 vs 120 vs 130.
    dvol_emergency_threshold: float = 100.0


class EmergencyManager:
    """Manages emergency position closures during extreme conditions.

    Triggers active position closure (not just halt) when DVOL > 100.
    This is more severe than CircuitBreaker's DVOL >= 80 halt.
    """

    # Short vol strategy types that should be closed in emergency
    SHORT_VOL_STRATEGIES = {"iron_condor"}
    # Vol arb with sell_vol phase is also short vol
    VOL_ARB_SHORT_PHASE = "sell_vol"

    def __init__(self, config: EmergencyConfig) -> None:
        """Initialize emergency manager.

        Args:
            config: Emergency configuration.
        """
        self.config = config

    def is_emergency(self, metrics: MarketMetrics) -> bool:
        """Check if emergency conditions exist.

        Args:
            metrics: Current market metrics.

        Returns:
            True if DVOL exceeds emergency threshold.
        """
        if metrics.dvol is None:
            return False

        return metrics.dvol > self.config.dvol_emergency_threshold

    def identify_short_vol_positions(
        self,
        positions: list[Position],
    ) -> list[Position]:
        """Identify short vol positions that should be closed.

        Short vol positions:
        - Iron Condor (always short vol)
        - Vol Arb with phase="sell_vol"

        Args:
            positions: All open positions.

        Returns:
            List of positions to close.
        """
        to_close: list[Position] = []

        for pos in positions:
            if pos.status != PositionStatus.OPEN:
                continue

            # Short vol strategies (iron condor, etc.)
            if pos.strategy_type in self.SHORT_VOL_STRATEGIES:
                to_close.append(pos)
                continue

            # Vol arb with sell_vol phase
            if pos.strategy_type == "vol_arb" and pos.phase == self.VOL_ARB_SHORT_PHASE:
                to_close.append(pos)

        return to_close

    def check_emergency(
        self,
        metrics: MarketMetrics,
        positions: list[Position],
        strategy_contracts: Optional[dict[str, tuple[list[OptionContract], list[str], float]]] = None,
    ) -> list[TradeSignal]:
        """Check for emergency and generate close signals if needed.

        Args:
            metrics: Current market metrics.
            positions: All open positions.
            strategy_contracts: Optional mapping of strategy_id to
                (contracts, legs_direction, quantity) from active strategy state.

        Returns:
            List of CLOSE signals for short vol positions, empty if no emergency.
        """
        if not self.is_emergency(metrics):
            return []

        to_close = self.identify_short_vol_positions(positions)
        contracts_map = strategy_contracts or {}

        signals: list[TradeSignal] = []
        for pos in to_close:
            try:
                strategy_type = StrategyType(pos.strategy_type)
            except ValueError:
                continue

            # Resolve contracts and quantity from strategy state
            contracts: list[OptionContract] = []
            legs_direction: Optional[list[str]] = None
            quantity = 0.0
            if pos.strategy_id in contracts_map:
                contracts, legs_dir, qty = contracts_map[pos.strategy_id]
                legs_direction = legs_dir
                quantity = qty

            if not contracts:
                # Skip if no contracts available - can't close nothing
                continue

            # Reverse legs_direction for closing (sell->buy, buy->sell)
            close_legs = None
            if legs_direction:
                close_legs = [
                    "buy" if d == "sell" else "sell" for d in legs_direction
                ]

            signal = TradeSignal(
                strategy_type=strategy_type,
                action=SignalAction.CLOSE,
                contracts=contracts,
                direction="buy",
                quantity=quantity,
                legs_direction=close_legs,
                reason=f"DVOL emergency {metrics.dvol:.0f} > {self.config.dvol_emergency_threshold}: closing {pos.strategy_id}",
            )
            signals.append(signal)

        return signals
