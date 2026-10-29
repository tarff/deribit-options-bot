"""Position sizer using Half Kelly criterion with regime adjustment."""

from dataclasses import dataclass

from src.data.market_metrics import MarketMetrics


@dataclass
class SizingConfig:
    """Configuration for position sizing.

    Attributes:
        max_position_pct: Maximum single position as % of capital.
        max_total_exposure_pct: Maximum total exposure as % of capital.
        base_win_rate: Historical win rate for Kelly calculation.
        base_avg_win: Average win as % of position.
        base_avg_loss: Average loss as % of position.
    """

    # Calibrated via scripts/calibrate_kelly_params.py (2026-02-10):
    # 54 IC trades on ETH, IVR>60%, 50% PT, 25 DTE, 2.7 years of data
    # Half Kelly = 36.76%, capped at 20% for conservatism
    max_position_pct: float = 0.20
    max_total_exposure_pct: float = 0.30
    base_win_rate: float = 0.9074
    base_avg_win: float = 0.008217
    base_avg_loss: float = 0.015291
    # Deribit USDC linear options: 0.1 ETH/BTC minimum, 0.1 tick size.
    # Reject trades below this instead of flooring (which bypasses risk management).
    min_trade_amount: float = 0.1


@dataclass
class SizingResult:
    """Result of position sizing calculation.

    Attributes:
        approved: Whether the position is allowed.
        size_pct: Position size as % of capital.
        size_coins: Position size in base currency (ETH or BTC).
        regime_multiplier: Multiplier applied for regime (1.0, 0.5, or 0.0).
        reason: Explanation if rejected or adjusted.
    """

    approved: bool
    size_pct: float
    size_coins: float
    regime_multiplier: float
    reason: str = ""


class PositionSizer:
    """Calculate position sizes using Half Kelly with DVOL-based adjustment.

    DVOL-based size adjustments (configurable thresholds):
    - DVOL < reduce threshold: Full size (multiplier 1.0)
    - DVOL reduce-halt range: Half size (multiplier 0.5)
    - DVOL >= halt threshold: No new positions (multiplier 0.0)

    For defined-risk strategies (e.g. Iron Condor with wings capping max loss):
    - DVOL >= halt threshold: Half size (multiplier 0.5) instead of 0.0
    - Session 61 analysis: DVOL 70-80 = 100% IC win rate, Sharpe 20.00
    - Higher DVOL = richer premiums + mean reversion (double tailwind)

    Default thresholds (BTC): reduce=60, halt=80
    ETH thresholds (calibrated): reduce=73, halt=82
    """

    def __init__(
        self,
        config: SizingConfig,
        dvol_reduce_threshold: float = 60.0,
        dvol_halt_threshold: float = 80.0,
    ) -> None:
        """Initialize position sizer.

        Args:
            config: Sizing configuration.
            dvol_reduce_threshold: DVOL level to reduce position size to 50%.
            dvol_halt_threshold: DVOL level to halt new positions.
        """
        self.config = config
        self.dvol_reduce_threshold = dvol_reduce_threshold
        self.dvol_halt_threshold = dvol_halt_threshold

    def calculate_kelly(self) -> float:
        """Calculate Half Kelly fraction.

        Kelly formula: f* = p - q/b
        Where:
            p = win probability
            q = loss probability (1 - p)
            b = win/loss ratio (avg_win / avg_loss)

        Returns:
            Half Kelly fraction, capped at max_position_pct.
        """
        p = self.config.base_win_rate
        q = 1.0 - p
        b = self.config.base_avg_win / self.config.base_avg_loss

        kelly = p - (q / b)
        half_kelly = kelly / 2.0

        # Cap at maximum position size
        return min(max(half_kelly, 0.0), self.config.max_position_pct)

    def get_regime_multiplier(
        self, metrics: MarketMetrics, is_defined_risk: bool = False
    ) -> float:
        """Get position size multiplier based on DVOL level.

        Args:
            metrics: Current market metrics.
            is_defined_risk: True for strategies with capped max loss (e.g. IC).
                Defined-risk strategies use 0.5x at extreme DVOL instead of 0.0x
                because wings cap the downside regardless of DVOL level.

        Returns:
            Multiplier: 1.0 (normal), 0.5 (stressed/defined-risk extreme), 0.0 (extreme).
        """
        if metrics.dvol is None:
            return 1.0  # Default to normal if no DVOL

        if metrics.dvol >= self.dvol_halt_threshold:
            # Defined-risk strategies (IC) can still trade at reduced size
            # because wings cap max loss regardless of DVOL level.
            # Session 61: DVOL 70-80 = 100% IC win rate, richer premiums.
            return 0.5 if is_defined_risk else 0.0
        elif metrics.dvol >= self.dvol_reduce_threshold:
            return 0.5
        else:
            return 1.0

    def size_position(
        self,
        capital: float,
        metrics: MarketMetrics,
        current_exposure: float,
        is_defined_risk: bool = False,
    ) -> SizingResult:
        """Calculate position size for a new trade.

        Args:
            capital: Total capital in USD.
            metrics: Current market metrics.
            current_exposure: Current exposure as fraction (0.0 to 1.0).
            is_defined_risk: True for strategies with capped max loss (e.g. IC).

        Returns:
            SizingResult with approved flag and calculated size.
        """
        # Validate capital
        if capital <= 0:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_coins=0.0,
                regime_multiplier=0.0,
                reason=f"Invalid capital: {capital}",
            )

        # Check regime
        regime_mult = self.get_regime_multiplier(metrics, is_defined_risk)

        if regime_mult == 0.0:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_coins=0.0,
                regime_multiplier=0.0,
                reason=f"Extreme fear: DVOL {metrics.dvol:.1f} >= {self.dvol_halt_threshold}",
            )

        # Check exposure limit
        remaining_exposure = self.config.max_total_exposure_pct - current_exposure

        if remaining_exposure <= 0:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_coins=0.0,
                regime_multiplier=regime_mult,
                reason=f"Exposure limit: {current_exposure:.1%} >= {self.config.max_total_exposure_pct:.1%}",
            )

        # Calculate Kelly-based size
        base_size = self.calculate_kelly()

        # Apply regime multiplier
        adjusted_size = base_size * regime_mult

        # Cap at remaining exposure
        final_size = min(adjusted_size, remaining_exposure)

        # Convert to BTC
        size_usd = capital * final_size
        size_coins = size_usd / metrics.btc_price if metrics.btc_price > 0 else 0.0

        # Reject if below minimum trade amount (prevents order_executor
        # from flooring up to min_amount, which bypasses risk management).
        if size_coins < self.config.min_trade_amount:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_coins=0.0,
                regime_multiplier=regime_mult,
                reason=(
                    f"Below minimum trade: {size_coins:.3f} < {self.config.min_trade_amount} "
                    f"(capital ${capital:,.0f} too low for current regime)"
                ),
            )

        reason = ""
        if regime_mult < 1.0:
            reason = f"Stressed market: DVOL {metrics.dvol:.1f}, size reduced to {regime_mult:.0%}"

        return SizingResult(
            approved=True,
            size_pct=final_size,
            size_coins=size_coins,
            regime_multiplier=regime_mult,
            reason=reason,
        )
