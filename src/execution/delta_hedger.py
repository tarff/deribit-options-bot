"""Delta hedger for maintaining delta-neutral positions."""

from dataclasses import dataclass
from typing import Optional

from src.brain.signal import OptionContract


@dataclass
class HedgerConfig:
    """Configuration for delta hedger.

    Attributes:
        rebalance_threshold: Rebalance when |delta| exceeds this.
        hard_limit: Never let |delta| exceed this (urgent hedge).
    """

    rebalance_threshold: float = 0.10
    hard_limit: float = 0.15


@dataclass
class HedgeSignal:
    """Signal to execute a delta hedge.

    Attributes:
        direction: 'buy' or 'sell' BTC/perpetual.
        quantity: Amount of BTC to trade.
        target_delta: Target portfolio delta after hedge.
        urgent: True if delta exceeds hard limit.
        reason: Explanation for hedge.
    """

    direction: str
    quantity: float
    target_delta: float = 0.0
    urgent: bool = False
    reason: str = ""


class DeltaHedger:
    """Monitors portfolio delta and generates hedge signals.

    Uses perpetual futures for hedging (better liquidity than spot).
    """

    def __init__(self, config: HedgerConfig) -> None:
        """Initialize delta hedger.

        Args:
            config: Hedger configuration.
        """
        self.config = config

    def calculate_portfolio_delta(
        self,
        contracts: list[OptionContract],
        direction: str,
        quantity: float = 1.0,
    ) -> float:
        """Calculate portfolio delta for uniformly directional position.

        For a position where all legs have the same direction:
        - Long position: position_delta = sum(contract_deltas) * quantity
        - Short position: position_delta = -sum(contract_deltas) * quantity

        Args:
            contracts: List of option contracts.
            direction: Overall position direction ('buy' or 'sell').
            quantity: Position size in BTC (default 1.0).

        Returns:
            Portfolio delta (delta exposure = delta * quantity).
        """
        contract_delta_sum = sum(
            c.delta for c in contracts if c.delta is not None
        )

        if direction == "sell":
            return -contract_delta_sum * quantity
        return contract_delta_sum * quantity

    def calculate_portfolio_delta_with_legs(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
        quantity: float = 1.0,
    ) -> float:
        """Calculate portfolio delta for multi-leg position.

        Each leg can have its own direction:
        - Long leg: position_delta = contract_delta * quantity
        - Short leg: position_delta = -contract_delta * quantity

        Args:
            contracts: List of option contracts.
            legs_direction: Direction for each leg ('buy' or 'sell').
            quantity: Position size in BTC (default 1.0).

        Returns:
            Portfolio delta (delta exposure = delta * quantity).
        """
        total_delta = 0.0

        for contract, direction in zip(contracts, legs_direction, strict=True):
            if contract.delta is None:
                continue

            if direction == "sell":
                total_delta -= contract.delta
            else:
                total_delta += contract.delta

        return total_delta * quantity

    def check_hedge_needed(
        self,
        portfolio_delta: float,
        existing_hedge_delta: float = 0.0,
    ) -> Optional[HedgeSignal]:
        """Check if delta hedge is needed.

        Args:
            portfolio_delta: Current portfolio delta from options.
            existing_hedge_delta: Delta from existing hedge positions.

        Returns:
            HedgeSignal if hedge needed, None otherwise.
        """
        net_delta = portfolio_delta + existing_hedge_delta

        if abs(net_delta) <= self.config.rebalance_threshold:
            return None

        # Determine hedge direction and size
        if net_delta > 0:
            # Long delta -> sell to reduce
            direction = "sell"
        else:
            # Short delta -> buy to reduce
            direction = "buy"

        quantity = abs(net_delta)
        urgent = abs(net_delta) > self.config.hard_limit

        reason = f"Portfolio delta {net_delta:+.3f} exceeds threshold"
        if urgent:
            reason = f"URGENT: Portfolio delta {net_delta:+.3f} exceeds hard limit"

        return HedgeSignal(
            direction=direction,
            quantity=quantity,
            target_delta=0.0,
            urgent=urgent,
            reason=reason,
        )
