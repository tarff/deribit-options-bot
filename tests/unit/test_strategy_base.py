"""Tests for base strategy interface."""

import pytest

from src.strategies.base import BaseStrategy, StrategyConfig, StrategyState
from src.brain.signal import TradeSignal, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


class MockStrategy(BaseStrategy):
    """Concrete implementation for testing."""

    def __init__(self, config: StrategyConfig) -> None:
        super().__init__(config)
        self._should_signal = False
        self._signal: TradeSignal | None = None

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.WHEEL

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> TradeSignal | None:
        if self._should_signal:
            return self._signal
        return None

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> TradeSignal | None:
        return None

    def set_signal(self, signal: TradeSignal) -> None:
        self._should_signal = True
        self._signal = signal


def test_strategy_config_defaults() -> None:
    """Test StrategyConfig with defaults."""
    config = StrategyConfig(
        name="test_strategy",
        enabled=True,
    )

    assert config.max_position_size == 0.10
    assert config.target_dte_min == 30
    assert config.target_dte_max == 45
    assert config.profit_target == 0.50


def test_strategy_config_custom() -> None:
    """Test StrategyConfig with custom values."""
    config = StrategyConfig(
        name="iron_condor",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=21,
        target_dte_max=35,
        profit_target=0.40,
    )

    assert config.max_position_size == 0.05
    assert config.target_dte_min == 21


def test_strategy_state_initial() -> None:
    """Test StrategyState initial values."""
    state = StrategyState()

    assert state.is_active is False
    assert state.position_id is None
    assert state.entry_time is None


def test_base_strategy_initialization() -> None:
    """Test BaseStrategy initialization."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)

    assert strategy.config.name == "test"
    assert strategy.state.is_active is False


@pytest.mark.asyncio
async def test_base_strategy_can_open_when_inactive() -> None:
    """Test can_open returns True when no position."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)

    assert strategy.can_open() is True


@pytest.mark.asyncio
async def test_base_strategy_cannot_open_when_active() -> None:
    """Test can_open returns False when position exists."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)
    strategy.state.is_active = True
    strategy.state.position_id = "test-123"

    assert strategy.can_open() is False


@pytest.mark.asyncio
async def test_base_strategy_cannot_open_when_disabled() -> None:
    """Test can_open returns False when strategy disabled."""
    config = StrategyConfig(name="test", enabled=False)
    strategy = MockStrategy(config)

    assert strategy.can_open() is False
