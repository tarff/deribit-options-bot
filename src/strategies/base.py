"""Base strategy interface and common components."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.brain.signal import TradeSignal, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@dataclass
class StrategyConfig:
    """Configuration for a strategy.

    Attributes:
        name: Strategy identifier.
        enabled: Whether strategy is active.
        max_position_size: Maximum position size as fraction of capital.
        target_dte_min: Minimum days to expiry for entries.
        target_dte_max: Maximum days to expiry for entries.
        profit_target: Close at this fraction of max profit (e.g., 0.50).
        loss_limit: Close at this fraction of max loss (e.g., 2.0 = 200%).
        target_delta: Target delta for option selection.
    """

    name: str
    enabled: bool
    max_position_size: float = 0.10
    target_dte_min: int = 30
    target_dte_max: int = 45
    profit_target: float = 0.50
    loss_limit: float = 2.0
    target_delta: float = 0.25


@dataclass
class StrategyState:
    """Runtime state for a strategy instance.

    Attributes:
        is_active: Whether strategy has an open position.
        position_id: ID of current position (if active).
        phase: Current phase (strategy-specific, e.g., 'csp', 'covered_call').
        entry_time: When position was opened.
        entry_price: Underlying price at entry.
        premium_received: Total premium collected.
        current_pnl: Current unrealized P&L.
        hedge_delta: Signed underlying hedge delta; positive is long underlying,
            negative is short underlying.
        contracts: Active option contracts.
    """

    is_active: bool = False
    position_id: Optional[str] = None
    phase: Optional[str] = None
    entry_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    premium_received: float = 0.0
    current_pnl: float = 0.0
    position_size: float = 0.0
    entry_fees: float = 0.0
    hedge_delta: float = 0.0
    contracts: list[OptionContract] = field(default_factory=list)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Strategies implement two main methods:
    - evaluate(): Check for new entry signals when no position exists
    - manage(): Check for exit/adjustment signals when position is open
    """

    def __init__(self, config: StrategyConfig) -> None:
        """Initialize strategy with configuration.

        Args:
            config: Strategy configuration.
        """
        self.config = config
        self.state = StrategyState()

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enum value."""
        pass

    @abstractmethod
    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate market for entry signals.

        Called when strategy has no open position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            TradeSignal to open position, or None.
        """
        pass

    @abstractmethod
    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing position.

        Called when strategy has an open position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            TradeSignal to close/adjust, or None.
        """
        pass

    def can_open(self) -> bool:
        """Check if strategy can open a new position.

        Returns:
            True if enabled and no active position.
        """
        return self.config.enabled and not self.state.is_active

    def activate(
        self,
        position_id: str,
        entry_price: float,
        phase: str = "",
        entry_time: datetime | None = None,
    ) -> None:
        """Mark strategy as having an active position.

        Args:
            position_id: Unique position identifier.
            entry_price: Underlying price at entry.
            phase: Initial phase (optional).
            entry_time: Entry timestamp (defaults to now, pass simulation time for backtests).
        """
        self.state.is_active = True
        self.state.position_id = position_id
        self.state.entry_time = entry_time or datetime.now()
        self.state.entry_price = entry_price
        self.state.phase = phase

    def deactivate(self) -> None:
        """Mark strategy as having no active position."""
        self.state = StrategyState()

    def update_pnl(self, current_pnl: float) -> None:
        """Update current P&L.

        Args:
            current_pnl: Current unrealized P&L.
        """
        self.state.current_pnl = current_pnl
