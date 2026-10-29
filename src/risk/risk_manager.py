"""Risk manager for pre-trade validation and limits."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.risk.position_sizer import PositionSizer, SizingConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType
from src.data.market_metrics import MarketMetrics

# Strategies with capped max loss (wings, spreads) that can trade at reduced
# size during extreme DVOL instead of being halted entirely.
DEFINED_RISK_STRATEGIES = frozenset({StrategyType.IRON_CONDOR})

if TYPE_CHECKING:
    from src.risk.circuit_breaker import CircuitBreaker


@dataclass
class RiskConfig:
    """Configuration for risk management.

    Attributes:
        max_positions: Maximum concurrent open positions.
        max_daily_loss_pct: Maximum daily loss as % of capital.
        max_drawdown_pct: Maximum drawdown from peak as % of peak.
    """

    max_positions: int = 5
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15


@dataclass
class ValidationResult:
    """Result of signal validation.

    Attributes:
        approved: Whether signal is approved.
        adjusted_quantity: Quantity after any adjustments.
        reason: Explanation if rejected or adjusted.
    """

    approved: bool
    adjusted_quantity: float
    reason: str = ""


class RiskManager:
    """Validates trade signals against risk limits.

    Checks:
    - Maximum open positions
    - Daily loss limit
    - Drawdown limit
    - Position sizing (via PositionSizer)

    Delegates halt state to CircuitBreaker (single source of truth).
    """

    def __init__(
        self,
        config: RiskConfig,
        sizing_config: SizingConfig,
        circuit_breaker: Optional["CircuitBreaker"] = None,
        strategy_sizing_configs: Optional[dict[StrategyType, SizingConfig]] = None,
        dvol_reduce_threshold: float = 60.0,
        dvol_halt_threshold: float = 80.0,
    ) -> None:
        """Initialize risk manager.

        Args:
            config: Risk configuration.
            sizing_config: Position sizing configuration.
            circuit_breaker: Optional circuit breaker for halt coordination.
            dvol_reduce_threshold: DVOL level to reduce position size to 50%.
            dvol_halt_threshold: DVOL level to halt new positions.
        """
        self.config = config
        self.sizer = PositionSizer(
            sizing_config,
            dvol_reduce_threshold=dvol_reduce_threshold,
            dvol_halt_threshold=dvol_halt_threshold,
        )
        self._strategy_sizers = {
            strategy_type: PositionSizer(
                config,
                dvol_reduce_threshold=dvol_reduce_threshold,
                dvol_halt_threshold=dvol_halt_threshold,
            )
            for strategy_type, config in (strategy_sizing_configs or {}).items()
        }
        self._breaker = circuit_breaker

    @property
    def halt_reason(self) -> Optional[str]:
        """Get reason for current halt, if any."""
        if self._breaker is not None:
            return self._breaker._trip_reason
        return None

    def can_trade(self) -> bool:
        """Check if trading is currently allowed.

        Returns:
            False if halted, True otherwise.
        """
        if self._breaker is not None:
            return self._breaker.can_trade()
        return True

    def halt(self, reason: str) -> None:
        """Halt all trading.

        Args:
            reason: Reason for halt.
        """
        if self._breaker is not None:
            self._breaker.trip("manual", reason)

    def resume(self) -> None:
        """Resume trading after halt (forces reset, ignoring cooldown)."""
        if self._breaker is not None:
            self._breaker.reset(force=True)

    def validate_signal(
        self,
        signal: TradeSignal,
        metrics: MarketMetrics,
        capital: float,
        current_exposure: float,
        open_positions: int,
        daily_pnl: float,
        peak_capital: float,
    ) -> ValidationResult:
        """Validate a trade signal against risk limits.

        Args:
            signal: Trade signal to validate.
            metrics: Current market metrics.
            capital: Current capital in USD.
            current_exposure: Current exposure as fraction.
            open_positions: Number of open positions.
            daily_pnl: Today's realized + unrealized P&L.
            peak_capital: Peak capital for drawdown calculation.

        Returns:
            ValidationResult with approval status and adjusted quantity.
        """
        # CLOSE and HEDGE signals always approved (reduce risk)
        if signal.action in (SignalAction.CLOSE, SignalAction.HEDGE):
            return ValidationResult(
                approved=True,
                adjusted_quantity=signal.quantity,
                reason="Close/hedge signals always approved",
            )

        # Check if halted
        if not self.can_trade():
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Trading halted: {self.halt_reason}",
            )

        # Check for depleted capital (prevents division-by-zero in loss/drawdown checks)
        if capital <= 0:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason="Capital depleted - trading halted",
            )

        # Check max positions
        if open_positions >= self.config.max_positions:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Max positions reached: {open_positions}/{self.config.max_positions}",
            )

        # Check daily loss
        daily_loss_pct = abs(daily_pnl) / capital if capital > 0 and daily_pnl < 0 else 0
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Daily loss limit: {daily_loss_pct:.1%} >= {self.config.max_daily_loss_pct:.1%}",
            )

        # Check drawdown
        drawdown = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
        if drawdown >= self.config.max_drawdown_pct:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Drawdown limit: {drawdown:.1%} >= {self.config.max_drawdown_pct:.1%}",
            )

        # Check position sizing
        is_defined_risk = signal.strategy_type in DEFINED_RISK_STRATEGIES
        sizer = self._strategy_sizers.get(signal.strategy_type, self.sizer)
        sizing_result = sizer.size_position(
            capital, metrics, current_exposure, is_defined_risk=is_defined_risk
        )

        if not sizing_result.approved:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=sizing_result.reason,
            )

        # Use risk-adjusted size from position sizer (already capped by
        # max_position_pct, Kelly, regime multiplier, and exposure limits).
        # signal.quantity is a fraction (e.g. 0.10 = 10%), not an ETH amount.
        final_quantity = sizing_result.size_coins

        return ValidationResult(
            approved=True,
            adjusted_quantity=final_quantity,
            reason=sizing_result.reason,
        )
