"""Tests for Wheel strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.wheel import WheelStrategy, WheelConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def wheel_config() -> WheelConfig:
    """Create Wheel strategy config."""
    return WheelConfig(
        name="wheel",
        enabled=True,
        max_position_size=0.10,
        target_dte_min=30,
        target_dte_max=45,
        profit_target=0.50,
        target_delta=0.25,
        min_iv_rank=0.30,
    )


@pytest.fixture
def sample_metrics() -> MarketMetrics:
    """Create sample market metrics."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        rv_30d=48.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create sample option chain."""
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    return [
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.18,
            iv=50.0,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,
            iv=51.0,
            bid=0.0150,
            ask=0.0165,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-95000-P",
            strike=95000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.35,
            iv=52.0,
            bid=0.0220,
            ask=0.0240,
        ),
        # Calls for covered call phase
        OptionContract(
            instrument_name="BTC-31JAN26-100000-C",
            strike=100000.0,
            expiry=expiry,
            option_type="call",
            delta=0.35,
            iv=52.0,
            bid=0.0200,
            ask=0.0220,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-103000-C",
            strike=103000.0,
            expiry=expiry,
            option_type="call",
            delta=0.25,
            iv=51.0,
            bid=0.0140,
            ask=0.0155,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-105000-C",
            strike=105000.0,
            expiry=expiry,
            option_type="call",
            delta=0.18,
            iv=50.0,
            bid=0.0090,
            ask=0.0105,
        ),
    ]


@pytest.mark.asyncio
async def test_wheel_evaluate_generates_csp_signal(
    wheel_config: WheelConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel generates sell put signal when conditions met."""
    strategy = WheelStrategy(wheel_config)

    signal = await strategy.evaluate(sample_metrics, sample_option_chain)

    assert signal is not None
    assert signal.strategy_type == StrategyType.WHEEL
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "sell"
    assert len(signal.contracts) == 1
    assert signal.contracts[0].option_type == "put"
    # Should select put with delta closest to -0.25
    assert signal.contracts[0].delta is not None
    assert -0.30 <= signal.contracts[0].delta <= -0.20


@pytest.mark.asyncio
async def test_wheel_evaluate_requires_minimum_iv_rank(
    wheel_config: WheelConfig,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel requires IV Rank > 30% for entry."""
    strategy = WheelStrategy(wheel_config)
    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=35.0,
        iv_rank=0.20,  # Below 30% threshold
        rv_30d=40.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_iv_metrics, sample_option_chain)

    assert signal is None


@pytest.mark.asyncio
async def test_wheel_manage_closes_at_profit_target(
    wheel_config: WheelConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel closes position at 50% profit."""
    strategy = WheelStrategy(wheel_config)

    # Simulate active position
    strategy.state.is_active = True
    strategy.state.position_id = "wheel-001"
    strategy.state.phase = "csp"
    strategy.state.premium_received = 0.0160  # Entry premium
    strategy.state.contracts = [sample_option_chain[1]]  # 92k put

    # Current price is much lower (profitable)
    sample_option_chain[1].bid = 0.0070
    sample_option_chain[1].ask = 0.0080

    signal = await strategy.manage(sample_metrics, sample_option_chain)

    # Profit = 0.016 - 0.0075 = 0.0085 (53% of premium)
    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "profit" in signal.reason.lower()


@pytest.mark.asyncio
async def test_wheel_phase_transition_to_covered_call(
    wheel_config: WheelConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel transitions from CSP to covered call on assignment."""
    strategy = WheelStrategy(wheel_config)

    # Simulate assignment by setting phase to covered_call with CSP contract
    strategy.state.is_active = True
    strategy.state.position_id = "wheel-001"
    strategy.state.phase = "covered_call"
    strategy.state.entry_price = 92000.0  # Spot at CSP entry
    # The CSP put contract that was assigned (strike is the assignment price)
    strategy.state.contracts = [sample_option_chain[1]]  # 92k put

    signal = await strategy.evaluate(sample_metrics, sample_option_chain)

    # Should generate sell call signal
    assert signal is not None
    assert signal.direction == "sell"
    assert len(signal.contracts) == 1
    assert signal.contracts[0].option_type == "call"


def test_wheel_strategy_type() -> None:
    """Test strategy type property."""
    config = WheelConfig(name="wheel", enabled=True)
    strategy = WheelStrategy(config)

    assert strategy.strategy_type == StrategyType.WHEEL


@pytest.mark.asyncio
async def test_profit_target_uses_ask_not_mark() -> None:
    """Test profit target uses ask price, not mark, to prevent false exits.

    On testnet, mark_price can diverge below the actual ask price. When
    mark shows 58% profit but buying back at the ask would lose money,
    the bot should NOT close the position. This prevents the exit-entry
    loop seen on testnet where the bot sells at $79, mark says $33 (58%
    profit), but buyback costs $82 (actual loss of $2.70 per cycle).
    """
    config = WheelConfig(name="wheel", enabled=True, profit_target=0.50)
    strategy = WheelStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=33)

    # Position: sold 0.9 ETH_USDC-27MAR26-1800-P at $79 = $71.10 premium
    position_contract = OptionContract(
        instrument_name="ETH_USDC-27MAR26-1800-P",
        strike=1800.0,
        expiry=expiry,
        option_type="put",
        delta=-0.28,
    )

    strategy.state.is_active = True
    strategy.state.position_id = "wheel-test"
    strategy.state.premium_received = 71.10  # Sold 0.9 @ $79
    strategy.state.position_size = 0.9
    strategy.state.contracts = [position_contract]

    # Current chain: mark=$33 but ask=$82
    # Mark-based profit: (71.10 - 33*0.9) / 71.10 = 58.2% -> triggers 50% target
    # Ask-based close cost: 82 * 0.9 = $73.80 -> PnL = 71.10 - 73.80 = -$2.70 (loss!)
    chain = [
        OptionContract(
            instrument_name="ETH_USDC-27MAR26-1800-P",
            strike=1800.0,
            expiry=expiry,
            option_type="put",
            delta=-0.28,
            bid=35.0,
            ask=82.0,
            mark_price=33.0,
        ),
    ]

    metrics = MarketMetrics(
        btc_price=1980.0, dvol=68.7, iv_rank=0.56,
        rv_30d=55.0, timestamp=datetime.now(timezone.utc),
    )

    # Should NOT trigger profit target - actual close at ask would lose money
    signal = await strategy.manage(metrics, chain)
    assert signal is None, (
        f"False profit target triggered! Mark shows profit but ask-based "
        f"close would result in a loss. Signal: {signal.reason if signal else 'N/A'}"
    )


@pytest.mark.asyncio
async def test_profit_target_triggers_when_ask_shows_real_profit() -> None:
    """Test profit target still triggers when ask-based close is profitable."""
    config = WheelConfig(name="wheel", enabled=True, profit_target=0.50)
    strategy = WheelStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=33)

    position_contract = OptionContract(
        instrument_name="ETH_USDC-27MAR26-1800-P",
        strike=1800.0,
        expiry=expiry,
        option_type="put",
        delta=-0.28,
    )

    strategy.state.is_active = True
    strategy.state.position_id = "wheel-test"
    strategy.state.premium_received = 71.10
    strategy.state.position_size = 0.9
    strategy.state.contracts = [position_contract]

    # Both mark and ask show genuine profit:
    # Ask = $35, close cost = 35 * 0.9 = $31.50
    # Profit = (71.10 - 31.50) / 71.10 = 55.7% -> should trigger
    chain = [
        OptionContract(
            instrument_name="ETH_USDC-27MAR26-1800-P",
            strike=1800.0,
            expiry=expiry,
            option_type="put",
            delta=-0.20,
            bid=33.0,
            ask=35.0,
            mark_price=34.0,
        ),
    ]

    metrics = MarketMetrics(
        btc_price=1980.0, dvol=68.7, iv_rank=0.56,
        rv_30d=55.0, timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.manage(metrics, chain)
    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "profit" in signal.reason.lower()
