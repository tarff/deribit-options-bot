"""Tests for option selection helpers."""

import pytest
from datetime import datetime, timezone, timedelta

from src.data.option_selector import OptionSelector
from src.brain.signal import OptionContract


@pytest.fixture
def sample_options() -> list[OptionContract]:
    """Create sample option chain for testing."""
    base_expiry = datetime.now(timezone.utc) + timedelta(days=30)

    return [
        # Puts at various strikes
        OptionContract(
            instrument_name="BTC-30JAN26-90000-P",
            strike=90000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.15,
            bid=0.0080,
            ask=0.0090,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-92000-P",
            strike=92000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.20,
            bid=0.0120,
            ask=0.0135,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-95000-P",
            strike=95000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.30,
            bid=0.0200,
            ask=0.0220,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-97000-P",
            strike=97000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.45,
            bid=0.0350,
            ask=0.0380,
        ),
        # Calls at various strikes
        OptionContract(
            instrument_name="BTC-30JAN26-100000-C",
            strike=100000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.45,
            bid=0.0340,
            ask=0.0370,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-103000-C",
            strike=103000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.30,
            bid=0.0180,
            ask=0.0200,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-105000-C",
            strike=105000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.20,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-108000-C",
            strike=108000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.12,
            bid=0.0050,
            ask=0.0060,
        ),
    ]


def test_find_put_by_delta(sample_options: list[OptionContract]) -> None:
    """Test finding put option by target delta."""
    selector = OptionSelector(sample_options)

    # Find put with delta closest to -0.25
    put = selector.find_by_delta(target_delta=-0.25, option_type="put")

    assert put is not None
    assert put.option_type == "put"
    # Should find the -0.20 or -0.30 delta put
    assert put.delta is not None
    assert -0.35 <= put.delta <= -0.15


def test_find_call_by_delta(sample_options: list[OptionContract]) -> None:
    """Test finding call option by target delta."""
    selector = OptionSelector(sample_options)

    # Find call with delta closest to 0.25
    call = selector.find_by_delta(target_delta=0.25, option_type="call")

    assert call is not None
    assert call.option_type == "call"
    assert call.delta is not None
    assert 0.15 <= call.delta <= 0.35


def test_find_atm_straddle(sample_options: list[OptionContract]) -> None:
    """Test finding ATM put and call for straddle."""
    selector = OptionSelector(sample_options)

    # Find ATM options (delta ~0.50)
    put = selector.find_by_delta(target_delta=-0.50, option_type="put")
    call = selector.find_by_delta(target_delta=0.50, option_type="call")

    assert put is not None
    assert call is not None
    # Should be closest to ATM
    assert abs(put.delta or 0) >= 0.40
    assert abs(call.delta or 0) >= 0.40


def test_find_matching_straddle_requires_same_strike_and_expiry() -> None:
    """A straddle must use a liquid put/call pair at identical strike and expiry."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    selector = OptionSelector([
        OptionContract(
            instrument_name="BTC-21JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            bid=0.045,
            ask=0.048,
        ),
        OptionContract(
            instrument_name="BTC-21JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.52,
            bid=0.044,
            ask=0.047,
        ),
    ])

    straddle = selector.find_matching_straddle()

    assert straddle is not None
    put, call = straddle
    assert put.option_type == "put"
    assert call.option_type == "call"
    assert put.strike == call.strike
    assert put.expiry == call.expiry


def test_find_matching_straddle_rejects_mismatched_pair() -> None:
    """Near-ATM put and call cannot be mixed across strikes or expiries."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    selector = OptionSelector([
        OptionContract(
            instrument_name="BTC-21JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            bid=0.045,
            ask=0.048,
        ),
        OptionContract(
            instrument_name="BTC-28JAN26-98000-C",
            strike=98000.0,
            expiry=expiry + timedelta(days=7),
            option_type="call",
            delta=0.52,
            bid=0.044,
            ask=0.047,
        ),
    ])

    assert selector.find_matching_straddle() is None


def test_find_matching_straddle_scores_duplicate_put_candidates() -> None:
    """Duplicate strike/expiry candidates should keep the best delta match."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    weaker_put = OptionContract(
        instrument_name="BTC-21JAN26-97000-P-WEAK",
        strike=97000.0,
        expiry=expiry,
        option_type="put",
        delta=-0.41,
        bid=0.041,
        ask=0.043,
    )
    better_put = OptionContract(
        instrument_name="BTC-21JAN26-97000-P-BEST",
        strike=97000.0,
        expiry=expiry,
        option_type="put",
        delta=-0.49,
        bid=0.045,
        ask=0.048,
    )
    call = OptionContract(
        instrument_name="BTC-21JAN26-97000-C",
        strike=97000.0,
        expiry=expiry,
        option_type="call",
        delta=0.52,
        bid=0.044,
        ask=0.047,
    )
    selector = OptionSelector([weaker_put, better_put, call])

    straddle = selector.find_matching_straddle()

    assert straddle is not None
    put, _ = straddle
    assert put.instrument_name == better_put.instrument_name


def test_find_protective_wing(sample_options: list[OptionContract]) -> None:
    """Test finding OTM option for protection."""
    selector = OptionSelector(sample_options)

    # Find far OTM put (delta ~-0.10)
    wing = selector.find_by_delta(target_delta=-0.10, option_type="put")

    assert wing is not None
    assert wing.option_type == "put"
    # Should be the most OTM put


def test_filter_by_dte(sample_options: list[OptionContract]) -> None:
    """Test filtering options by days to expiry."""
    # Add some options with different expiries
    near_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    far_expiry = datetime.now(timezone.utc) + timedelta(days=60)

    mixed_options = sample_options + [
        OptionContract(
            instrument_name="BTC-7JAN26-95000-P",
            strike=95000.0,
            expiry=near_expiry,
            option_type="put",
            delta=-0.30,
            bid=0.0100,
            ask=0.0110,
        ),
        OptionContract(
            instrument_name="BTC-15MAR26-95000-P",
            strike=95000.0,
            expiry=far_expiry,
            option_type="put",
            delta=-0.35,
            bid=0.0400,
            ask=0.0420,
        ),
    ]

    selector = OptionSelector(mixed_options)

    # Filter for 20-40 DTE
    filtered = selector.filter_by_dte(min_dte=20, max_dte=40)

    assert len(filtered.options) == len(sample_options)  # Only the 30 DTE options


def test_find_returns_none_if_no_match(sample_options: list[OptionContract]) -> None:
    """Test returns None when no options match criteria."""
    selector = OptionSelector(sample_options)

    # Try to find a put with very low delta (doesn't exist)
    result = selector.find_by_delta(target_delta=-0.01, option_type="put")

    # Should return closest match or None depending on threshold
    # With our sample, should return the -0.15 delta put as closest
    assert result is None or (result.delta is not None and result.delta > -0.10)
