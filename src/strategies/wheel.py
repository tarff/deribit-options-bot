"""Wheel strategy implementation.

The Wheel is a yield strategy that cycles between:
1. Selling cash-secured puts (CSP) until assigned
2. Selling covered calls on assigned shares until called away

Entry: IV Rank above threshold (currency-specific), NEUTRAL or HIGH_IV regime
Exit: 50% profit target, assignment, or regime shift
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector

logger = logging.getLogger(__name__)


@dataclass
class WheelConfig(StrategyConfig):
    """Configuration specific to Wheel strategy.

    Attributes:
        min_iv_rank: Minimum IV Rank required for entry.
            Calibrated via scripts/analyze_iv_rank_thresholds.py (2026-01-30):
            - ETH live threshold is 46% via shared strategy factory.
            - 40% threshold: 36.5% combined win rate (IV down + price calm)
            - ~266 entry opportunities/year
            - Previous 30%: only 33.4% win rate
    """

    min_iv_rank: float = 0.40


class WheelStrategy(BaseStrategy):
    """Wheel strategy: CSP → Covered Call cycle.

    Phases:
    - 'csp': Selling cash-secured puts
    - 'covered_call': Selling covered calls after assignment
    """

    config: WheelConfig  # Type hint for IDE support

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.WHEEL

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry or phase transition signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open position or transition phase.
        """
        # If in covered call phase, generate sell call signal
        if self.state.is_active and self.state.phase == "covered_call":
            return self._generate_covered_call_signal(metrics, option_chain)

        # Otherwise, check for new CSP entry
        if not self.can_open():
            return None

        # Check IV conditions
        if metrics.iv_rank is None or metrics.iv_rank < self.config.min_iv_rank:
            return None

        return self._generate_csp_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to close/adjust, or None.
        """
        if not self.state.is_active or not self.state.contracts:
            return None

        # Check profit target using execution prices (ask = actual buyback cost).
        # Mark can diverge below ask on illiquid testnet, causing false profits.
        current_value = self._get_current_option_value(option_chain, use_mark=False)
        if current_value is not None and self.state.premium_received > 0:
            profit_pct = (self.state.premium_received - current_value) / self.state.premium_received

            if profit_pct >= self.config.profit_target:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",  # Buy back the sold option
                    quantity=self.state.position_size,
                    reason=f"Profit target reached: {profit_pct:.1%} >= {self.config.profit_target:.1%}",
                )

        return None

    def _generate_csp_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate sell put signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to sell put, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
            reference_time=metrics.timestamp,
        )

        # Find put with target delta (~0.25 OTM)
        put = selector.find_by_delta(
            target_delta=-self.config.target_delta,
            option_type="put",
            max_delta_diff=0.10,
        )

        if put is None:
            logger.debug(
                f"Wheel: No CSP found (target delta {-self.config.target_delta}, "
                f"DTE {self.config.target_dte_min}-{self.config.target_dte_max})"
            )
            return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[put],
            direction="sell",
            quantity=self.config.max_position_size,
            reason=f"Wheel CSP entry: IV Rank {metrics.iv_rank:.1%}, delta {put.delta}",
        )

    def _generate_covered_call_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate sell call signal for covered call phase.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to sell call, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
            reference_time=metrics.timestamp,
        )

        # Find call with target delta (~0.25 OTM)
        # Strike should be at or above entry price
        call = selector.find_by_delta(
            target_delta=self.config.target_delta,
            option_type="call",
            max_delta_diff=0.10,
        )

        if call is None:
            logger.debug(
                f"Wheel: No covered call found (target delta {self.config.target_delta}, "
                f"DTE {self.config.target_dte_min}-{self.config.target_dte_max})"
            )
            return None

        # Ensure strike is at or above assignment price (CSP put strike)
        if not self.state.contracts:
            logger.warning("Wheel covered call phase but no contracts in state")
            return None
        assignment_strike = self.state.contracts[0].strike
        if assignment_strike and call.strike < assignment_strike:
            # Find a call with higher strike
            call = selector.find_strike_near_price(
                price=assignment_strike,
                option_type="call",
                otm_percent=0.05,
            )
            if call is None:
                return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[call],
            direction="sell",
            quantity=self.config.max_position_size,
            reason=f"Wheel covered call: strike {call.strike}, delta {call.delta}",
        )

    def _get_current_option_value(
        self,
        option_chain: list[OptionContract],
        use_mark: bool = True,
    ) -> Optional[float]:
        """Get current value of held option.

        Args:
            option_chain: Current option chain.
            use_mark: If True, use mark_price (for loss monitoring).
                If False, use ask price (for profit target — reflects
                actual buyback cost for short positions).

        Returns:
            Current option value, or None.
        """
        if not self.state.contracts:
            return None

        held = self.state.contracts[0]

        # Match by instrument name (includes expiry) to avoid picking up
        # a different-expiry option at the same strike with a much lower price.
        current = None
        for opt in option_chain:
            if opt.instrument_name == held.instrument_name:
                current = opt
                break
        if current is None:
            return None

        qty = self.state.position_size or 1.0
        if use_mark:
            price = current.mark_price or current.mid_price
        else:
            price = current.ask or current.mark_price or current.mid_price

        if price is None:
            return None
        return price * qty
