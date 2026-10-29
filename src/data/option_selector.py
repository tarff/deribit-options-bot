"""Option selection helpers for finding appropriate strikes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.brain.signal import OptionContract


@dataclass
class OptionSelector:
    """Helper for selecting options from a chain.

    Filters and finds options by delta, strike, DTE, etc.
    """

    options: list[OptionContract]

    def find_by_delta(
        self,
        target_delta: float,
        option_type: str,
        max_delta_diff: float = 0.10,
    ) -> Optional[OptionContract]:
        """Find option closest to target delta.

        Args:
            target_delta: Target delta (negative for puts, positive for calls).
            option_type: 'put' or 'call'.
            max_delta_diff: Maximum allowed difference from target.

        Returns:
            Option closest to target delta, or None if none within threshold.
        """
        candidates = [
            opt for opt in self.options
            if opt.option_type == option_type and opt.delta is not None
        ]

        if not candidates:
            return None

        # Sort by distance from target delta, then by strike for determinism
        candidates.sort(key=lambda o: (abs((o.delta or 0) - target_delta), o.strike))

        best = candidates[0]
        if abs((best.delta or 0) - target_delta) <= max_delta_diff:
            return best

        return None

    def find_matching_straddle(
        self,
        target_put_delta: float = -0.50,
        target_call_delta: float = 0.50,
        max_delta_diff: float = 0.10,
    ) -> Optional[tuple[OptionContract, OptionContract]]:
        """Find a liquid put/call pair with the same strike and expiry.

        Args:
            target_put_delta: Target delta for the put leg.
            target_call_delta: Target delta for the call leg.
            max_delta_diff: Maximum allowed difference from either target.

        Returns:
            Tuple of (put, call), or None if no matching straddle is found.
        """
        puts_by_key: dict[tuple[datetime, float], OptionContract] = {}
        for opt in self.options:
            if (
                opt.option_type != "put"
                or opt.delta is None
                or abs(opt.delta - target_put_delta) > max_delta_diff
                or opt.bid is None
                or opt.bid <= 0
                or opt.ask is None
                or opt.ask <= 0
            ):
                continue

            key = (opt.expiry, opt.strike)
            existing = puts_by_key.get(key)
            existing_delta = existing.delta if existing is not None else None
            if existing is None or existing_delta is None or abs(
                opt.delta - target_put_delta
            ) < abs(existing_delta - target_put_delta):
                puts_by_key[key] = opt

        candidates: list[tuple[float, OptionContract, OptionContract]] = []
        for call in self.options:
            if (
                call.option_type != "call"
                or call.delta is None
                or abs(call.delta - target_call_delta) > max_delta_diff
                or call.bid is None
                or call.bid <= 0
                or call.ask is None
                or call.ask <= 0
            ):
                continue

            put = puts_by_key.get((call.expiry, call.strike))
            if put is None or put.delta is None:
                continue

            score = abs(put.delta - target_put_delta) + abs(call.delta - target_call_delta)
            candidates.append((score, put, call))

        if not candidates:
            return None

        _, put, call = min(
            candidates,
            key=lambda item: (item[0], item[1].expiry, item[1].strike),
        )
        return put, call

    def find_by_strike(
        self,
        target_strike: float,
        option_type: str,
    ) -> Optional[OptionContract]:
        """Find option at exact strike.

        Args:
            target_strike: Target strike price.
            option_type: 'put' or 'call'.

        Returns:
            Option at strike, or None if not found.
        """
        for opt in self.options:
            if opt.option_type == option_type and opt.strike == target_strike:
                return opt
        return None

    def find_strike_near_price(
        self,
        price: float,
        option_type: str,
        otm_percent: float = 0.0,
    ) -> Optional[OptionContract]:
        """Find option with strike at specified OTM percentage.

        Args:
            price: Current underlying price.
            option_type: 'put' or 'call'.
            otm_percent: How far OTM (e.g., 0.05 = 5% OTM).

        Returns:
            Closest option to target strike.
        """
        if option_type == "put":
            target_strike = price * (1 - otm_percent)
        else:
            target_strike = price * (1 + otm_percent)

        candidates = [
            opt for opt in self.options
            if opt.option_type == option_type
        ]

        if not candidates:
            return None

        # Find closest to target strike
        candidates.sort(key=lambda o: abs(o.strike - target_strike))
        return candidates[0]

    def filter_by_dte(
        self,
        min_dte: int = 0,
        max_dte: int = 365,
        reference_time: Optional[datetime] = None,
    ) -> "OptionSelector":
        """Filter options by days to expiry.

        Args:
            min_dte: Minimum days to expiry.
            max_dte: Maximum days to expiry.
            reference_time: Reference time for DTE calculation.
                Defaults to now. For backtesting, pass the simulation timestamp.

        Returns:
            New OptionSelector with filtered options.
        """
        if min_dte < 0:
            raise ValueError(f"min_dte must be >= 0, got {min_dte}")
        if max_dte < min_dte:
            raise ValueError(f"max_dte ({max_dte}) must be >= min_dte ({min_dte})")

        now = reference_time or datetime.now(timezone.utc)

        filtered = []
        for opt in self.options:
            dte = max(0, (opt.expiry - now).days)
            if min_dte <= dte <= max_dte:
                filtered.append(opt)

        return OptionSelector(filtered)

    def filter_by_type(self, option_type: str) -> "OptionSelector":
        """Filter options by type (put/call).

        Args:
            option_type: 'put' or 'call'.

        Returns:
            New OptionSelector with filtered options.
        """
        filtered = [opt for opt in self.options if opt.option_type == option_type]
        return OptionSelector(filtered)

    def get_puts(self) -> list[OptionContract]:
        """Get all put options sorted by strike descending."""
        puts = [opt for opt in self.options if opt.option_type == "put"]
        puts.sort(key=lambda o: o.strike, reverse=True)
        return puts

    def get_calls(self) -> list[OptionContract]:
        """Get all call options sorted by strike ascending."""
        calls = [opt for opt in self.options if opt.option_type == "call"]
        calls.sort(key=lambda o: o.strike)
        return calls
