"""Iron Condor strategy implementation.

Iron Condor is a defined-risk premium selling strategy:
- Sell OTM put spread (bull put spread)
- Sell OTM call spread (bear call spread)
- Profit from time decay when price stays in range

Entry: IV Rank > 60%, HIGH_IV_OVERPRICED regime
Exit: 50% profit, short strike breached, or DTE < 7

Note: Position sizing applies DVOL-based reduction (0.5x when elevated).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector

logger = logging.getLogger(__name__)


@dataclass
class IronCondorConfig(StrategyConfig):
    """Configuration specific to Iron Condor strategy.

    Attributes:
        short_delta: Target delta for short strikes (default 0.15).
        wing_delta: Target delta for wing strikes (default 0.05).
            Calibrated via scripts/calibrate_iron_condor_wing_delta.py (2026-02-02):
            - 0.05 delta: Sharpe 11.23, 96.3% win rate (optimal)
            - 0.10 delta: Sharpe 1.79, 87.0% win rate
            - 0.12+ delta: Unprofitable
        max_delta_diff: Maximum delta difference tolerance (default 0.08).
            Set to 0.08 to capture sparse ETH option chain at 53 DTE
            where closest wing is ~0.107 delta (diff 0.057 from target 0.05).
        is_linear: Whether using USDC-settled (linear) options. When True,
            spread widths and premiums are already in USD, no conversion needed.
    """

    short_delta: float = 0.15
    wing_delta: float = 0.05
    max_delta_diff: float = 0.08
    is_linear: bool = False


class IronCondorStrategy(BaseStrategy):
    """Iron Condor: Sell OTM put spread + call spread.

    Structure:
    - Buy OTM put (protection)
    - Sell OTM put (credit)
    - Sell OTM call (credit)
    - Buy OTM call (protection)
    """

    # Minimum IV Rank for entry
    # Calibrated via scripts/analyze_iv_rank_thresholds.py (2026-01-30):
    #   - 60% threshold: 40.9% combined win rate (IV down + price calm)
    #   - ~134 entry opportunities/year
    #   - Previous 50%: only 39.1% win rate
    MIN_IV_RANK = 0.60

    def __init__(self, config: IronCondorConfig) -> None:
        super().__init__(config)
        self.ic_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.IRON_CONDOR

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open iron condor, or None.
        """
        if not self.can_open():
            return None

        # Check IV conditions
        if metrics.iv_rank is None or metrics.iv_rank < self.MIN_IV_RANK:
            return None

        return self._generate_iron_condor_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing iron condor.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to close, or None.
        """
        if not self.state.is_active:
            return None

        # Check DTE — close if any leg is near expiry
        if self.state.contracts:
            now = metrics.timestamp or datetime.now(timezone.utc)
            min_dte = min((c.expiry - now).days for c in self.state.contracts)
            if min_dte <= 7:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",
                    quantity=self.state.position_size,
                    legs_direction=["buy", "sell", "buy", "sell"],
                    reason=f"DTE exit: {min_dte} days remaining",
                )

        # Check profit target using execution prices (ask for shorts, bid for longs).
        # Mark can diverge from execution prices on illiquid testnet, causing
        # false profit triggers that lead to exit-entry loops.
        exec_value = self._get_current_spread_value(option_chain, use_mark=False)
        if exec_value is not None and self.state.premium_received > 0:
            profit_pct = (self.state.premium_received - exec_value) / self.state.premium_received

            if profit_pct >= self.config.profit_target:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",
                    quantity=self.state.position_size,
                    legs_direction=["buy", "sell", "buy", "sell"],
                    reason=f"Profit target: {profit_pct:.1%}",
                )

        # Check loss limit using mark prices. Mark is exchange-computed fair
        # value, immune to illiquid ask spikes that cause false loss triggers.
        mark_value = self._get_current_spread_value(option_chain, use_mark=True)
        if mark_value is not None and self.state.premium_received > 0:
            loss_pct = (self.state.premium_received - mark_value) / self.state.premium_received

            if loss_pct <= -self.config.loss_limit:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",
                    quantity=self.state.position_size,
                    legs_direction=["buy", "sell", "buy", "sell"],
                    reason=f"Loss limit: {loss_pct:.1%}",
                )

        return None

    def _generate_iron_condor_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate 4-leg iron condor signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal with 4 contracts, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
            reference_time=metrics.timestamp,
        )

        # Group options by expiry - all legs must be in same expiry
        by_expiry: dict[str, list[OptionContract]] = {}
        for opt in selector.options:
            expiry_key = opt.expiry.strftime("%Y-%m-%d")
            if expiry_key not in by_expiry:
                by_expiry[expiry_key] = []
            by_expiry[expiry_key].append(opt)

        # Try each expiry to find a valid iron condor
        for expiry_key in sorted(by_expiry.keys()):
            expiry_opts = by_expiry[expiry_key]
            expiry_selector = OptionSelector(expiry_opts)

            # Find put spread: need short put with a valid wing at lower strike
            short_put, long_put = self._find_put_spread(expiry_selector)
            if short_put is None or long_put is None:
                continue

            # Find call spread: need short call with a valid wing at higher strike
            short_call, long_call = self._find_call_spread(expiry_selector)
            if short_call is None or long_call is None:
                continue

            # Found valid iron condor at this expiry
            contracts = [short_put, long_put, short_call, long_call]
            break
        else:
            # No valid iron condor found at any expiry
            logger.debug(
                f"Iron Condor: No valid 4-leg structure found across {len(by_expiry)} expiries"
            )
            return None

        contracts = [short_put, long_put, short_call, long_call]
        legs_direction = ["sell", "buy", "sell", "buy"]

        # Calculate max profit (net credit) and max loss
        net_credit = self._calculate_net_credit(contracts, legs_direction)

        # IC must collect positive credit to be valid
        if net_credit <= 0:
            return None

        max_loss = self._calculate_max_loss(contracts, net_credit, metrics.btc_price)

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=contracts,
            direction="sell",
            quantity=self.config.max_position_size,
            legs_direction=legs_direction,
            reason=f"Iron condor: IV Rank {metrics.iv_rank:.1%}, short deltas ±{self.ic_config.short_delta}",
            max_profit=net_credit,
            max_loss=max_loss,
        )

    def _find_put_spread(
        self,
        selector: OptionSelector,
    ) -> tuple[Optional[OptionContract], Optional[OptionContract]]:
        """Find valid put spread (short put + wing at lower strike).

        Iterates through all valid short put candidates to find one
        that has a valid wing option at a lower strike.

        Args:
            selector: Option selector with DTE-filtered options.

        Returns:
            Tuple of (short_put, long_put) or (None, None) if no valid spread.
        """
        puts = [
            opt for opt in selector.options
            if opt.option_type == "put" and opt.delta is not None
        ]

        # Find all candidates for short put (within tolerance of target delta)
        # Short put requires bid > 0 (to sell) AND ask > 0 (to buy back later)
        short_candidates = [
            opt for opt in puts
            if abs((opt.delta or 0) - (-self.ic_config.short_delta)) <= self.ic_config.max_delta_diff
            and (opt.bid or 0) > 0  # Liquidity check: need a bid to sell
            and (opt.ask or 0) > 0  # Liquidity check: need an ask to buy back
        ]

        # Sort by distance from target (best first)
        short_candidates.sort(key=lambda o: abs((o.delta or 0) - (-self.ic_config.short_delta)))

        # For each short candidate, try to find a valid wing
        for short_put in short_candidates:
            # Wing must be at lower strike and have ask > 0 (we're buying)
            wing_candidates = [
                opt for opt in puts
                if opt.strike < short_put.strike and (opt.ask or 0) > 0
            ]
            if not wing_candidates:
                continue

            # Find wing closest to target delta
            wing_candidates.sort(key=lambda o: abs((o.delta or 0) - (-self.ic_config.wing_delta)))
            best_wing = wing_candidates[0]

            if abs((best_wing.delta or 0) - (-self.ic_config.wing_delta)) <= self.ic_config.max_delta_diff:
                return short_put, best_wing

        return None, None

    def _find_call_spread(
        self,
        selector: OptionSelector,
    ) -> tuple[Optional[OptionContract], Optional[OptionContract]]:
        """Find valid call spread (short call + wing at higher strike).

        Iterates through all valid short call candidates to find one
        that has a valid wing option at a higher strike.

        Args:
            selector: Option selector with DTE-filtered options.

        Returns:
            Tuple of (short_call, long_call) or (None, None) if no valid spread.
        """
        calls = [
            opt for opt in selector.options
            if opt.option_type == "call" and opt.delta is not None
        ]

        # Find all candidates for short call (within tolerance of target delta)
        # Short call requires bid > 0 (to sell) AND ask > 0 (to buy back later)
        short_candidates = [
            opt for opt in calls
            if abs((opt.delta or 0) - self.ic_config.short_delta) <= self.ic_config.max_delta_diff
            and (opt.bid or 0) > 0  # Liquidity check: need a bid to sell
            and (opt.ask or 0) > 0  # Liquidity check: need an ask to buy back
        ]

        # Sort by distance from target (best first)
        short_candidates.sort(key=lambda o: abs((o.delta or 0) - self.ic_config.short_delta))

        # For each short candidate, try to find a valid wing
        for short_call in short_candidates:
            # Wing must be at higher strike and have ask > 0 (we're buying)
            wing_candidates = [
                opt for opt in calls
                if opt.strike > short_call.strike and (opt.ask or 0) > 0
            ]
            if not wing_candidates:
                continue

            # Find wing closest to target delta
            wing_candidates.sort(key=lambda o: abs((o.delta or 0) - self.ic_config.wing_delta))
            best_wing = wing_candidates[0]

            if abs((best_wing.delta or 0) - self.ic_config.wing_delta) <= self.ic_config.max_delta_diff:
                return short_call, best_wing

        return None, None

    def _calculate_net_credit(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
    ) -> float:
        """Calculate net credit received.

        Args:
            contracts: The 4 contracts.
            legs_direction: Direction for each leg.

        Returns:
            Net credit (positive = credit).
        """
        total = 0.0
        for contract, direction in zip(contracts, legs_direction, strict=True):
            if direction == "sell":
                # Selling: we receive the bid price (what buyer pays us)
                price = contract.bid or contract.mid_price or 0
                total += price
            else:
                # Buying: we pay the ask price (what seller charges us)
                price = contract.ask or contract.mid_price or 0
                total -= price
        return total

    def _calculate_max_loss(
        self,
        contracts: list[OptionContract],
        net_credit: float,
        spot_price: float,
    ) -> float:
        """Calculate maximum loss.

        Max loss = width of widest spread - net credit

        For inverse options, spread width (USD) must be converted to the
        settlement currency using spot_price. For linear (USDC) options,
        both width and credit are already in USD.

        Args:
            contracts: The 4 contracts.
            net_credit: Net credit received.
            spot_price: Current spot price for USD-to-crypto conversion (inverse only).

        Returns:
            Maximum loss in settlement currency units.
        """
        # Put spread width
        put_width = abs(contracts[0].strike - contracts[1].strike)
        # Call spread width
        call_width = abs(contracts[3].strike - contracts[2].strike)

        max_spread_width = max(put_width, call_width)

        if self.ic_config.is_linear:
            # Linear (USDC): width and credit both in USD
            return max_spread_width - net_credit
        else:
            # Inverse: convert USD width to crypto using spot price
            width_in_btc = max_spread_width / spot_price
            return width_in_btc - net_credit

    def _get_current_spread_value(
        self,
        option_chain: list[OptionContract],
        use_mark: bool = True,
    ) -> Optional[float]:
        """Get current value of the spread.

        Args:
            option_chain: Current option chain.
            use_mark: If True, use mark_price (for loss monitoring).
                If False, use execution prices — ask for buying back
                short legs, bid for selling long legs (for profit target).

        Returns:
            Current value to close the spread.
        """
        if len(self.state.contracts) != 4:
            return None

        # Build lookup by instrument name for exact matching
        chain_by_name = {opt.instrument_name: opt for opt in option_chain}
        total = 0.0

        legs_direction = ["sell", "buy", "sell", "buy"]

        qty = self.state.position_size or 1.0

        for contract, direction in zip(self.state.contracts, legs_direction, strict=True):
            # Match by instrument name to ensure same expiry
            current = chain_by_name.get(contract.instrument_name)
            if current is None:
                logger.debug(
                    f"Iron Condor: {contract.instrument_name} not found in chain, "
                    f"profit target check skipped"
                )
                return None

            if use_mark:
                # Mark for loss monitoring — immune to illiquid bid/ask spikes
                price = current.mark_price or current.mid_price or 0
            else:
                # Execution prices for profit target — reflects actual close cost.
                # Short legs: buy back at ask. Long legs: sell at bid.
                if direction == "sell":
                    price = current.ask or current.mark_price or current.mid_price or 0
                else:
                    price = current.bid or current.mark_price or current.mid_price or 0

            if direction == "sell":
                total += price * qty  # Cost to buy back
            else:
                total -= price * qty  # Credit from selling
        return total
