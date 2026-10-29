"""Tests for Gamma Scalping strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.gamma_scalp import GammaScalpStrategy, GammaScalpConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def gamma_config() -> GammaScalpConfig:
    """Create Gamma Scalp strategy config."""
    return GammaScalpConfig(
        name="gamma_scalp",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=14,
        target_dte_max=21,
        profit_target=0.20,
        min_rv=40.0,
        scalp_threshold=0.10,
    )


@pytest.fixture
def volatile_metrics() -> MarketMetrics:
    """Create metrics with high RV (scalping opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=48.0,
        iv_rank=0.25,
        iv_rv_spread=-5.0,
        rv_7d=55.0,  # High short-term RV
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_atm_options() -> list[OptionContract]:
    """Create ATM options for straddle."""
    expiry = datetime.now(timezone.utc) + timedelta(days=15)
    return [
        OptionContract(
            instrument_name="BTC-14JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            gamma=0.00018,
            theta=-95.0,
            vega=130.0,
            iv=48.0,
            bid=0.0380,
            ask=0.0410,
        ),
        OptionContract(
            instrument_name="BTC-14JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.52,
            gamma=0.00018,
            theta=-95.0,
            vega=130.0,
            iv=48.0,
            bid=0.0370,
            ask=0.0400,
        ),
    ]


@pytest.mark.asyncio
async def test_gamma_scalp_entry_signal(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp generates buy straddle signal."""
    strategy = GammaScalpStrategy(gamma_config)

    signal = await strategy.evaluate(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.strategy_type == StrategyType.GAMMA_SCALP
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "buy"
    assert len(signal.contracts) == 2
    assert signal.contracts[0].strike == signal.contracts[1].strike
    assert signal.contracts[0].expiry == signal.contracts[1].expiry


@pytest.mark.asyncio
async def test_gamma_scalp_requires_same_strike_and_expiry_straddle(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
) -> None:
    """Gamma Scalp should not build a synthetic straddle from mismatched legs."""
    expiry = datetime.now(timezone.utc) + timedelta(days=15)
    options = [
        OptionContract(
            instrument_name="BTC-14JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            bid=0.0380,
            ask=0.0410,
        ),
        OptionContract(
            instrument_name="BTC-21JAN26-98000-C",
            strike=98000.0,
            expiry=expiry + timedelta(days=7),
            option_type="call",
            delta=0.52,
            bid=0.0370,
            ask=0.0400,
        ),
    ]
    strategy = GammaScalpStrategy(gamma_config)

    signal = await strategy.evaluate(volatile_metrics, options)

    assert signal is None


@pytest.mark.asyncio
async def test_gamma_scalp_requires_minimum_rv(
    gamma_config: GammaScalpConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp requires RV > 40%."""
    strategy = GammaScalpStrategy(gamma_config)
    low_rv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.30,
        rv_7d=30.0,  # Below threshold
        rv_30d=32.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_rv_metrics, sample_atm_options)

    assert signal is None


@pytest.mark.asyncio
async def test_gamma_scalp_hedge_signal(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp generates scalp signal when delta exceeds threshold."""
    strategy = GammaScalpStrategy(gamma_config)

    # Simulate active position
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options

    # Price moved up, delta is now positive
    sample_atm_options[0].delta = -0.35
    sample_atm_options[1].delta = 0.65
    # Net delta = 0.30

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.direction == "sell"  # Sell BTC to reduce positive delta


@pytest.mark.asyncio
async def test_gamma_scalp_hedge_uses_position_size_and_existing_hedge(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Hedge quantity should be net delta after position size and existing hedge."""
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 2.0

    sample_atm_options[0].delta = -0.35
    sample_atm_options[1].delta = 0.65

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.direction == "sell"
    assert signal.quantity == pytest.approx(0.6)

    strategy.state.hedge_delta = -0.6

    assert await strategy.manage(volatile_metrics, sample_atm_options) is None


@pytest.mark.asyncio
async def test_gamma_scalp_exit_when_rv_drops(
    gamma_config: GammaScalpConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp exits when RV drops below IV."""
    strategy = GammaScalpStrategy(gamma_config)

    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options

    # RV dropped, no longer favorable
    low_rv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.40,
        rv_7d=35.0,  # RV dropped below IV
        rv_30d=38.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.manage(low_rv_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "rv" in signal.reason.lower()


@pytest.mark.asyncio
async def test_gamma_scalp_exits_near_expiry(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Gamma Scalp should close before the configured expiry cutoff."""
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    strategy.state.premium_received = -0.08
    near_expiry = volatile_metrics.timestamp + timedelta(days=6)
    for contract in sample_atm_options:
        contract.expiry = near_expiry

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "dte" in signal.reason.lower()


@pytest.mark.asyncio
async def test_gamma_scalp_closes_at_profit_target(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Gamma Scalp should capture gains when the straddle value reaches target."""
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    strategy.state.premium_received = -0.08
    sample_atm_options[0].bid = 0.055
    sample_atm_options[1].bid = 0.045

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "profit target" in signal.reason.lower()


@pytest.mark.asyncio
async def test_gamma_scalp_closes_at_loss_limit(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Gamma Scalp should stop out when long premium decays past the long-debit stop."""
    gamma_config.long_debit_stop_loss_pct = 0.50
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    strategy.state.premium_received = -0.08
    sample_atm_options[0].bid = 0.020
    sample_atm_options[1].bid = 0.015

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "loss limit" in signal.reason.lower()


@pytest.mark.asyncio
async def test_gamma_scalp_skips_loss_check_when_stop_is_none(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """With no calibrated stop, the loss check must not fire on a long-debit position."""
    gamma_config.long_debit_stop_loss_pct = None
    # Inherited loss_limit of 2.0 is unreachable for long debit; ensure
    # leaving the new field unset truly disables the check.
    gamma_config.loss_limit = 2.0
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    strategy.state.premium_received = -0.08
    # Straddle is essentially worthless — full debit lost.
    sample_atm_options[0].bid = 0.001
    sample_atm_options[1].bid = 0.001

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    # No "loss limit" close should fire — only RV-drop or scalp signals are possible.
    if signal is not None:
        assert "loss limit" not in signal.reason.lower()


@pytest.mark.asyncio
async def test_gamma_scalp_profit_target_accounts_for_entry_fees(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Entry fees inflate the cost basis used in the profit-target check."""
    gamma_config.profit_target = 0.50
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    # Gross debit 0.10, fees 0.02 -> true cost basis 0.12.
    strategy.state.premium_received = -0.10
    strategy.state.entry_fees = 0.02
    # Current straddle value 0.17.
    # Without fees: profit_pct = (0.17 - 0.10) / 0.10 = 70% -> would trigger.
    # With fees:    profit_pct = (0.17 - 0.12) / 0.12 = 41.7% -> below 50% target.
    sample_atm_options[0].bid = 0.10
    sample_atm_options[1].bid = 0.07

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    if signal is not None:
        assert "profit target" not in signal.reason.lower()


def test_gamma_scalp_straddle_value_treats_zero_bid_as_real_price(
    gamma_config: GammaScalpConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """A zero bid is truthful execution data, not missing data."""
    strategy = GammaScalpStrategy(gamma_config)
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 1.0
    sample_atm_options[0].bid = 0.0
    sample_atm_options[0].mark_price = 0.050
    sample_atm_options[1].bid = 0.045
    sample_atm_options[1].mark_price = 0.045

    value = strategy._get_current_straddle_value(sample_atm_options)

    assert value == pytest.approx(0.045)


def test_gamma_scalp_strategy_type() -> None:
    """Test strategy type property."""
    config = GammaScalpConfig(name="gs", enabled=True)
    strategy = GammaScalpStrategy(config)

    assert strategy.strategy_type == StrategyType.GAMMA_SCALP
