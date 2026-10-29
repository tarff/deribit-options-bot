"""Volatility Arbitrage strategy implementation.

Vol Arb trades the IV-RV spread:
- Sell ATM straddle when IV >> RV (IV overpriced)
- Buy ATM straddle when IV << RV (IV underpriced)
- Delta hedge to remain neutral

Entry: |IV-RV spread| > threshold
Exit: Spread normalizes, profit target, or time limit
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
class VolArbConfig(StrategyConfig):
    """Configuration specific to Vol Arb strategy.

    Attributes:
        iv_rv_threshold_sell: IV-RV spread above this → sell vol.
        iv_rv_threshold_buy: IV-RV spread below this → buy vol.
        delta_hedge_threshold: Rebalance when |delta| exceeds this.

    Thresholds validated via scripts/analyze_strategy_thresholds.py (2026-01-23):
        - iv_rv_threshold_buy (-10): ~41 entry days/year (11% of days)
        - Mean 7-day forward return when spread < -10: +1.92% vs +1.24% overall
        - This is a statistically meaningful signal for IV mean reversion
        - iv_rv_threshold_sell (+15): ~26% of days have spread > 15
    """

    iv_rv_threshold_sell: float = 15.0
    iv_rv_threshold_buy: float = -10.0
    delta_hedge_threshold: float = 0.10


class VolArbStrategy(BaseStrategy):
    """Volatility Arbitrage: Trade IV-RV spread with delta hedging.

    Modes:
    - 'sell_vol': Short ATM straddle (IV overpriced)
    - 'buy_vol': Long ATM straddle (IV underpriced)
    """

    def __init__(self, config: VolArbConfig) -> None:
        super().__init__(config)
        self.va_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.VOL_ARB

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal based on IV-RV spread.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open straddle, or None.
        """
        if not self.can_open():
            return None

        if metrics.iv_rv_spread is None:
            return None

        # Check for sell vol opportunity
        if metrics.iv_rv_spread > self.va_config.iv_rv_threshold_sell:
            return self._generate_straddle_signal(metrics, option_chain, "sell")

        # Check for buy vol opportunity
        if metrics.iv_rv_spread < self.va_config.iv_rv_threshold_buy:
            return self._generate_straddle_signal(metrics, option_chain, "buy")

        return None

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage position - check for hedge or exit signals.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to hedge, close, or None.
        """
        if not self.state.is_active:
            return None

        if len(self.state.contracts) != 2:
            return None

        # Calculate current portfolio delta using live chain (not stale entry deltas)
        portfolio_delta = self._calculate_portfolio_delta(option_chain)
        net_delta = portfolio_delta + self.state.hedge_delta

        # Check if hedge needed
        if abs(net_delta) > self.va_config.delta_hedge_threshold:
            return TradeSignal(
                strategy_type=self.strategy_type,
                action=SignalAction.HEDGE,
                contracts=[],
                direction="sell" if net_delta > 0 else "buy",
                quantity=abs(net_delta),
                target_delta=0.0,
                reason=f"Delta hedge: net delta {net_delta:.3f}",
            )

        # Check if spread normalized (exit condition)
        if metrics.iv_rv_spread is not None:
            if self.state.phase == "sell_vol" and metrics.iv_rv_spread < 5:
                return self._generate_close_signal("IV-RV spread normalized")
            if self.state.phase == "buy_vol" and metrics.iv_rv_spread > -5:
                return self._generate_close_signal("IV-RV spread normalized")

        return None

    def _generate_straddle_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
        direction: str,
    ) -> Optional[TradeSignal]:
        """Generate ATM straddle signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.
            direction: 'buy' or 'sell'.

        Returns:
            Signal to open straddle, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
            reference_time=metrics.timestamp,
        )

        straddle = selector.find_matching_straddle()
        if straddle is None:
            logger.debug("Vol Arb: No matching ATM straddle found")
            return None
        atm_put, atm_call = straddle

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[atm_put, atm_call],
            direction=direction,
            quantity=self.config.max_position_size,
            legs_direction=[direction, direction],
            reason=f"Vol arb {direction}: IV-RV spread {metrics.iv_rv_spread:.1f}",
        )

    def _generate_close_signal(self, reason: str) -> TradeSignal:
        """Generate close signal.

        Args:
            reason: Reason for closing.

        Returns:
            Close signal.
        """
        close_direction = "buy" if self.state.phase == "sell_vol" else "sell"

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=self.state.contracts,
            direction=close_direction,
            quantity=self.state.position_size,
            legs_direction=[close_direction] * len(self.state.contracts),
            reason=reason,
        )

    def _calculate_portfolio_delta(
        self, option_chain: list[OptionContract],
    ) -> float:
        """Calculate total portfolio delta using current chain.

        Looks up live deltas from the option chain rather than using
        stale entry-time deltas stored on state.contracts.

        For long positions (buy_vol): position delta = sum of contract deltas
        For short positions (sell_vol): position delta = -sum of contract deltas

        Args:
            option_chain: Current option chain with live greeks.

        Returns:
            Portfolio delta accounting for position direction.
        """
        chain_by_name = {opt.instrument_name: opt for opt in option_chain}

        total_delta = 0.0
        for contract in self.state.contracts:
            current = chain_by_name.get(contract.instrument_name)
            if current is not None and current.delta is not None:
                total_delta += current.delta
            elif contract.delta is not None:
                # Fallback to entry delta if contract not in current chain
                total_delta += contract.delta

        # Negate for short positions
        if self.state.phase == "sell_vol":
            total_delta = -total_delta

        quantity = self.state.position_size or 1.0
        return total_delta * quantity
