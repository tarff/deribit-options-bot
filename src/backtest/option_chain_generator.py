"""Synthetic option chain generator for backtesting."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.brain.signal import OptionContract


def _norm_cdf(x: float) -> float:
    """Approximate standard normal CDF using Abramowitz & Stegun (1964) formula 26.2.17.

    Maximum error < 7.5e-8 across entire domain.
    """
    if x < -10:
        return 0.0
    if x > 10:
        return 1.0
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x_abs = abs(x)
    t = 1.0 / (1.0 + p * x_abs)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x_abs * x_abs / 2.0)
    return 0.5 * (1.0 + sign * y)


@dataclass
class SyntheticChainConfig:
    """Configuration for synthetic option chain generation.

    Note: These defaults are simplified approximations for backtesting.
    For production use, actual market data should be used.

    TODO(backtest-validation): All parameters below need empirical validation
    against historical Deribit option chain data. Run validation with:
        python scripts/validate_option_chain_params.py

    Attributes:
        dte_list: Days to expiry for generated options.
        strikes_above_atm: Number of strikes above ATM.
            25 at 2% = 50% above ATM, needed for call delta ~0.05 wings
            at DVOL=65 / 45 DTE (dataset mean). Derived from Black-Scholes:
            call delta 0.05 requires strike ~49% OTM at these params.
        strikes_below_atm: Number of strikes below ATM.
            15 at 2% = 30% below ATM, needed for put delta ~-0.05 wings.
            Put side needs less range due to lognormal skew.
        strike_increment_pct: Strike spacing as % of spot.
            Deribit ETH options typically have $25-$100 increments (~1-4% at $2500).
            Deribit BTC options: $1000-$5000 increments (~1-5% at $100k).
            Default 2% is mid-range for both.
            TODO: Validate against actual Deribit strike spacing.
        spread_pct: Bid-ask spread as % of mid price.
            Deribit liquid options typically 2-10% spread.
            Default 5% is conservative mid-range for backtesting.
            TODO: Validate against actual Deribit bid-ask spreads by DTE/delta.
    """

    dte_list: list[int] = field(default_factory=lambda: [7, 14, 30, 45])
    strikes_above_atm: int = 25
    strikes_below_atm: int = 15
    strike_increment_pct: float = 0.02  # TODO: Validate empirically
    spread_pct: float = 0.05  # TODO: Validate empirically
    currency: str = "ETH"  # Currency for instrument names


class SyntheticOptionChainGenerator:
    """Generates synthetic option chains for backtesting.

    Uses spot price and DVOL to create realistic option contracts
    with approximate delta and premium values.
    """

    def __init__(self, config: SyntheticChainConfig | None = None) -> None:
        """Initialize generator.

        Args:
            config: Chain configuration. Uses defaults if None.
        """
        self.config = config or SyntheticChainConfig()

    def generate(
        self,
        spot_price: float,
        dvol: float,
        timestamp: datetime,
    ) -> list[OptionContract]:
        """Generate synthetic option chain.

        Args:
            spot_price: Current BTC spot price.
            dvol: Deribit volatility index (used as IV proxy).
            timestamp: Current timestamp for expiry calculation.

        Returns:
            List of OptionContract objects.
        """
        chain: list[OptionContract] = []
        iv = dvol / 100.0  # Convert to decimal

        # Generate strikes centered on spot
        strikes = self._generate_strikes(spot_price)

        for dte in self.config.dte_list:
            expiry = timestamp + timedelta(days=dte)

            for strike in strikes:
                for option_type in ["call", "put"]:
                    contract = self._create_contract(
                        spot_price=spot_price,
                        strike=strike,
                        expiry=expiry,
                        dte=dte,
                        iv=iv,
                        option_type=option_type,
                    )
                    chain.append(contract)

        return chain

    def _generate_strikes(self, spot_price: float) -> list[float]:
        """Generate strike prices centered on spot."""
        strikes = []
        increment = spot_price * self.config.strike_increment_pct

        # Round spot to nearest increment for ATM
        atm_strike = round(spot_price / increment) * increment
        strikes.append(atm_strike)

        for i in range(1, self.config.strikes_above_atm + 1):
            strikes.append(atm_strike + i * increment)

        for i in range(1, self.config.strikes_below_atm + 1):
            strikes.append(atm_strike - i * increment)

        return sorted(strikes)

    def _create_contract(
        self,
        spot_price: float,
        strike: float,
        expiry: datetime,
        dte: int,
        iv: float,
        option_type: str,
    ) -> OptionContract:
        """Create a single option contract."""
        delta = self._approximate_delta(spot_price, strike, dte, option_type)
        premium = self._approximate_premium(spot_price, strike, dte, iv, option_type)

        # Apply bid-ask spread (ensure ask >= bid)
        half_spread = premium * self.config.spread_pct / 2
        bid = max(0.0001, premium - half_spread)
        ask = max(bid * (1 + self.config.spread_pct), premium + half_spread)

        # Generate instrument name
        expiry_str = expiry.strftime("%d%b%y").upper()
        opt_char = "C" if option_type == "call" else "P"
        instrument = f"{self.config.currency}-{expiry_str}-{int(strike)}-{opt_char}"

        return OptionContract(
            instrument_name=instrument,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            delta=delta,
            iv=iv * 100,  # Store as percentage
            bid=bid,
            ask=ask,
            mark_price=premium,
        )

    def _approximate_delta(
        self,
        spot: float,
        strike: float,
        dte: int,
        option_type: str,
    ) -> float:
        """Approximate delta using moneyness.

        Uses arctan for smooth mapping from moneyness to delta.
        This is a simplified model for backtesting - actual delta requires
        full Black-Scholes with accurate IV surface data.

        TODO(backtest-validation): Validate scale factor and time adjustment
        against historical Deribit option deltas. Run:
            python scripts/validate_option_chain_params.py --check-delta

        The scale factor (10.0) and time adjustment (dte/30) produce:
        - ATM options have delta ~0.50
        - 1 strike OTM has delta ~0.30-0.40
        - Deep OTM options approach 0
        """
        moneyness = spot / strike
        # Scale factor affects steepness - 10.0 calibrated for BTC volatility
        # Time adjustment: delta curve flattens with more DTE (30 days as baseline)
        scale = 10.0 / max(1, math.sqrt(dte / 30))

        if option_type == "call":
            raw = (moneyness - 1.0) * scale
            delta = 0.50 + 0.50 * (2 / math.pi) * math.atan(raw)
        else:
            raw = (1.0 - moneyness) * scale
            delta = -(0.50 + 0.50 * (2 / math.pi) * math.atan(raw))

        return round(delta, 4)

    def _approximate_premium(
        self,
        spot: float,
        strike: float,
        dte: int,
        iv: float,
        option_type: str,
    ) -> float:
        """Price option using Black-Scholes model (zero risk-free rate).

        Uses the standard Black-Scholes formula with r=0 (crypto convention).
        Previous Brenner-Subrahmanyam ATM approximation was 80-276% wrong for OTM.

        Premium is returned in BTC (divided by spot) as per Deribit convention.
        """
        t = dte / 365.0

        if t <= 0 or iv <= 0:
            # Expired or zero vol: intrinsic value only
            if option_type == "call":
                return max(0.0, (spot - strike) / spot)
            return max(0.0, (strike - spot) / spot)

        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t

        if option_type == "call":
            price = spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
        else:
            price = strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)

        # Convert to BTC terms
        premium_btc = price / spot
        return round(max(premium_btc, 0.000001), 6)
