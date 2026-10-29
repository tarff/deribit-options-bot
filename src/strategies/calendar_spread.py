"""Calendar Spread strategy implementation.

Calendar Spread (horizontal spread) profits from time decay differential:
- Sell near-dated ATM option (high theta decay)
- Buy far-dated ATM option at same strike (slower decay)
- Profits when underlying stays near strike and/or IV rises

Entry: NEUTRAL regime when IV Rank is below the Calendar threshold
       (cash-settled neutral strategy; Wheel is retired for Deribit options)
Exit: 25% profit, short leg expires, or underlying moves too far
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.strategies.base import BaseStrategy, StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class CalendarSpreadConfig(StrategyConfig):
    """Configuration specific to Calendar Spread strategy.

    Attributes:
        max_iv_rank: Maximum IV Rank for entry (below this = low IV environment).
            Calibrated via scripts/calibrate_calendar_spread.py on 999 days of
            ETH data (2023-2026). 20% threshold appears in 40% of top-20 results
            by Sharpe ratio. Lower threshold = more selective entries.
        short_dte_min: Minimum DTE for short (front) leg.
        short_dte_max: Maximum DTE for short (front) leg.
        long_dte_min: Minimum DTE for long (back) leg.
        long_dte_max: Maximum DTE for long (back) leg.
            DTE ranges validated: 14-21 short + 45-60 long appears in 55% of
            top-20 results. Provides good theta differential.
        option_type: Type of options to use ('put' or 'call').
        max_strike_distance_pct: Max distance from ATM as % of underlying.
        exit_price_move_pct: Exit if price moves this far from strike.
            Calibrated: 12% appears in 60% of top-20 results by Sharpe.
            At 12%, positions exit before theta edge diminishes significantly.
        profit_target: Target profit as multiple of initial debit.
            Calibrated: 25% (0.25) appears in 40% of top-20 results.
            Lower target captures gains more reliably than 50%+.
    """

    max_iv_rank: float = 0.20  # Entry when IV Rank below 20% (calibrated)
    short_dte_min: int = 14
    short_dte_max: int = 21
    long_dte_min: int = 45
    long_dte_max: int = 60
    option_type: str = "put"  # Use puts by default (slight downside bias)
    max_strike_distance_pct: float = 0.02  # Strike within 2% of spot
    exit_price_move_pct: float = 0.12  # Exit if price moves >12% (calibrated)
    profit_target: float = 0.25  # 25% profit target (calibrated)


class CalendarSpreadStrategy(BaseStrategy):
    """Calendar Spread: Sell front-month, buy back-month at same strike.

    Phases:
    - 'open': Initial position with both legs active
    - 'long_only': Short leg expired, holding long leg
    """

    def __init__(self, config: CalendarSpreadConfig) -> None:
        super().__init__(config)
        self.cs_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.CALENDAR_SPREAD

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal.

        Entry conditions:
        - Not already in position
        - IV Rank below threshold (low IV environment)

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open calendar spread, or None.
        """
        if not self.can_open():
            return None

        # Check IV conditions - enter when IV is LOW (opposite of premium sellers)
        if metrics.iv_rank is None:
            return None

        if metrics.iv_rank >= self.cs_config.max_iv_rank:
            # IV is high enough for premium selling, don't use calendar
            return None

        return self._generate_calendar_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing calendar spread.

        Exit conditions:
        - Profit target reached
        - Short leg expired (close or roll)
        - Underlying moved too far from strike

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to close/adjust, or None.
        """
        if not self.state.is_active:
            return None

        # Check if short leg has expired
        if self._short_leg_expired(metrics):
            # Only close the long leg — the short leg no longer exists on
            # the exchange, and submitting a close order for an expired
            # instrument fails with 'Invalid params' and strands the long.
            return self._generate_close_long_only_signal("Short leg expired")

        # Check profit target using execution prices (bid/ask).
        # Mark can diverge from execution prices on illiquid testnet.
        current_value = self._get_current_spread_value(option_chain, use_mark=False)
        if current_value is not None:
            # For calendar spreads, we pay a debit to open. Include entry fees
            # in the cost basis so the strategy-side profit target matches the
            # realized PnL calculation in paper_trading._execute_signal (which
            # deducts both entry and close fees).
            initial_debit = abs(self.state.premium_received) + self.state.entry_fees
            if initial_debit > 0:
                profit_pct = (current_value - initial_debit) / initial_debit

                if profit_pct >= self.cs_config.profit_target:
                    return self._generate_close_signal(
                        f"Profit target: {profit_pct:.1%} >= {self.cs_config.profit_target:.1%}"
                    )

        # Check if underlying moved too far from strike
        short_leg = self._get_short_leg()
        if short_leg is not None and metrics.btc_price:
            strike = short_leg.strike
            distance_pct = abs(metrics.btc_price - strike) / strike

            if distance_pct > self.cs_config.exit_price_move_pct:
                return self._generate_close_signal(
                    f"Price moved {distance_pct:.1%} from strike"
                )

        return None

    def _generate_calendar_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate calendar spread entry signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal with 2 contracts (short front, long back), or None.
        """
        now = metrics.timestamp or datetime.now(timezone.utc)
        option_type = self.cs_config.option_type

        # Find ATM strike (closest to current price)
        atm_strike = self._find_atm_strike(metrics.btc_price, option_chain)
        if atm_strike is None:
            return None

        # Find short (front-month) leg
        short_leg = self._find_leg(
            option_chain=option_chain,
            strike=atm_strike,
            option_type=option_type,
            dte_min=self.cs_config.short_dte_min,
            dte_max=self.cs_config.short_dte_max,
            reference_time=now,
        )
        if short_leg is None:
            return None

        # Find long (back-month) leg at same strike
        long_leg = self._find_leg(
            option_chain=option_chain,
            strike=atm_strike,
            option_type=option_type,
            dte_min=self.cs_config.long_dte_min,
            dte_max=self.cs_config.long_dte_max,
            reference_time=now,
        )
        if long_leg is None:
            return None

        # Ensure legs have different expiries
        if short_leg.expiry >= long_leg.expiry:
            return None

        contracts = [short_leg, long_leg]
        legs_direction = ["sell", "buy"]

        # Log selected contracts for debugging
        logger.info(
            f"Calendar legs: short={short_leg.instrument_name} (bid={short_leg.bid}, ask={short_leg.ask}), "
            f"long={long_leg.instrument_name} (bid={long_leg.bid}, ask={long_leg.ask})"
        )

        # Calculate net debit (long costs more than short credit)
        net_debit = self._calculate_net_debit(contracts, legs_direction)

        # Calendar spread must pay debit (long leg costs more than short credit)
        if net_debit <= 0:
            logger.warning(
                f"Calendar spread debit={net_debit:.6f} invalid (should be > 0). "
                f"Short={short_leg.instrument_name} mid={short_leg.mid_price}, "
                f"Long={long_leg.instrument_name} mid={long_leg.mid_price}"
            )
            return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=contracts,
            direction="buy",  # Net debit position
            quantity=self.config.max_position_size,
            legs_direction=legs_direction,
            reason=f"Calendar spread: IV Rank {metrics.iv_rank:.1%} (low IV), strike ${atm_strike:,.0f}",
            max_loss=net_debit,  # Max loss is the debit paid
        )

    def _find_atm_strike(
        self,
        price: float,
        option_chain: list[OptionContract],
    ) -> Optional[float]:
        """Find the ATM strike closest to current price.

        Args:
            price: Current underlying price.
            option_chain: Available options.

        Returns:
            Strike price, or None.
        """
        if not option_chain:
            return None

        # Get unique strikes
        strikes = sorted(set(c.strike for c in option_chain))
        if not strikes:
            return None

        # Find closest to price within max distance
        max_distance = price * self.cs_config.max_strike_distance_pct
        best_strike = None
        min_diff = float('inf')

        for strike in strikes:
            diff = abs(strike - price)
            if diff < min_diff and diff <= max_distance:
                min_diff = diff
                best_strike = strike

        # If no strike within range, don't fall back to arbitrary strike
        return best_strike

    def _find_leg(
        self,
        option_chain: list[OptionContract],
        strike: float,
        option_type: str,
        dte_min: int,
        dte_max: int,
        reference_time: datetime,
    ) -> Optional[OptionContract]:
        """Find an option leg matching criteria.

        Args:
            option_chain: Available options.
            strike: Target strike price.
            option_type: 'put' or 'call'.
            dte_min: Minimum DTE.
            dte_max: Maximum DTE.
            reference_time: Current time for DTE calculation.

        Returns:
            OptionContract matching criteria, or None.
        """
        candidates = []

        for contract in option_chain:
            # Check strike, type, and valid pricing
            if contract.strike != strike or contract.option_type != option_type:
                continue
            if (contract.mid_price or 0) <= 0:
                continue

            # Check DTE
            dte = (contract.expiry - reference_time).days
            if dte < dte_min or dte > dte_max:
                continue

            candidates.append((contract, dte))

        if not candidates:
            return None

        # Return the one closest to middle of DTE range
        target_dte = (dte_min + dte_max) // 2
        return min(candidates, key=lambda x: abs(x[1] - target_dte))[0]

    def _calculate_net_debit(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
    ) -> float:
        """Calculate net debit paid to open the spread.

        Args:
            contracts: The 2 contracts [short, long].
            legs_direction: Direction for each leg.

        Returns:
            Net debit (positive = debit paid).
        """
        total = 0.0
        for contract, direction in zip(contracts, legs_direction, strict=True):
            if direction == "sell":
                # Selling: we receive the bid price
                price = contract.bid or contract.mid_price or 0
                total -= price  # Credit received
            else:
                # Buying: we pay the ask price
                price = contract.ask or contract.mid_price or 0
                total += price  # Debit paid
        return total

    def _short_leg_expired(self, metrics: MarketMetrics) -> bool:
        """Check if short leg has expired.

        Args:
            metrics: Current market metrics (uses timestamp for backtest compatibility).

        Returns:
            True if short leg is past expiry.
        """
        short_leg = self._get_short_leg()
        if short_leg is None:
            return False

        now = metrics.timestamp or datetime.now(timezone.utc)
        return now >= short_leg.expiry

    def _get_short_leg(self) -> Optional[OptionContract]:
        """Return the front-month leg by expiry, independent of list order."""
        if not self.state.contracts:
            return None
        return min(self.state.contracts, key=lambda c: c.expiry)

    def _get_long_leg(self) -> Optional[OptionContract]:
        """Return the back-month leg by expiry, independent of list order."""
        if not self.state.contracts:
            return None
        return max(self.state.contracts, key=lambda c: c.expiry)

    def _get_current_spread_value(
        self,
        option_chain: list[OptionContract],
        use_mark: bool = True,
    ) -> Optional[float]:
        """Get current value of the calendar spread.

        Args:
            option_chain: Current option chain.
            use_mark: If True, use mark_price (for loss monitoring).
                If False, use execution prices — bid for selling long
                leg, ask for buying back short leg (for profit target).

        Returns:
            Current spread value, or None.
        """
        if len(self.state.contracts) != 2:
            return None

        short_contract = self._get_short_leg()
        long_contract = self._get_long_leg()
        if short_contract is None or long_contract is None:
            return None

        # Find current prices
        short_current = None
        long_current = None

        for contract in option_chain:
            if (contract.strike == short_contract.strike and
                contract.option_type == short_contract.option_type):
                # Match by expiry date
                if contract.expiry.date() == short_contract.expiry.date():
                    short_current = contract
                elif contract.expiry.date() == long_contract.expiry.date():
                    long_current = contract

        if short_current is None or long_current is None:
            # Log which leg(s) couldn't be found for debugging
            missing = []
            if short_current is None:
                missing.append(f"short ({short_contract.instrument_name})")
            if long_current is None:
                missing.append(f"long ({long_contract.instrument_name})")
            logger.warning(
                f"Cannot calculate spread value - missing {', '.join(missing)} in option chain. "
                f"Profit target check skipped."
            )
            return None

        qty = self.state.position_size or 1.0

        if use_mark:
            # Mark for loss monitoring — immune to illiquid bid/ask spikes
            short_price = self._first_available_price(
                short_current.mark_price,
                short_current.mid_price,
                0,
            )
            long_price = self._first_available_price(
                long_current.mark_price,
                long_current.mid_price,
                0,
            )
        else:
            # Execution prices for profit target:
            # Short leg: buy back at ask. Long leg: sell at bid.
            short_price = self._first_available_price(
                short_current.ask,
                short_current.mark_price,
                short_current.mid_price,
                0,
            )
            long_price = self._first_available_price(
                long_current.bid,
                long_current.mark_price,
                long_current.mid_price,
                0,
            )

        # Value = long price - short price (what we'd net closing)
        return (long_price - short_price) * qty

    def _first_available_price(self, *prices: Optional[float]) -> float:
        """Return the first non-None price, preserving legitimate zero prices."""
        for price in prices:
            if price is not None:
                return price
        return 0.0

    def _generate_close_signal(self, reason: str) -> TradeSignal:
        """Generate close signal for both legs.

        Args:
            reason: Reason for closing.

        Returns:
            Close signal.
        """
        contracts = sorted(self.state.contracts, key=lambda c: c.expiry)
        legs_direction = ["buy", "sell"] if len(contracts) == 2 else ["sell"] * len(contracts)
        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=contracts,
            direction="sell",  # Net sell to close
            quantity=self.state.position_size,
            legs_direction=legs_direction,
            reason=reason,
        )

    def _generate_close_long_only_signal(self, reason: str) -> TradeSignal:
        """Generate close signal for the long leg only.

        Used when the short leg has expired naturally on the exchange.
        """
        if not self.state.contracts:
            return self._generate_close_signal(reason)
        long_leg = self._get_long_leg()
        if long_leg is None:
            return self._generate_close_signal(reason)
        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=[long_leg],
            direction="sell",
            quantity=self.state.position_size,
            legs_direction=["sell"],
            reason=reason,
        )
