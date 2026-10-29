"""Integration tests for risk management flow."""

import pytest
from datetime import datetime, timezone

from src.risk.position_sizer import PositionSizer, SizingConfig
from src.risk.risk_manager import RiskManager, RiskConfig
from src.risk.circuit_breaker import CircuitBreaker, BreakerConfig
from src.execution.delta_hedger import DeltaHedger, HedgerConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def risk_config() -> RiskConfig:
    """Create risk config."""
    return RiskConfig(
        max_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )


@pytest.fixture
def sizing_config() -> SizingConfig:
    """Create sizing config."""
    return SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
        min_trade_amount=0.0,  # Disable guard for non-guard tests
    )


@pytest.fixture
def breaker_config() -> BreakerConfig:
    """Create breaker config."""
    return BreakerConfig(
        daily_loss_limit_pct=0.05,
        dvol_halt_threshold=80.0,
        dvol_resume_threshold=70.0,
    )


@pytest.fixture
def hedger_config() -> HedgerConfig:
    """Create hedger config."""
    return HedgerConfig(
        rebalance_threshold=0.10,
        hard_limit=0.15,
    )


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create sample trade signal."""
    expiry = datetime.now(timezone.utc)
    return TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-90000-P",
                strike=90000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.15,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-85000-P",
                strike=85000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.05,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-104000-C",
                strike=104000.0,
                expiry=expiry,
                option_type="call",
                delta=0.15,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-110000-C",
                strike=110000.0,
                expiry=expiry,
                option_type="call",
                delta=0.05,
            ),
        ],
        direction="sell",
        quantity=0.10,
        legs_direction=["sell", "buy", "sell", "buy"],
    )


def test_full_risk_flow_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    breaker_config: BreakerConfig,
    sample_signal: TradeSignal,
) -> None:
    """Test full risk check flow with approved signal."""
    breaker = CircuitBreaker(breaker_config)
    manager = RiskManager(risk_config, sizing_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        timestamp=datetime.now(timezone.utc),
    )

    # Step 1: Check circuit breaker
    dvol_event = breaker.check_dvol(metrics)
    assert dvol_event is None
    assert breaker.can_trade() is True

    # Step 2: Validate signal
    result = manager.validate_signal(
        signal=sample_signal,
        metrics=metrics,
        capital=100000.0,
        current_exposure=0.10,
        open_positions=2,
        daily_pnl=500.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    assert result.adjusted_quantity > 0


def test_full_risk_flow_blocked_by_breaker(
    breaker_config: BreakerConfig,
) -> None:
    """Test risk flow blocked by circuit breaker."""
    breaker = CircuitBreaker(breaker_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,  # High DVOL
        timestamp=datetime.now(timezone.utc),
    )

    # Check circuit breaker - should trip
    dvol_event = breaker.check_dvol(metrics)
    assert dvol_event is not None
    assert breaker.can_trade() is False


def test_delta_hedger_with_iron_condor(
    hedger_config: HedgerConfig,
    sample_signal: TradeSignal,
) -> None:
    """Test delta hedger with iron condor legs."""
    hedger = DeltaHedger(hedger_config)

    # Calculate delta with per-leg directions
    # Short put -0.15: +0.15
    # Long put -0.05: -0.05
    # Short call +0.15: -0.15
    # Long call +0.05: +0.05
    # Net: +0.15 - 0.05 - 0.15 + 0.05 = 0.0
    assert sample_signal.legs_direction is not None
    portfolio_delta = hedger.calculate_portfolio_delta_with_legs(
        sample_signal.contracts,
        sample_signal.legs_direction,
    )

    assert portfolio_delta == pytest.approx(0.0, abs=0.01)

    # No hedge needed
    hedge = hedger.check_hedge_needed(portfolio_delta)
    assert hedge is None


def test_delta_hedger_triggers_hedge_after_price_move(
    hedger_config: HedgerConfig,
) -> None:
    """Test delta hedger triggers hedge after price move."""
    hedger = DeltaHedger(hedger_config)

    # Simulate larger price move - put deltas changed significantly
    expiry = datetime.now(timezone.utc)
    moved_contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.30,  # Was -0.15, price dropped significantly
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-85000-P",
            strike=85000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.12,  # Was -0.05
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-104000-C",
            strike=104000.0,
            expiry=expiry,
            option_type="call",
            delta=0.06,  # Was +0.15, price dropped
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-110000-C",
            strike=110000.0,
            expiry=expiry,
            option_type="call",
            delta=0.02,  # Was +0.05
        ),
    ]
    legs_direction = ["sell", "buy", "sell", "buy"]

    # Recalculate delta
    # Short put -0.30: +0.30
    # Long put -0.12: -0.12
    # Short call +0.06: -0.06
    # Long call +0.02: +0.02
    # Net: +0.30 - 0.12 - 0.06 + 0.02 = +0.14
    portfolio_delta = hedger.calculate_portfolio_delta_with_legs(
        moved_contracts,
        legs_direction,
    )

    assert portfolio_delta == pytest.approx(0.14, abs=0.01)

    # Should trigger hedge (delta 0.14 > threshold 0.10)
    hedge = hedger.check_hedge_needed(portfolio_delta)
    assert hedge is not None
    assert hedge.direction == "sell"


def test_regime_sizing_integration(
    sizing_config: SizingConfig,
) -> None:
    """Test position sizing across different regimes."""
    sizer = PositionSizer(sizing_config)
    capital = 100000.0

    # Normal regime
    normal = MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_normal = sizer.size_position(capital, normal, 0.0)

    # Stressed regime
    stressed = MarketMetrics(
        btc_price=97000.0,
        dvol=68.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_stressed = sizer.size_position(capital, stressed, 0.0)

    # Extreme regime
    extreme = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_extreme = sizer.size_position(capital, extreme, 0.0)

    # Verify sizing decreases with stress
    assert result_normal.approved is True
    assert result_stressed.approved is True
    assert result_extreme.approved is False

    assert result_stressed.size_pct < result_normal.size_pct
    assert result_extreme.size_pct == 0.0
