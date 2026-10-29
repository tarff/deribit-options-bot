"""Tests for Calendar Spread strategy."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.calendar_spread import CalendarSpreadStrategy, CalendarSpreadConfig
from src.brain.signal import StrategyType, SignalAction, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def calendar_config() -> CalendarSpreadConfig:
    """Create calendar spread config for testing.

    Uses calibrated values from scripts/calibrate_calendar_spread.py
    (999 days ETH data, 1600 parameter combinations tested).
    """
    return CalendarSpreadConfig(
        name="calendar_spread",
        enabled=True,
        max_iv_rank=0.20,  # Calibrated: 20% appears in 40% of top-20 by Sharpe
        short_dte_min=14,
        short_dte_max=21,
        long_dte_min=45,
        long_dte_max=60,
        option_type="put",
        profit_target=0.25,  # Calibrated: 25% appears in 40% of top-20
        exit_price_move_pct=0.12,  # Calibrated: 12% appears in 60% of top-20
    )


@pytest.fixture
def calendar_strategy(calendar_config: CalendarSpreadConfig) -> CalendarSpreadStrategy:
    """Create calendar spread strategy instance."""
    return CalendarSpreadStrategy(calendar_config)


@pytest.fixture
def low_iv_metrics() -> MarketMetrics:
    """Create metrics with low IV (should trigger calendar).

    IV Rank of 15% is below the calibrated 20% threshold.
    """
    return MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.15,  # 15% IV Rank - below 20% threshold
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def high_iv_metrics() -> MarketMetrics:
    """Create metrics with high IV (should NOT trigger calendar).

    IV Rank of 35% is above the calibrated 20% threshold.
    """
    return MarketMetrics(
        btc_price=97000.0,
        dvol=65.0,
        iv_rank=0.35,  # 35% IV Rank - above 20% threshold
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def option_chain_with_calendar() -> list[OptionContract]:
    """Create option chain suitable for calendar spread.

    Creates puts at ATM strike with two expiries:
    - Front month: ~18 DTE (within 14-21 range)
    - Back month: ~52 DTE (within 45-60 range)
    """
    now = datetime.now(timezone.utc)
    atm_strike = 97000.0

    # Front month expiry (~18 DTE)
    front_expiry = now + timedelta(days=18)
    # Back month expiry (~52 DTE)
    back_expiry = now + timedelta(days=52)

    options = [
        # Front month put (to sell)
        OptionContract(
            instrument_name=f"BTC-{front_expiry.strftime('%d%b%y').upper()}-{int(atm_strike)}-P",
            strike=atm_strike,
            expiry=front_expiry,
            option_type="put",
            delta=-0.48,
            gamma=0.00015,
            theta=-80.0,  # Higher theta for front month
            vega=90.0,
            iv=48.0,
            bid=0.025,
            ask=0.027,
        ),
        # Back month put (to buy)
        OptionContract(
            instrument_name=f"BTC-{back_expiry.strftime('%d%b%y').upper()}-{int(atm_strike)}-P",
            strike=atm_strike,
            expiry=back_expiry,
            option_type="put",
            delta=-0.45,
            gamma=0.00010,
            theta=-45.0,  # Lower theta for back month
            vega=150.0,
            iv=50.0,
            bid=0.045,
            ask=0.048,
        ),
        # Add some other strikes for diversity
        OptionContract(
            instrument_name=f"BTC-{front_expiry.strftime('%d%b%y').upper()}-95000-P",
            strike=95000.0,
            expiry=front_expiry,
            option_type="put",
            delta=-0.35,
            gamma=0.00012,
            theta=-60.0,
            vega=80.0,
            iv=49.0,
            bid=0.018,
            ask=0.020,
        ),
    ]

    return options


# =============================================================================
# STRATEGY TYPE TESTS
# =============================================================================


def test_strategy_type(calendar_strategy: CalendarSpreadStrategy) -> None:
    """Test strategy type is correct."""
    assert calendar_strategy.strategy_type == StrategyType.CALENDAR_SPREAD


def test_initial_state(calendar_strategy: CalendarSpreadStrategy) -> None:
    """Test initial state is inactive."""
    assert not calendar_strategy.state.is_active
    assert calendar_strategy.state.contracts == []


# =============================================================================
# ENTRY CONDITION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_entry_on_low_iv(
    calendar_strategy: CalendarSpreadStrategy,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test entry signal generated when IV is low."""
    signal = await calendar_strategy.evaluate(low_iv_metrics, option_chain_with_calendar)

    assert signal is not None
    assert signal.strategy_type == StrategyType.CALENDAR_SPREAD
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "buy"  # Net debit
    assert len(signal.contracts) == 2
    assert signal.legs_direction == ["sell", "buy"]
    assert "low IV" in signal.reason


@pytest.mark.asyncio
async def test_no_entry_on_high_iv(
    calendar_strategy: CalendarSpreadStrategy,
    high_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test no entry when IV is high (Wheel should handle this)."""
    signal = await calendar_strategy.evaluate(high_iv_metrics, option_chain_with_calendar)

    assert signal is None


@pytest.mark.asyncio
async def test_no_entry_when_active(
    calendar_strategy: CalendarSpreadStrategy,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test no entry when already has active position."""
    # Activate strategy
    calendar_strategy.activate("test-123", 97000.0, "open")

    signal = await calendar_strategy.evaluate(low_iv_metrics, option_chain_with_calendar)

    assert signal is None


@pytest.mark.asyncio
async def test_no_entry_when_disabled(
    calendar_config: CalendarSpreadConfig,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test no entry when strategy is disabled."""
    calendar_config.enabled = False
    strategy = CalendarSpreadStrategy(calendar_config)

    signal = await strategy.evaluate(low_iv_metrics, option_chain_with_calendar)

    assert signal is None


@pytest.mark.asyncio
async def test_no_entry_with_missing_iv_rank(
    calendar_strategy: CalendarSpreadStrategy,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test no entry when IV rank is not available."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=None,  # Missing
        timestamp=datetime.now(timezone.utc),
    )

    signal = await calendar_strategy.evaluate(metrics, option_chain_with_calendar)

    assert signal is None


# =============================================================================
# CONTRACT SELECTION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_selects_correct_expiries(
    calendar_strategy: CalendarSpreadStrategy,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test that correct front/back month options are selected."""
    signal = await calendar_strategy.evaluate(low_iv_metrics, option_chain_with_calendar)

    assert signal is not None
    short_leg = signal.contracts[0]
    long_leg = signal.contracts[1]

    # Verify short leg is front month (earlier expiry)
    assert short_leg.expiry < long_leg.expiry

    # Verify both are same strike
    assert short_leg.strike == long_leg.strike

    # Verify both are puts
    assert short_leg.option_type == "put"
    assert long_leg.option_type == "put"


@pytest.mark.asyncio
async def test_no_entry_without_matching_options(
    calendar_strategy: CalendarSpreadStrategy,
    low_iv_metrics: MarketMetrics,
) -> None:
    """Test no entry when option chain doesn't have matching strikes/expiries."""
    # Empty chain
    signal = await calendar_strategy.evaluate(low_iv_metrics, [])
    assert signal is None

    # Chain with only front month
    now = datetime.now(timezone.utc)
    front_only = [
        OptionContract(
            instrument_name="BTC-TEST-97000-P",
            strike=97000.0,
            expiry=now + timedelta(days=18),
            option_type="put",
            delta=-0.48,
            bid=0.025,
            ask=0.027,
        ),
    ]
    signal = await calendar_strategy.evaluate(low_iv_metrics, front_only)
    assert signal is None


# =============================================================================
# MANAGE PHASE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_manage_inactive(
    calendar_strategy: CalendarSpreadStrategy,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test manage returns None when not active."""
    signal = await calendar_strategy.manage(low_iv_metrics, option_chain_with_calendar)
    assert signal is None


@pytest.mark.asyncio
async def test_close_on_price_move(
    calendar_strategy: CalendarSpreadStrategy,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test close signal when price moves too far from strike.

    Exit threshold is calibrated at 12%, so price must move >12%.
    """
    # Activate with contracts at 97000 strike
    calendar_strategy.activate("test-123", 97000.0, "open")
    calendar_strategy.state.contracts = option_chain_with_calendar[:2]

    # Price moved 15% from strike (above 12% threshold)
    metrics = MarketMetrics(
        btc_price=111550.0,  # ~15% above 97000
        dvol=45.0,
        iv_rank=0.15,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await calendar_strategy.manage(metrics, option_chain_with_calendar)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "moved" in signal.reason.lower()


@pytest.mark.asyncio
async def test_close_on_short_leg_expiry(
    calendar_config: CalendarSpreadConfig,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test close signal when short leg expires."""
    strategy = CalendarSpreadStrategy(calendar_config)
    strategy.activate("test-123", 97000.0, "open")

    # Create contracts with short leg already expired
    expired_short = OptionContract(
        instrument_name="BTC-EXPIRED-97000-P",
        strike=97000.0,
        expiry=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
        option_type="put",
        delta=-0.48,
        bid=0.001,
        ask=0.002,
    )
    active_long = option_chain_with_calendar[1]  # Back month still active

    strategy.state.contracts = [expired_short, active_long]

    signal = await strategy.manage(low_iv_metrics, option_chain_with_calendar)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "expired" in signal.reason.lower()
    # Only the long leg should be closed — submitting a close for the
    # expired short instrument returns 'Invalid params' from Deribit.
    assert len(signal.contracts) == 1
    assert signal.contracts[0].instrument_name == active_long.instrument_name
    assert signal.legs_direction == ["sell"]


@pytest.mark.asyncio
async def test_close_on_short_leg_expiry_uses_expiry_role_when_contracts_reordered(
    calendar_config: CalendarSpreadConfig,
    low_iv_metrics: MarketMetrics,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Restored calendar contracts should not depend on DB row order."""
    strategy = CalendarSpreadStrategy(calendar_config)
    strategy.activate("test-123", 97000.0, "open")
    expired_short = OptionContract(
        instrument_name="BTC-EXPIRED-97000-P",
        strike=97000.0,
        expiry=datetime.now(timezone.utc) - timedelta(days=1),
        option_type="put",
        delta=-0.48,
        bid=0.001,
        ask=0.002,
    )
    active_long = option_chain_with_calendar[1]
    strategy.state.contracts = [active_long, expired_short]

    signal = await strategy.manage(low_iv_metrics, option_chain_with_calendar)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert signal.contracts == [active_long]
    assert signal.legs_direction == ["sell"]


def test_calendar_execution_value_treats_zero_bid_as_real_price(
    calendar_strategy: CalendarSpreadStrategy,
) -> None:
    """A zero bid on the long leg means no closeable sale value."""
    now = datetime.now(timezone.utc)
    short_leg = OptionContract(
        instrument_name="BTC-SHORT-97000-P",
        strike=97000.0,
        expiry=now + timedelta(days=18),
        option_type="put",
        bid=0.01,
        ask=0.02,
        mark_price=0.02,
    )
    long_leg = OptionContract(
        instrument_name="BTC-LONG-97000-P",
        strike=97000.0,
        expiry=now + timedelta(days=52),
        option_type="put",
        bid=0.0,
        ask=0.11,
        mark_price=0.10,
    )
    calendar_strategy.state.contracts = [short_leg, long_leg]
    calendar_strategy.state.position_size = 1.0

    value = calendar_strategy._get_current_spread_value(
        [short_leg, long_leg],
        use_mark=False,
    )

    assert value == pytest.approx(-0.02)


@pytest.mark.asyncio
async def test_calendar_profit_target_accounts_for_entry_fees(
    calendar_strategy: CalendarSpreadStrategy,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Entry fees inflate the cost basis used in the profit-target check."""
    calendar_strategy.activate("test-123", 97000.0, "open")
    calendar_strategy.state.contracts = option_chain_with_calendar[:2]
    calendar_strategy.state.position_size = 1.0
    # Gross debit 0.02, fees 0.005 -> true cost basis 0.025.
    calendar_strategy.state.premium_received = -0.02
    calendar_strategy.state.entry_fees = 0.005
    # Drive spread value to 0.026 — would clear a 25% target on gross debit
    # (0.026 / 0.02 - 1 = 30%) but NOT on the fee-inclusive basis
    # (0.026 / 0.025 - 1 = 4%).
    short_leg = option_chain_with_calendar[0]
    long_leg = option_chain_with_calendar[1]
    short_leg.ask = 0.024
    short_leg.bid = 0.022
    long_leg.bid = 0.050
    long_leg.ask = 0.052
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.15,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await calendar_strategy.manage(metrics, option_chain_with_calendar)

    if signal is not None:
        assert "profit target" not in signal.reason.lower()


# =============================================================================
# NET DEBIT CALCULATION TESTS
# =============================================================================


def test_net_debit_calculation(calendar_strategy: CalendarSpreadStrategy) -> None:
    """Test net debit is calculated correctly (long costs more than short credit)."""
    now = datetime.now(timezone.utc)

    contracts = [
        OptionContract(  # Short (sell) - receive credit
            instrument_name="BTC-SHORT-97000-P",
            strike=97000.0,
            expiry=now + timedelta(days=18),
            option_type="put",
            bid=0.025,
            ask=0.027,
        ),
        OptionContract(  # Long (buy) - pay debit
            instrument_name="BTC-LONG-97000-P",
            strike=97000.0,
            expiry=now + timedelta(days=52),
            option_type="put",
            bid=0.045,
            ask=0.048,
        ),
    ]

    net_debit = calendar_strategy._calculate_net_debit(contracts, ["sell", "buy"])

    # Short: sell uses bid = 0.025, Long: buy uses ask = 0.048
    # Net debit = 0.048 - 0.025 = 0.023
    expected = 0.048 - 0.025
    assert abs(net_debit - expected) < 0.001


# =============================================================================
# ATM STRIKE FINDING TESTS
# =============================================================================


def test_find_atm_strike(
    calendar_strategy: CalendarSpreadStrategy,
    option_chain_with_calendar: list[OptionContract],
) -> None:
    """Test ATM strike is found correctly."""
    strike = calendar_strategy._find_atm_strike(97000.0, option_chain_with_calendar)
    assert strike == 97000.0

    # Price slightly off ATM
    strike = calendar_strategy._find_atm_strike(96500.0, option_chain_with_calendar)
    assert strike == 97000.0  # Closest strike


def test_find_atm_strike_empty_chain(calendar_strategy: CalendarSpreadStrategy) -> None:
    """Test ATM strike with empty chain."""
    strike = calendar_strategy._find_atm_strike(97000.0, [])
    assert strike is None
