"""Tests for delta hedger."""

import pytest
from datetime import datetime, timezone

from src.execution.delta_hedger import DeltaHedger, HedgerConfig
from src.brain.signal import OptionContract


@pytest.fixture
def hedger_config() -> HedgerConfig:
    """Create hedger config."""
    return HedgerConfig(
        rebalance_threshold=0.10,
        hard_limit=0.15,
    )


@pytest.fixture
def sample_contracts() -> list[OptionContract]:
    """Create sample option contracts with deltas."""
    expiry = datetime.now(timezone.utc)
    return [
        # Short put: position delta = +0.25
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,
        ),
        # Short call: position delta = -0.20
        OptionContract(
            instrument_name="BTC-31JAN26-102000-C",
            strike=102000.0,
            expiry=expiry,
            option_type="call",
            delta=0.20,
        ),
    ]


def test_calculate_portfolio_delta_long(hedger_config: HedgerConfig) -> None:
    """Test portfolio delta calculation for long positions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.50,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.50,
        ),
    ]

    # Long straddle: position delta = sum of contract deltas
    delta = hedger.calculate_portfolio_delta(contracts, direction="buy")

    assert delta == pytest.approx(0.0, abs=0.01)


def test_calculate_portfolio_delta_short(hedger_config: HedgerConfig) -> None:
    """Test portfolio delta calculation for short positions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.50,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.50,
        ),
    ]

    # Short straddle: position delta = negative of sum of contract deltas
    delta = hedger.calculate_portfolio_delta(contracts, direction="sell")

    assert delta == pytest.approx(0.0, abs=0.01)


def test_needs_hedge_within_threshold(
    hedger_config: HedgerConfig,
    sample_contracts: list[OptionContract],
) -> None:
    """Test no hedge needed when delta within threshold."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.05, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=0.05)

    assert result is None


def test_needs_hedge_exceeds_threshold(hedger_config: HedgerConfig) -> None:
    """Test hedge needed when delta exceeds threshold."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.12, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=0.12)

    assert result is not None
    assert result.direction == "sell"  # Positive delta -> sell to reduce
    assert result.quantity == pytest.approx(0.12, abs=0.01)


def test_needs_hedge_negative_delta(hedger_config: HedgerConfig) -> None:
    """Test hedge for negative delta."""
    hedger = DeltaHedger(hedger_config)

    # Delta = -0.15, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=-0.15)

    assert result is not None
    assert result.direction == "buy"  # Negative delta -> buy to reduce
    assert result.quantity == pytest.approx(0.15, abs=0.01)


def test_hard_limit_flag(hedger_config: HedgerConfig) -> None:
    """Test urgent flag when delta exceeds hard limit."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.18, hard limit = 0.15
    result = hedger.check_hedge_needed(portfolio_delta=0.18)

    assert result is not None
    assert result.urgent is True


def test_add_existing_hedge(hedger_config: HedgerConfig) -> None:
    """Test accounting for existing hedge position."""
    hedger = DeltaHedger(hedger_config)

    # Portfolio delta 0.25, but we have -0.20 hedge, net = 0.05
    result = hedger.check_hedge_needed(
        portfolio_delta=0.25,
        existing_hedge_delta=-0.20,
    )

    # Net delta = 0.05, within threshold
    assert result is None


def test_calculate_portfolio_delta_with_legs(hedger_config: HedgerConfig) -> None:
    """Test delta calculation with per-leg directions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-88000-P",
            strike=88000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
        ),
    ]
    legs_direction = ["sell", "buy"]  # Short 92k, long 88k

    # Short put @ -0.15: position delta = +0.15
    # Long put @ -0.05: position delta = -0.05
    # Net = +0.10
    delta = hedger.calculate_portfolio_delta_with_legs(contracts, legs_direction)

    assert delta == pytest.approx(0.10, abs=0.01)


def test_calculate_portfolio_delta_scales_by_quantity(hedger_config: HedgerConfig) -> None:
    """Test that delta is multiplied by quantity parameter."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,
        ),
    ]

    # Short put with delta=-0.25, quantity=1.0 -> position delta = +0.25
    delta_1x = hedger.calculate_portfolio_delta(contracts, direction="sell", quantity=1.0)
    assert delta_1x == pytest.approx(0.25, abs=0.01)

    # Same position with quantity=2.0 -> position delta = +0.50
    delta_2x = hedger.calculate_portfolio_delta(contracts, direction="sell", quantity=2.0)
    assert delta_2x == pytest.approx(0.50, abs=0.01)

    # Verify scaling is linear
    assert delta_2x == pytest.approx(delta_1x * 2.0, abs=0.01)


def test_calculate_portfolio_delta_with_legs_scales_by_quantity(
    hedger_config: HedgerConfig,
) -> None:
    """Test that multi-leg delta is multiplied by quantity parameter."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    # Iron condor put spread: short 92k, long 88k
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-88000-P",
            strike=88000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
        ),
    ]
    legs_direction = ["sell", "buy"]

    # Net delta = +0.10 per contract
    delta_1x = hedger.calculate_portfolio_delta_with_legs(
        contracts, legs_direction, quantity=1.0
    )
    assert delta_1x == pytest.approx(0.10, abs=0.01)

    # With 3 contracts: +0.30
    delta_3x = hedger.calculate_portfolio_delta_with_legs(
        contracts, legs_direction, quantity=3.0
    )
    assert delta_3x == pytest.approx(0.30, abs=0.01)
