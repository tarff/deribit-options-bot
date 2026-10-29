"""Strategy selector based on market regime."""

from typing import Optional

from src.brain.regime_detector import MarketRegime
from src.brain.signal import StrategyType


class StrategySelector:
    """Maps market regimes to appropriate strategies.

    Strategy selection rules:
    - NEUTRAL: Calendar Spread (cash-settled neutral yield)
    - HIGH_IV_OVERPRICED: Iron Condor (sell premium)
    - LOW_IV_UNDERPRICED: Gamma Scalp (buy cheap options)
    - VOLATILE_FAIR: Gamma Scalp (profit from oscillation)
    - EXTREME_FEAR: None (no trading)

    Note: Position sizing handles DVOL-based size reduction separately.
    """

    # Primary strategy for each regime
    REGIME_TO_STRATEGY: dict[MarketRegime, Optional[StrategyType]] = {
        MarketRegime.NEUTRAL: StrategyType.CALENDAR_SPREAD,
        MarketRegime.HIGH_IV_OVERPRICED: StrategyType.IRON_CONDOR,
        MarketRegime.LOW_IV_UNDERPRICED: StrategyType.GAMMA_SCALP,
        MarketRegime.VOLATILE_FAIR: StrategyType.GAMMA_SCALP,
        MarketRegime.EXTREME_FEAR: None,
    }

    # All allowed strategies per regime (primary + alternatives)
    REGIME_ALLOWED: dict[MarketRegime, list[StrategyType]] = {
        MarketRegime.NEUTRAL: [StrategyType.CALENDAR_SPREAD, StrategyType.IRON_CONDOR],
        MarketRegime.HIGH_IV_OVERPRICED: [StrategyType.IRON_CONDOR, StrategyType.VOL_ARB],
        MarketRegime.LOW_IV_UNDERPRICED: [StrategyType.GAMMA_SCALP, StrategyType.VOL_ARB],
        MarketRegime.VOLATILE_FAIR: [StrategyType.GAMMA_SCALP],
        MarketRegime.EXTREME_FEAR: [],
    }

    # Fallback strategies when primary declines (none currently configured).
    REGIME_FALLBACK: dict[MarketRegime, StrategyType] = {}

    def select(self, regime: MarketRegime) -> Optional[StrategyType]:
        """Select primary strategy for regime.

        Args:
            regime: Current market regime.

        Returns:
            Recommended strategy type, or None if should not trade.
        """
        return self.REGIME_TO_STRATEGY.get(regime)

    def get_allowed(self, regime: MarketRegime) -> list[StrategyType]:
        """Get all allowed strategies for regime.

        Args:
            regime: Current market regime.

        Returns:
            List of allowed strategy types.
        """
        return self.REGIME_ALLOWED.get(regime, [])

    def is_allowed(self, strategy: StrategyType, regime: MarketRegime) -> bool:
        """Check if strategy is allowed in regime.

        Args:
            strategy: Strategy to check.
            regime: Current market regime.

        Returns:
            True if strategy is allowed.
        """
        return strategy in self.get_allowed(regime)

    def get_fallback(self, regime: MarketRegime) -> Optional[StrategyType]:
        """Get fallback strategy when primary declines.

        Used when primary strategy returns None (e.g., Wheel declines
        due to low IV Rank) - try the fallback instead.

        Args:
            regime: Current market regime.

        Returns:
            Fallback strategy type, or None if no fallback defined.
        """
        return self.REGIME_FALLBACK.get(regime)
