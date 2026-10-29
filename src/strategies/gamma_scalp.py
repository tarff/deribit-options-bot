"""Gamma Scalping strategy implementation.

Gamma Scalping profits from high realized volatility:
- Buy ATM straddle (long gamma)
- Continuously hedge delta to lock in profits from price oscillations
- Theta decays but is offset by scalping profits if RV > IV

Entry: RV > 40%, LOW_IV or VOLATILE_FAIR regime
Exit: RV < IV for 3 days, 7 DTE, or scalp P&L < theta
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
class GammaScalpConfig(StrategyConfig):
    """Configuration specific to Gamma Scalp strategy.

    Attributes:
        min_rv: Minimum RV (7d) required for entry.
        scalp_threshold: Delta threshold to trigger scalp trade.
        exit_dte: Exit when DTE falls below this.
        long_debit_stop_loss_pct: Stop out when the straddle has lost this
            fraction of the entry debit (range (0, 1]; None disables the
            check). The inherited ``loss_limit`` field is sized for
            short-credit strategies (>1.0) and is unreachable for a long
            debit, so this field is used instead. Calibrated via
            scripts/calibrate_gamma_scalp_stop.py — see factory.py.
    """

    min_rv: float = 40.0
    scalp_threshold: float = 0.10
    exit_dte: int = 7
    long_debit_stop_loss_pct: Optional[float] = None


class GammaScalpStrategy(BaseStrategy):
    """Gamma Scalping: Long straddle with continuous delta hedging.

    Profits from price oscillations when RV exceeds IV.
    """

    def __init__(self, config: GammaScalpConfig) -> None:
        super().__init__(config)
        self.gs_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.GAMMA_SCALP

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal based on RV.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to buy straddle, or None.
        """
        if not self.can_open():
            return None

        # Check RV conditions
        if metrics.rv_7d is None or metrics.rv_7d < self.gs_config.min_rv:
            return None

        return self._generate_straddle_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage position - scalp delta or exit.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to scalp, close, or None.
        """
        if not self.state.is_active:
            return None

        if len(self.state.contracts) != 2:
            return None

        now = metrics.timestamp
        if now is not None:
            min_dte = min((c.expiry - now).days for c in self.state.contracts)
            if min_dte <= self.gs_config.exit_dte:
                return self._generate_close_signal(
                    f"DTE exit: {min_dte} days remaining"
                )

        current_value = self._get_current_straddle_value(option_chain)
        # Include entry fees in cost basis so the strategy-side profit target
        # matches the realized PnL calculation in paper_trading._execute_signal
        # (which deducts both entry and close fees).
        initial_debit = abs(self.state.premium_received) + self.state.entry_fees
        if current_value is not None and initial_debit > 0:
            profit_pct = (current_value - initial_debit) / initial_debit
            if profit_pct >= self.config.profit_target:
                return self._generate_close_signal(
                    f"Profit target: {profit_pct:.1%}"
                )

            stop_loss_pct = self.gs_config.long_debit_stop_loss_pct
            if stop_loss_pct is not None:
                loss_pct = (initial_debit - current_value) / initial_debit
                if loss_pct >= stop_loss_pct:
                    return self._generate_close_signal(
                        f"Loss limit: {loss_pct:.1%}"
                    )

        # Check exit condition: RV dropped below threshold
        if metrics.rv_7d is not None and metrics.rv_7d < self.gs_config.min_rv:
            return self._generate_close_signal(
                f"RV dropped to {metrics.rv_7d:.1f}% (below {self.gs_config.min_rv}%)"
            )

        # Check for scalp opportunity using live chain deltas
        portfolio_delta = self._calculate_portfolio_delta(option_chain)
        net_delta = portfolio_delta + self.state.hedge_delta

        if abs(net_delta) > self.gs_config.scalp_threshold:
            return TradeSignal(
                strategy_type=self.strategy_type,
                action=SignalAction.HEDGE,
                contracts=[],
                direction="sell" if net_delta > 0 else "buy",
                quantity=abs(net_delta),
                target_delta=0.0,
                reason=f"Gamma scalp: net delta {net_delta:.3f} exceeds threshold",
            )

        return None

    def _generate_straddle_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate buy straddle signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to buy straddle, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for shorter DTE (more gamma)
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
            reference_time=metrics.timestamp,
        )

        straddle = selector.find_matching_straddle()
        if straddle is None:
            logger.debug("Gamma Scalp: No matching ATM straddle found")
            return None
        atm_put, atm_call = straddle

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[atm_put, atm_call],
            direction="buy",
            quantity=self.config.max_position_size,
            legs_direction=["buy", "buy"],
            reason=f"Gamma scalp entry: RV(7d) {metrics.rv_7d:.1f}%",
        )

    def _generate_close_signal(self, reason: str) -> TradeSignal:
        """Generate close signal.

        Args:
            reason: Reason for closing.

        Returns:
            Close signal.
        """
        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=self.state.contracts,
            direction="sell",
            quantity=self.state.position_size,
            legs_direction=["sell"] * len(self.state.contracts),
            reason=reason,
        )

    def _calculate_portfolio_delta(
        self, option_chain: list[OptionContract],
    ) -> float:
        """Calculate total portfolio delta using current chain.

        Looks up live deltas from the option chain rather than using
        stale entry-time deltas stored on state.contracts.

        Args:
            option_chain: Current option chain with live greeks.

        Returns:
            Sum of deltas for all contracts.
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
        quantity = self.state.position_size or 1.0
        return total_delta * quantity

    def _get_current_straddle_value(
        self,
        option_chain: list[OptionContract],
    ) -> Optional[float]:
        """Get execution value for closing the long straddle."""
        chain_by_name = {opt.instrument_name: opt for opt in option_chain}
        qty = self.state.position_size or 1.0
        total = 0.0

        for contract in self.state.contracts:
            current = chain_by_name.get(contract.instrument_name)
            if current is None:
                return None
            price = current.bid
            if price is None:
                price = current.mark_price
            if price is None:
                price = current.mid_price
            if price is None:
                return None
            total += price * qty

        return total
