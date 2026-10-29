"""Tests for Volatility Arbitrage strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.vol_arb import VolArbStrategy, VolArbConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def vol_arb_config() -> VolArbConfig:
    """Create Vol Arb strategy config."""
    return VolArbConfig(
        name="vol_arb",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=14,
        target_dte_max=30,
        profit_target=0.30,
        iv_rv_threshold_sell=15.0,
        iv_rv_threshold_buy=-10.0,
        delta_hedge_threshold=0.10,
    )


@pytest.fixture
def high_iv_spread_metrics() -> MarketMetrics:
    """Create metrics with high IV-RV spread (sell vol opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=60.0,
        iv_rank=0.70,
        iv_rv_spread=18.0,  # IV > RV by 18 points
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def low_iv_spread_metrics() -> MarketMetrics:
    """Create metrics with low IV-RV spread (buy vol opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=38.0,
        iv_rank=0.20,
        iv_rv_spread=-12.0,  # IV < RV by 12 points
        rv_30d=50.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_atm_options() -> list[OptionContract]:
    """Create ATM options for straddle."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    return [
        OptionContract(
            instrument_name="BTC-21JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            gamma=0.00015,
            theta=-85.0,
            vega=150.0,
            iv=60.0,
            bid=0.0450,
            ask=0.0480,
        ),
        OptionContract(
            instrument_name="BTC-21JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.52,
            gamma=0.00015,
            theta=-85.0,
            vega=150.0,
            iv=60.0,
            bid=0.0440,
            ask=0.0470,
        ),
    ]


@pytest.mark.asyncio
async def test_vol_arb_sell_vol_signal(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb generates sell straddle when IV overpriced."""
    strategy = VolArbStrategy(vol_arb_config)

    signal = await strategy.evaluate(high_iv_spread_metrics, sample_atm_options)

    assert signal is not None
    assert signal.strategy_type == StrategyType.VOL_ARB
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "sell"
    assert len(signal.contracts) == 2  # Put + Call
    assert signal.contracts[0].strike == signal.contracts[1].strike
    assert signal.contracts[0].expiry == signal.contracts[1].expiry
    assert "sell" in signal.reason.lower()


@pytest.mark.asyncio
async def test_vol_arb_requires_same_strike_and_expiry_straddle(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
) -> None:
    """Vol Arb should not mix expiries or strikes when building a straddle."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    options = [
        OptionContract(
            instrument_name="BTC-21JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            bid=0.0450,
            ask=0.0480,
        ),
        OptionContract(
            instrument_name="BTC-28JAN26-98000-C",
            strike=98000.0,
            expiry=expiry + timedelta(days=7),
            option_type="call",
            delta=0.52,
            bid=0.0440,
            ask=0.0470,
        ),
    ]
    strategy = VolArbStrategy(vol_arb_config)

    signal = await strategy.evaluate(high_iv_spread_metrics, options)

    assert signal is None


@pytest.mark.asyncio
async def test_vol_arb_buy_vol_signal(
    vol_arb_config: VolArbConfig,
    low_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb generates buy straddle when IV underpriced."""
    strategy = VolArbStrategy(vol_arb_config)

    signal = await strategy.evaluate(low_iv_spread_metrics, sample_atm_options)

    assert signal is not None
    assert signal.direction == "buy"
    assert "buy" in signal.reason.lower()


@pytest.mark.asyncio
async def test_vol_arb_hedge_signal_sell_vol_mode(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb hedge direction is correct for short straddle (sell_vol)."""
    strategy = VolArbStrategy(vol_arb_config)

    # Simulate active SHORT position (sell_vol)
    strategy.state.is_active = True
    strategy.state.position_id = "va-001"
    strategy.state.phase = "sell_vol"
    strategy.state.contracts = sample_atm_options

    # Price moved up, contract deltas shifted
    # Contract delta sum = -0.35 + 0.50 = 0.15
    # Position delta for SHORT = -0.15 (negative = short delta)
    sample_atm_options[0].delta = -0.35  # Put
    sample_atm_options[1].delta = 0.50   # Call

    signal = await strategy.manage(high_iv_spread_metrics, sample_atm_options)

    # Should generate hedge signal
    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.target_delta is not None
    # To hedge negative delta, we BUY underlying
    assert signal.direction == "buy"


@pytest.mark.asyncio
async def test_vol_arb_hedge_signal_buy_vol_mode(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb hedge direction is correct for long straddle (buy_vol)."""
    strategy = VolArbStrategy(vol_arb_config)

    # Simulate active LONG position (buy_vol)
    strategy.state.is_active = True
    strategy.state.position_id = "va-001"
    strategy.state.phase = "buy_vol"
    strategy.state.contracts = sample_atm_options

    # Price moved up, contract deltas shifted
    # Contract delta sum = -0.35 + 0.50 = 0.15
    # Position delta for LONG = 0.15 (positive = long delta)
    sample_atm_options[0].delta = -0.35  # Put
    sample_atm_options[1].delta = 0.50   # Call

    signal = await strategy.manage(high_iv_spread_metrics, sample_atm_options)

    # Should generate hedge signal
    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.target_delta is not None
    # To hedge positive delta, we SELL underlying
    assert signal.direction == "sell"


@pytest.mark.asyncio
async def test_vol_arb_hedge_uses_position_size_and_existing_hedge(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Vol arb should hedge only the unhedged net delta exposure."""
    strategy = VolArbStrategy(vol_arb_config)
    strategy.state.is_active = True
    strategy.state.position_id = "va-001"
    strategy.state.phase = "sell_vol"
    strategy.state.contracts = sample_atm_options
    strategy.state.position_size = 3.0

    sample_atm_options[0].delta = -0.35
    sample_atm_options[1].delta = 0.50

    signal = await strategy.manage(high_iv_spread_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.direction == "buy"
    assert signal.quantity == pytest.approx(0.45)

    strategy.state.hedge_delta = 0.45

    assert await strategy.manage(high_iv_spread_metrics, sample_atm_options) is None


@pytest.mark.asyncio
async def test_vol_arb_no_signal_neutral_spread(
    vol_arb_config: VolArbConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb no signal when IV-RV spread near zero."""
    strategy = VolArbStrategy(vol_arb_config)
    neutral_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        iv_rv_spread=3.0,  # Near zero
        rv_30d=47.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(neutral_metrics, sample_atm_options)

    assert signal is None


def test_vol_arb_strategy_type() -> None:
    """Test strategy type property."""
    config = VolArbConfig(name="va", enabled=True)
    strategy = VolArbStrategy(config)

    assert strategy.strategy_type == StrategyType.VOL_ARB
