"""Trading signal models for strategy execution."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalAction(str, Enum):
    """Action type for a trade signal."""

    OPEN = "open"
    CLOSE = "close"
    ADJUST = "adjust"
    HEDGE = "hedge"


class StrategyType(str, Enum):
    """Strategy types."""

    WHEEL = "wheel"
    IRON_CONDOR = "iron_condor"
    VOL_ARB = "vol_arb"
    GAMMA_SCALP = "gamma_scalp"
    CALENDAR_SPREAD = "calendar_spread"


@dataclass
class OptionContract:
    """Option contract details from order book.

    Attributes:
        instrument_name: Deribit instrument name (e.g., BTC-31JAN26-95000-P).
        strike: Strike price in USD.
        expiry: Expiration datetime (UTC).
        option_type: 'call' or 'put'.
        delta: Option delta (-1 to 1).
        gamma: Option gamma.
        theta: Option theta (daily decay).
        vega: Option vega.
        iv: Implied volatility (percentage).
        bid: Best bid price (inverse: crypto units, linear: USDC).
        ask: Best ask price (inverse: crypto units, linear: USDC).
        mark_price: Mark price (inverse: crypto units, linear: USDC).
    """

    instrument_name: str
    strike: float
    expiry: datetime
    option_type: str  # 'call' or 'put'
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mark_price: Optional[float] = None

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate mid price from bid/ask."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.mark_price


@dataclass
class TradeSignal:
    """Signal to execute a trade.

    Attributes:
        strategy_type: Which strategy generated this signal.
        action: OPEN, CLOSE, ADJUST, or HEDGE.
        contracts: List of option contracts involved.
        direction: Overall direction ('buy' or 'sell').
        quantity: Position size in BTC.
        legs_direction: Per-leg direction for multi-leg strategies.
        reason: Human-readable reason for signal.
        target_delta: Target delta for hedging signals.
        max_loss: Maximum loss for the position.
        max_profit: Maximum profit for the position.
    """

    strategy_type: StrategyType
    action: SignalAction
    contracts: list[OptionContract]
    direction: str  # 'buy' or 'sell' overall
    quantity: float
    legs_direction: Optional[list[str]] = None
    reason: str = ""
    target_delta: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None

    @property
    def net_premium(self) -> Optional[float]:
        """Calculate net premium for the signal.

        Positive = credit received, Negative = debit paid.
        """
        if not self.contracts:
            return None

        directions = self.legs_direction or [self.direction] * len(self.contracts)

        total = 0.0
        for contract, leg_dir in zip(self.contracts, directions, strict=True):
            mid = contract.mid_price
            if mid is None:
                return None
            if leg_dir == "sell":
                total += mid
            else:
                total -= mid

        return total
