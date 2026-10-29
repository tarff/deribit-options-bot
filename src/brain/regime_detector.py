"""Market regime detection based on volatility metrics."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.data.market_metrics import MarketMetrics


class MarketRegime(str, Enum):
    """Market regime classification."""

    EXTREME_FEAR = "extreme_fear"
    HIGH_IV_OVERPRICED = "high_iv_overpriced"
    LOW_IV_UNDERPRICED = "low_iv_underpriced"
    VOLATILE_FAIR = "volatile_fair"
    NEUTRAL = "neutral"


@dataclass
class StrategyRecommendation:
    """Strategy recommendation based on market regime.

    Attributes:
        regime: The detected market regime.
        strategy: Recommended strategy name, or None if should not trade.
        action: Action to take (open_new, reduce_exposure, close_all).
        size_multiplier: Position size multiplier (0.0 to 1.0).
        reason: Human-readable explanation.
    """

    regime: MarketRegime
    strategy: Optional[str]
    action: str
    size_multiplier: float
    reason: str


class RegimeDetector:
    """Detects market regime from volatility metrics.

    Uses rule-based classification with priority ordering:
    1. HIGH_IV_OVERPRICED: IV Rank > 60% AND IV-RV spread > 10
    2. LOW_IV_UNDERPRICED: IV Rank < 30% AND IV-RV spread < -10
    3. VOLATILE_FAIR: RV(7d) > RV(30d) * 1.3 AND spread near zero
    4. NEUTRAL: Default (calendar spread for cash-settled options)

    Note: EXTREME_FEAR is no longer triggered by the regime detector.
    DVOL-based risk policy is handled by the PositionSizer, which reduces
    size to 0.5x at elevated DVOL and 0.0x at extreme DVOL for undefined-risk
    strategies, while capping at 0.5x for defined-risk strategies (IC).

    Session 61 analysis (scripts/analyze_ic_dvol_performance.py) showed that
    blocking entries at high DVOL costs money for Iron Condors:
    - DVOL 70-80: 41 trades, 100% win rate, Sharpe 20.00
    - DVOL mean reversion from >= 80: 100% lower at 7/14/30 days
    - Higher DVOL = richer premiums + faster mean reversion (double tailwind)

    Thresholds calibrated via scripts/analyze_high_iv_overpriced.py (2026-01-30):
        HIGH_IV_OVERPRICED (for selling vol):
        - IV Rank >= 60% AND Spread >= 10: 63.6% mean reversion success
        - ~63 entry opportunities/year
        - Average DVOL change: -0.9 pts over 7 days
        - Spread-only NOT effective (53.8% = random)
    """

    def __init__(
        self,
        high_iv_rank_threshold: float = 0.6,
        low_iv_rank_threshold: float = 0.3,
        high_iv_spread_threshold: float = 10.0,
        low_iv_spread_threshold: float = -10.0,
        rv_spike_multiplier: float = 1.3,
        fair_spread_threshold: float = 5.0,
        dvol_halt_threshold: float = 80.0,  # Deprecated: kept for API compat, unused
    ) -> None:
        """Initialize detector with thresholds.

        Args:
            high_iv_rank_threshold: IV Rank above this = high IV.
            low_iv_rank_threshold: IV Rank below this = low IV.
            high_iv_spread_threshold: IV-RV spread above this = overpriced.
            low_iv_spread_threshold: IV-RV spread below this = underpriced.
            rv_spike_multiplier: RV(7d) / RV(30d) ratio for volatile regime.
            fair_spread_threshold: IV-RV spread absolute value for "fair" pricing.
            dvol_halt_threshold: Deprecated, unused. DVOL risk handled by PositionSizer.
        """
        self.dvol_halt_threshold = dvol_halt_threshold  # Kept for backcompat
        self.high_iv_rank_threshold = high_iv_rank_threshold
        self.low_iv_rank_threshold = low_iv_rank_threshold
        self.high_iv_spread_threshold = high_iv_spread_threshold
        self.low_iv_spread_threshold = low_iv_spread_threshold
        self.rv_spike_multiplier = rv_spike_multiplier
        self.fair_spread_threshold = fair_spread_threshold

    def detect(self, metrics: MarketMetrics) -> MarketRegime:
        """Detect current market regime.

        Classifies market conditions to determine WHAT strategy to trade.
        Does NOT enforce risk policy (that's PositionSizer's job).

        Args:
            metrics: Current market metrics.

        Returns:
            Detected market regime.
        """
        # Priority 1: HIGH_IV_OVERPRICED
        if self._is_high_iv_overpriced(metrics):
            return MarketRegime.HIGH_IV_OVERPRICED

        # Priority 3: LOW_IV_UNDERPRICED
        if self._is_low_iv_underpriced(metrics):
            return MarketRegime.LOW_IV_UNDERPRICED

        # Priority 4: VOLATILE_FAIR
        if self._is_volatile_fair(metrics):
            return MarketRegime.VOLATILE_FAIR

        # Default: NEUTRAL
        return MarketRegime.NEUTRAL

    def _is_high_iv_overpriced(self, metrics: MarketMetrics) -> bool:
        """Check if IV is high and overpriced relative to RV."""
        if metrics.iv_rank is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        return (
            metrics.iv_rank > self.high_iv_rank_threshold
            and spread > self.high_iv_spread_threshold
        )

    def _is_low_iv_underpriced(self, metrics: MarketMetrics) -> bool:
        """Check if IV is low and underpriced relative to RV."""
        if metrics.iv_rank is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        return (
            metrics.iv_rank < self.low_iv_rank_threshold
            and spread < self.low_iv_spread_threshold
        )

    def _is_volatile_fair(self, metrics: MarketMetrics) -> bool:
        """Check if market is volatile but fairly priced."""
        if metrics.rv_7d is None or metrics.rv_30d is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        rv_spiking = metrics.rv_7d > metrics.rv_30d * self.rv_spike_multiplier
        fair_priced = abs(spread) < self.fair_spread_threshold

        return rv_spiking and fair_priced

    def get_recommendation(self, regime: MarketRegime) -> StrategyRecommendation:
        """Get strategy recommendation for a regime.

        Args:
            regime: Market regime.

        Returns:
            Strategy recommendation with sizing and action.
        """
        recommendations = {
            MarketRegime.EXTREME_FEAR: StrategyRecommendation(
                regime=regime,
                strategy=None,
                action="close_all",
                size_multiplier=0.0,
                reason="DVOL above halt threshold: Halt all trading",
            ),
            MarketRegime.HIGH_IV_OVERPRICED: StrategyRecommendation(
                regime=regime,
                strategy="iron_condor",
                action="open_new",
                size_multiplier=1.0,
                reason="High IV Rank + positive spread: Sell premium via iron condor",
            ),
            MarketRegime.LOW_IV_UNDERPRICED: StrategyRecommendation(
                regime=regime,
                strategy="gamma_scalp",
                action="open_new",
                size_multiplier=1.0,
                reason="Low IV Rank + negative spread: Buy cheap options, gamma scalp",
            ),
            MarketRegime.VOLATILE_FAIR: StrategyRecommendation(
                regime=regime,
                strategy="gamma_scalp",
                action="open_new",
                size_multiplier=1.0,
                reason="High RV, fair IV: Gamma scalp to profit from oscillation",
            ),
            MarketRegime.NEUTRAL: StrategyRecommendation(
                regime=regime,
                strategy="calendar_spread",
                action="open_new",
                size_multiplier=1.0,
                reason="Neutral conditions: Calendar spread for cash-settled options",
            ),
        }
        return recommendations[regime]
