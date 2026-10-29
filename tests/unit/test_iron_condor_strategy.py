"""Tests for Iron Condor strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.iron_condor import IronCondorStrategy, IronCondorConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def ic_config() -> IronCondorConfig:
    """Create Iron Condor strategy config."""
    # DTE range calibrated to match Deribit's expiry schedule (25-55 DTE)
    # Wing delta calibrated via scripts/calibrate_iron_condor_wing_delta.py (2026-02-02):
    # - 0.05 delta: Sharpe 11.23, 96.3% win rate
    # - max_delta_diff=0.08 to capture sparse ETH chain
    return IronCondorConfig(
        name="iron_condor",
        enabled=True,
        max_position_size=0.10,
        target_dte_min=25,
        target_dte_max=55,
        profit_target=0.50,
        short_delta=0.15,
        wing_delta=0.05,
        max_delta_diff=0.08,
    )


@pytest.fixture
def high_iv_metrics() -> MarketMetrics:
    """Create high IV market metrics."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=58.0,
        iv_rank=0.65,
        iv_rv_spread=12.0,
        rv_30d=46.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create sample option chain for iron condor."""
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    return [
        # Puts (from OTM to ATM)
        OptionContract(
            instrument_name="BTC-31JAN26-85000-P",
            strike=85000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
            bid=0.0020,
            ask=0.0025,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-88000-P",
            strike=88000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.08,
            bid=0.0040,
            ask=0.0050,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.12,
            bid=0.0070,
            ask=0.0085,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.16,
            bid=0.0110,
            ask=0.0125,
        ),
        # Calls (from ATM to OTM)
        OptionContract(
            instrument_name="BTC-31JAN26-102000-C",
            strike=102000.0,
            expiry=expiry,
            option_type="call",
            delta=0.16,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-105000-C",
            strike=105000.0,
            expiry=expiry,
            option_type="call",
            delta=0.10,
            bid=0.0060,
            ask=0.0072,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-108000-C",
            strike=108000.0,
            expiry=expiry,
            option_type="call",
            delta=0.06,
            bid=0.0030,
            ask=0.0040,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-110000-C",
            strike=110000.0,
            expiry=expiry,
            option_type="call",
            delta=0.04,
            bid=0.0018,
            ask=0.0025,
        ),
    ]


@pytest.mark.asyncio
async def test_iron_condor_generates_4_leg_signal(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor generates 4-leg signal."""
    strategy = IronCondorStrategy(ic_config)

    signal = await strategy.evaluate(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.strategy_type == StrategyType.IRON_CONDOR
    assert signal.action == SignalAction.OPEN
    assert len(signal.contracts) == 4
    assert signal.legs_direction is not None
    assert len(signal.legs_direction) == 4

    # Verify structure: sell put, buy put, sell call, buy call
    put_legs = [c for c in signal.contracts if c.option_type == "put"]
    call_legs = [c for c in signal.contracts if c.option_type == "call"]
    assert len(put_legs) == 2
    assert len(call_legs) == 2


@pytest.mark.asyncio
async def test_iron_condor_requires_high_iv_rank(
    ic_config: IronCondorConfig,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor requires IV Rank > 50%."""
    strategy = IronCondorStrategy(ic_config)
    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.35,  # Below 50%
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_iv_metrics, sample_option_chain)

    assert signal is None


@pytest.mark.asyncio
async def test_iron_condor_max_profit_and_loss(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor calculates max profit and loss."""
    strategy = IronCondorStrategy(ic_config)

    signal = await strategy.evaluate(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.max_profit is not None
    assert signal.max_profit > 0
    assert signal.max_loss is not None
    assert signal.max_loss > 0


@pytest.mark.asyncio
async def test_iron_condor_closes_at_profit_target(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor closes at 50% profit."""
    strategy = IronCondorStrategy(ic_config)

    # Set up active position
    strategy.state.is_active = True
    strategy.state.position_id = "ic-001"
    strategy.state.premium_received = 0.0100  # Net credit
    strategy.state.contracts = sample_option_chain[:4]

    # Simulate options decayed significantly
    for opt in sample_option_chain:
        opt.bid = (opt.bid or 0) * 0.4
        opt.ask = (opt.ask or 0) * 0.4

    signal = await strategy.manage(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE


def test_iron_condor_strategy_type() -> None:
    """Test strategy type property."""
    config = IronCondorConfig(name="ic", enabled=True)
    strategy = IronCondorStrategy(config)

    assert strategy.strategy_type == StrategyType.IRON_CONDOR


def test_iron_condor_max_loss_inverse() -> None:
    """Test max loss calculation for inverse (crypto-margined) options."""
    config = IronCondorConfig(name="ic", enabled=True, is_linear=False)
    strategy = IronCondorStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    contracts = [
        OptionContract(instrument_name="ETH-28MAR26-2200-P", strike=2200.0, expiry=expiry,
                       option_type="put", bid=0.0110, ask=0.0125),
        OptionContract(instrument_name="ETH-28MAR26-2000-P", strike=2000.0, expiry=expiry,
                       option_type="put", bid=0.0020, ask=0.0025),
        OptionContract(instrument_name="ETH-28MAR26-3000-C", strike=3000.0, expiry=expiry,
                       option_type="call", bid=0.0100, ask=0.0115),
        OptionContract(instrument_name="ETH-28MAR26-3200-C", strike=3200.0, expiry=expiry,
                       option_type="call", bid=0.0018, ask=0.0025),
    ]
    # net_credit = sell_put_bid + sell_call_bid - buy_put_ask - buy_call_ask
    # = 0.0110 + 0.0100 - 0.0025 - 0.0025 = 0.0160
    net_credit = 0.0160
    spot_price = 2700.0

    max_loss = strategy._calculate_max_loss(contracts, net_credit, spot_price)

    # Widest spread = max(200, 200) = 200 USD
    # width_in_eth = 200 / 2700 = 0.07407
    # max_loss = 0.07407 - 0.0160 = 0.05807
    expected = (200.0 / 2700.0) - net_credit
    assert abs(max_loss - expected) < 0.0001


def test_iron_condor_max_loss_linear() -> None:
    """Test max loss calculation for linear (USDC) options.

    For linear options, spread width and net credit are both in USD,
    so no spot price conversion is needed.
    """
    config = IronCondorConfig(name="ic", enabled=True, is_linear=True)
    strategy = IronCondorStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    contracts = [
        OptionContract(instrument_name="ETH_USDC-28MAR26-2200-P", strike=2200.0, expiry=expiry,
                       option_type="put", bid=50.0, ask=55.0),
        OptionContract(instrument_name="ETH_USDC-28MAR26-2000-P", strike=2000.0, expiry=expiry,
                       option_type="put", bid=10.0, ask=12.0),
        OptionContract(instrument_name="ETH_USDC-28MAR26-3000-C", strike=3000.0, expiry=expiry,
                       option_type="call", bid=45.0, ask=50.0),
        OptionContract(instrument_name="ETH_USDC-28MAR26-3200-C", strike=3200.0, expiry=expiry,
                       option_type="call", bid=8.0, ask=10.0),
    ]
    # net_credit = 50.0 + 45.0 - 12.0 - 10.0 = 73.0 USDC
    net_credit = 73.0
    spot_price = 2700.0  # Should be irrelevant for linear

    max_loss = strategy._calculate_max_loss(contracts, net_credit, spot_price)

    # Widest spread = max(200, 200) = 200 USDC
    # max_loss = 200 - 73 = 127 USDC (no conversion)
    expected = 200.0 - net_credit
    assert abs(max_loss - expected) < 0.01


@pytest.mark.asyncio
async def test_spread_value_uses_mark_not_bidask() -> None:
    """Test spread value uses mark_price, not inflated bid/ask.

    On testnet, ask prices can spike due to zero liquidity, producing
    false loss limit triggers. The spread value calculation should use
    mark_price (exchange-computed fair value) for reliable P&L monitoring.
    """
    config = IronCondorConfig(name="ic", enabled=True, is_linear=True, loss_limit=1.0)
    strategy = IronCondorStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=33)

    # Position contracts (what we hold)
    position_contracts = [
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call"),
    ]

    strategy.state.is_active = True
    strategy.state.position_id = "ic-test"
    strategy.state.premium_received = 57.60
    strategy.state.position_size = 1.0
    strategy.state.contracts = position_contracts

    # Option chain with ILLIQUID bid/ask but REASONABLE mark prices.
    # Mark prices show the spread is worth ~$46 to close (small profit).
    # But the ask on the 1600-P is $200 (testnet liquidity spike),
    # making the bid/ask-based close cost ~$210 (false -265% loss).
    chain = [
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put",
                       bid=35.0, ask=200.0,  # Absurd ask - testnet illiquidity
                       mark_price=35.8),
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put",
                       bid=9.4, ask=11.0, mark_price=10.4),
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call",
                       bid=26.0, ask=27.4, mark_price=26.9),
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call",
                       bid=5.2, ask=6.4, mark_price=6.1),
    ]

    metrics = MarketMetrics(
        btc_price=1990.0, dvol=68.5, iv_rank=0.56,
        rv_30d=55.0, timestamp=datetime.now(timezone.utc),
    )

    # Should NOT trigger loss limit - mark-based close cost is ~$46,
    # well below the $57.60 premium (position is profitable)
    signal = await strategy.manage(metrics, chain)
    assert signal is None, (
        f"False loss limit triggered due to illiquid bid/ask. "
        f"Signal reason: {signal.reason if signal else 'N/A'}"
    )


@pytest.mark.asyncio
async def test_loss_limit_triggers_on_genuine_mark_loss() -> None:
    """Test loss limit still triggers when mark prices show real loss."""
    config = IronCondorConfig(name="ic", enabled=True, is_linear=True, loss_limit=1.0)
    strategy = IronCondorStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=33)

    position_contracts = [
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call"),
    ]

    strategy.state.is_active = True
    strategy.state.position_id = "ic-test"
    strategy.state.premium_received = 57.60
    strategy.state.position_size = 1.0
    strategy.state.contracts = position_contracts

    # Mark prices show genuine loss: spread costs $180 to close vs $57.60 credit
    # This is a real -212% loss (e.g., ETH moved close to a short strike)
    chain = [
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put",
                       bid=120.0, ask=125.0, mark_price=122.0),
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put",
                       bid=18.0, ask=20.0, mark_price=19.0),
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call",
                       bid=70.0, ask=75.0, mark_price=72.0),
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call",
                       bid=10.0, ask=12.0, mark_price=11.0),
    ]

    metrics = MarketMetrics(
        btc_price=1650.0, dvol=85.0, iv_rank=0.90,
        rv_30d=70.0, timestamp=datetime.now(timezone.utc),
    )

    # mark close cost = 122.0 - 19.0 + 72.0 - 11.0 = 164.0
    # profit_pct = (57.60 - 164.0) / 57.60 = -184.7% -> should trigger
    signal = await strategy.manage(metrics, chain)
    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "Loss limit" in signal.reason


@pytest.mark.asyncio
async def test_profit_target_uses_execution_prices_not_mark() -> None:
    """Test IC profit target uses bid/ask execution prices, not mark.

    Mark can diverge from execution prices on illiquid testnet. When mark
    shows profit but the actual close cost (ask for shorts, bid for longs)
    would result in a loss, the profit target should NOT trigger.
    """
    config = IronCondorConfig(name="ic", enabled=True, is_linear=True, profit_target=0.50)
    strategy = IronCondorStrategy(config)

    expiry = datetime.now(timezone.utc) + timedelta(days=33)

    position_contracts = [
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call"),
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call"),
    ]

    strategy.state.is_active = True
    strategy.state.position_id = "ic-test"
    strategy.state.premium_received = 57.60
    strategy.state.position_size = 1.0
    strategy.state.contracts = position_contracts

    # Mark prices show profit: spread costs $25 to close vs $57.60 credit = 56.6% profit
    # But execution prices (ask for shorts, bid for longs) show close cost of $60 = loss!
    # Short legs: buy back at ask. Long legs: sell at bid.
    chain = [
        # Short put: mark=$20, but ask=$45 (illiquid, costs more to buy back)
        OptionContract(instrument_name="ETH_USDC-27MAR26-1600-P", strike=1600.0,
                       expiry=expiry, option_type="put",
                       bid=18.0, ask=45.0, mark_price=20.0),
        # Long put: mark=$8, bid=$3 (illiquid, receive less when selling)
        OptionContract(instrument_name="ETH_USDC-27MAR26-1300-P", strike=1300.0,
                       expiry=expiry, option_type="put",
                       bid=3.0, ask=12.0, mark_price=8.0),
        # Short call: mark=$12, but ask=$30 (illiquid, costs more to buy back)
        OptionContract(instrument_name="ETH_USDC-27MAR26-2500-C", strike=2500.0,
                       expiry=expiry, option_type="call",
                       bid=10.0, ask=30.0, mark_price=12.0),
        # Long call: mark=$5, bid=$2 (illiquid, receive less when selling)
        OptionContract(instrument_name="ETH_USDC-27MAR26-3000-C", strike=3000.0,
                       expiry=expiry, option_type="call",
                       bid=2.0, ask=8.0, mark_price=5.0),
    ]
    # Mark-based close cost: (20 - 8) + (12 - 5) = 19. profit = (57.60 - 19)/57.60 = 67%
    # Exec-based close cost: (45 - 3) + (30 - 2) = 70. profit = (57.60 - 70)/57.60 = -21.5%

    metrics = MarketMetrics(
        btc_price=1990.0, dvol=68.5, iv_rank=0.56,
        rv_30d=55.0, timestamp=datetime.now(timezone.utc),
    )

    # Should NOT trigger profit target - execution prices show a loss
    signal = await strategy.manage(metrics, chain)
    assert signal is None or signal.reason.find("Profit") == -1, (
        f"False profit target triggered! Mark shows profit but execution "
        f"prices show a loss. Signal: {signal.reason if signal else 'N/A'}"
    )
