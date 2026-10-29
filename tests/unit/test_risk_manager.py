"""Tests for risk manager pre-trade validation."""

import pytest
from datetime import datetime, timezone

from src.risk.risk_manager import RiskManager, RiskConfig
from src.risk.position_sizer import SizingConfig
from src.risk.circuit_breaker import CircuitBreaker, BreakerConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def risk_config() -> RiskConfig:
    """Create risk manager config."""
    return RiskConfig(
        max_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )


@pytest.fixture
def sizing_config() -> SizingConfig:
    """Create position sizer config."""
    return SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
    )


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create sample trade signal."""
    expiry = datetime.now(timezone.utc)
    return TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.25,
                bid=0.0150,
                ask=0.0165,
            )
        ],
        direction="sell",
        quantity=0.10,
    )


@pytest.fixture
def normal_metrics() -> MarketMetrics:
    """Normal market conditions."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )


def test_validate_signal_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal approved under normal conditions."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.0,
        open_positions=0,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    assert result.adjusted_quantity > 0


def test_validate_signal_uses_strategy_specific_sizing_config(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Non-IC strategies should not inherit the IC Kelly calibration."""
    manager = RiskManager(
        risk_config,
        sizing_config,
        strategy_sizing_configs={
            StrategyType.WHEEL: SizingConfig(
                max_position_pct=0.03,
                max_total_exposure_pct=0.30,
                base_win_rate=0.60,
                base_avg_win=0.01,
                base_avg_loss=0.01,
                min_trade_amount=0.0,
            )
        },
    )

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.0,
        open_positions=0,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    assert result.adjusted_quantity == pytest.approx((100000.0 * 0.03) / 97000.0)


def test_validate_signal_rejected_max_positions(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when at max positions."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.20,
        open_positions=5,  # At limit
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "max positions" in result.reason.lower()


def test_validate_signal_rejected_daily_loss(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when daily loss exceeded."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.10,
        open_positions=1,
        daily_pnl=-5500.0,  # -5.5% exceeds 5% limit
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "daily loss" in result.reason.lower()


def test_validate_signal_rejected_drawdown(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when drawdown exceeded."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=84000.0,  # 16% drawdown from peak
        current_exposure=0.10,
        open_positions=1,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "drawdown" in result.reason.lower()


def test_validate_close_signal_always_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test CLOSE signals are always approved (closing reduces risk)."""
    manager = RiskManager(risk_config, sizing_config)

    expiry = datetime.now(timezone.utc)
    close_signal = TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.CLOSE,  # Closing, not opening
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=expiry,
                option_type="put",
            )
        ],
        direction="buy",
        quantity=0.10,
    )

    result = manager.validate_signal(
        signal=close_signal,
        metrics=normal_metrics,
        capital=84000.0,  # In drawdown
        current_exposure=0.30,  # At limit
        open_positions=5,  # At limit
        daily_pnl=-6000.0,  # Exceeds daily loss
        peak_capital=100000.0,
    )

    # CLOSE signals bypass risk checks
    assert result.approved is True


def test_validate_signal_rejected_when_halted(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test validate_signal rejects OPEN signals when halted."""
    breaker = CircuitBreaker(BreakerConfig())
    manager = RiskManager(risk_config, sizing_config, circuit_breaker=breaker)

    manager.halt("DVOL spike")

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.0,
        open_positions=0,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "halted" in result.reason.lower()


def test_can_trade_returns_false_on_halt(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
) -> None:
    """Test can_trade returns False when halted via CircuitBreaker."""
    breaker = CircuitBreaker(BreakerConfig())
    manager = RiskManager(risk_config, sizing_config, circuit_breaker=breaker)

    assert manager.can_trade() is True

    manager.halt("Test halt")

    assert manager.can_trade() is False
    assert manager.halt_reason == "manual"  # Trigger type from breaker


def test_resume_trading(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
) -> None:
    """Test resume clears halt state via CircuitBreaker."""
    breaker = CircuitBreaker(BreakerConfig())
    manager = RiskManager(risk_config, sizing_config, circuit_breaker=breaker)

    manager.halt("Test halt")
    assert manager.can_trade() is False

    manager.resume()
    assert manager.can_trade() is True


def test_validate_signal_uses_position_sizer_quantity(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test that adjusted_quantity comes from position sizer, not signal.

    Strategies pass a fraction (e.g. 0.10 = 10% of capital) as quantity,
    but the risk manager should use the position sizer's ETH amount instead.
    """
    manager = RiskManager(risk_config, sizing_config)

    expiry = datetime.now(timezone.utc)
    signal = TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.25,
            )
        ],
        direction="sell",
        quantity=0.10,  # This is a fraction (10%), not an ETH amount
    )

    result = manager.validate_signal(
        signal=signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.0,
        open_positions=0,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    # Position sizer determines actual ETH amount from capital/Kelly/price
    # With $100k capital, ~7.5% half-Kelly, BTC at ~$97k → ~0.077 BTC
    # Should NOT be capped at signal.quantity (which is a fraction, not ETH)
    assert result.adjusted_quantity > 0.05  # Sizer output, not signal fraction
