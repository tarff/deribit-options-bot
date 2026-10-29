"""Position tracking for backtesting."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.brain.signal import OptionContract, StrategyType, TradeSignal


@dataclass
class BacktestPosition:
    """Represents an open position in backtest.

    Attributes:
        position_id: Unique identifier.
        strategy_type: Strategy that opened this position.
        contracts: Option contracts in the position.
        legs_direction: Direction per leg ('buy' or 'sell').
        entry_price: Spot price at entry.
        entry_premium: Net premium (positive=credit).
        entry_time: When position was opened.
        quantity: Position size in BTC.
        max_profit: Maximum profit if applicable.
        max_loss: Maximum loss if applicable.
    """

    position_id: str
    strategy_type: StrategyType
    contracts: list[OptionContract]
    legs_direction: list[str]
    entry_price: float
    entry_premium: float
    entry_time: datetime
    quantity: float
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None


@dataclass
class ClosedTrade:
    """Record of a closed trade."""

    position_id: str
    strategy_type: StrategyType
    entry_time: datetime
    exit_time: datetime
    entry_premium: float
    exit_premium: float
    quantity: float
    pnl: float
    commission: float


class PositionTracker:
    """Tracks open positions and calculates P&L for backtesting."""

    def __init__(self, commission_pct: float = 0.0005) -> None:
        """Initialize position tracker.

        Args:
            commission_pct: Commission as fraction of notional.
        """
        self.commission_pct = commission_pct
        self.positions: dict[str, BacktestPosition] = {}
        self.closed_trades: list[ClosedTrade] = []
        self._next_id = 1

    def open_position(
        self,
        signal: TradeSignal,
        spot_price: float,
        timestamp: datetime,
    ) -> str:
        """Open a new position from a trade signal.

        Args:
            signal: Trade signal with contracts and direction.
            spot_price: Current spot price.
            timestamp: Current timestamp.

        Returns:
            Position ID of the new position.

        Raises:
            ValueError: If signal quantity is zero or negative.
        """
        if signal.quantity <= 0:
            raise ValueError(f"Signal quantity must be positive, got {signal.quantity}")

        position_id = f"pos_{self._next_id}"
        self._next_id += 1

        # Calculate entry premium (net credit/debit)
        entry_premium = self._calculate_net_premium(
            signal.contracts,
            signal.legs_direction or [signal.direction] * len(signal.contracts),
        )

        position = BacktestPosition(
            position_id=position_id,
            strategy_type=signal.strategy_type,
            contracts=signal.contracts.copy(),
            legs_direction=signal.legs_direction or [signal.direction] * len(signal.contracts),
            entry_price=spot_price,
            entry_premium=entry_premium,
            entry_time=timestamp,
            quantity=signal.quantity,
            max_profit=signal.max_profit,
            max_loss=signal.max_loss,
        )

        self.positions[position_id] = position
        return position_id

    def close_position(
        self,
        position_id: str,
        current_chain: list[OptionContract],
        spot_price: float,
        timestamp: datetime,
    ) -> float:
        """Close a position and return realized P&L.

        Args:
            position_id: ID of position to close.
            current_chain: Current option chain for pricing.
            spot_price: Current spot price.
            timestamp: Current timestamp.

        Returns:
            Realized P&L in BTC.
        """
        if position_id not in self.positions:
            return 0.0

        position = self.positions[position_id]

        # Find matching contracts in current chain and get exit premium
        exit_premium = self._get_exit_premium(position, current_chain, spot_price)

        # Calculate P&L: entry_premium - exit_premium (for short positions)
        # If we sold (credit), entry_premium is positive
        # Exit premium is cost to close (negative for buyer = positive value)
        gross_pnl = (position.entry_premium - exit_premium) * position.quantity

        # Calculate commission per-leg (not on net premium)
        # Each leg's notional contributes independently to commission
        per_leg_entry = sum(
            abs(c.mid_price or 0) for c in position.contracts
        )
        per_leg_exit = self._get_per_leg_exit_total(position, current_chain)
        commission = (per_leg_entry + per_leg_exit) * position.quantity * self.commission_pct

        net_pnl = gross_pnl - commission

        # Record closed trade
        trade = ClosedTrade(
            position_id=position_id,
            strategy_type=position.strategy_type,
            entry_time=position.entry_time,
            exit_time=timestamp,
            entry_premium=position.entry_premium,
            exit_premium=exit_premium,
            quantity=position.quantity,
            pnl=net_pnl,
            commission=commission,
        )
        self.closed_trades.append(trade)

        # Remove from open positions
        del self.positions[position_id]

        return net_pnl

    def mark_to_market(
        self,
        current_chain: list[OptionContract],
        spot_price: float,
    ) -> float:
        """Calculate total unrealized P&L for all open positions.

        Args:
            current_chain: Current option chain for pricing.
            spot_price: Current spot price.

        Returns:
            Total unrealized P&L in BTC.
        """
        total_unrealized = 0.0

        for position in self.positions.values():
            exit_premium = self._get_exit_premium(position, current_chain)
            unrealized = (position.entry_premium - exit_premium) * position.quantity
            total_unrealized += unrealized

        return total_unrealized

    def get_exposure(self, capital: float, btc_price: float) -> float:
        """Calculate current exposure as fraction of capital.

        Args:
            capital: Current capital in USD.
            btc_price: Current BTC price.

        Returns:
            Exposure as fraction (0.0 to 1.0+).
        """
        if capital <= 0:
            return 0.0

        total_exposure_usd = 0.0
        for position in self.positions.values():
            # Notional = quantity * BTC price
            notional = position.quantity * btc_price
            total_exposure_usd += notional

        return total_exposure_usd / capital

    def _calculate_net_premium(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
    ) -> float:
        """Calculate net premium for a set of contracts."""
        total = 0.0
        for contract, direction in zip(contracts, legs_direction, strict=True):
            mid = contract.mid_price or 0.0
            if direction == "sell":
                total += mid  # Credit
            else:
                total -= mid  # Debit
        return total

    def _get_exit_premium(
        self,
        position: BacktestPosition,
        current_chain: list[OptionContract],
        spot_price: float = 0.0,
    ) -> float:
        """Get exit premium by matching position contracts to current chain."""
        # Key includes expiry date to avoid collision between same strike/type
        # with different expiries
        chain_by_key: dict[tuple[float, str, datetime], OptionContract] = {}
        for c in current_chain:
            key = (c.strike, c.option_type, c.expiry)
            chain_by_key[key] = c

        total = 0.0
        for contract, direction in zip(
            position.contracts, position.legs_direction, strict=True
        ):
            key = (contract.strike, contract.option_type, contract.expiry)
            current = chain_by_key.get(key)

            if current:
                mid = current.mid_price or 0.0
            elif spot_price > 0:
                # Expired or missing: use intrinsic value
                if contract.option_type == "call":
                    mid = max(0.0, (spot_price - contract.strike) / spot_price)
                else:
                    mid = max(0.0, (contract.strike - spot_price) / spot_price)
            else:
                # Fallback: use original contract's mark
                mid = contract.mid_price or 0.0

            # Exit is opposite of entry direction
            if direction == "sell":
                total -= mid  # Buying to close costs money
            else:
                total += mid  # Selling to close gives credit

        # Return as positive value representing cost to close
        return -total

    def _get_per_leg_exit_total(
        self,
        position: BacktestPosition,
        current_chain: list[OptionContract],
    ) -> float:
        """Get sum of absolute per-leg exit prices for commission calculation."""
        chain_by_key: dict[tuple[float, str, datetime], OptionContract] = {}
        for c in current_chain:
            key = (c.strike, c.option_type, c.expiry)
            chain_by_key[key] = c

        total = 0.0
        for contract in position.contracts:
            key = (contract.strike, contract.option_type, contract.expiry)
            current = chain_by_key.get(key)
            mid = (current.mid_price or 0.0) if current else (contract.mid_price or 0.0)
            total += abs(mid)
        return total
