"""Tests for strategy selector."""


from src.brain.strategy_selector import StrategySelector
from src.brain.regime_detector import MarketRegime
from src.brain.signal import StrategyType


def test_selector_returns_calendar_spread_for_neutral() -> None:
    """Test Calendar Spread strategy selected for NEUTRAL regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.NEUTRAL)

    assert result == StrategyType.CALENDAR_SPREAD


def test_selector_returns_iron_condor_for_high_iv() -> None:
    """Test Iron Condor selected for HIGH_IV_OVERPRICED regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.HIGH_IV_OVERPRICED)

    assert result == StrategyType.IRON_CONDOR


def test_selector_returns_gamma_scalp_for_low_iv() -> None:
    """Test Gamma Scalp selected for LOW_IV_UNDERPRICED regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.LOW_IV_UNDERPRICED)

    assert result == StrategyType.GAMMA_SCALP


def test_selector_returns_gamma_scalp_for_volatile_fair() -> None:
    """Test Gamma Scalp selected for VOLATILE_FAIR regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.VOLATILE_FAIR)

    assert result == StrategyType.GAMMA_SCALP


def test_selector_returns_none_for_extreme_fear() -> None:
    """Test no strategy for EXTREME_FEAR regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.EXTREME_FEAR)

    assert result is None


def test_selector_get_allowed_strategies() -> None:
    """Test getting all allowed strategies for a regime."""
    selector = StrategySelector()

    allowed = selector.get_allowed(MarketRegime.NEUTRAL)

    assert StrategyType.CALENDAR_SPREAD in allowed
    assert StrategyType.WHEEL not in allowed


def test_selector_is_strategy_allowed() -> None:
    """Test checking if specific strategy is allowed."""
    selector = StrategySelector()

    # Wheel is disabled for Deribit cash-settled options
    assert selector.is_allowed(StrategyType.WHEEL, MarketRegime.NEUTRAL) is False
    assert selector.is_allowed(StrategyType.CALENDAR_SPREAD, MarketRegime.NEUTRAL) is True

    # Wheel not allowed in extreme fear
    assert selector.is_allowed(StrategyType.WHEEL, MarketRegime.EXTREME_FEAR) is False

    # Gamma scalp allowed in low IV
    assert selector.is_allowed(StrategyType.GAMMA_SCALP, MarketRegime.LOW_IV_UNDERPRICED) is True
