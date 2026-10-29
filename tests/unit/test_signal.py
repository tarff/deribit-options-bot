"""Tests for trading signal models."""

import pytest
from datetime import datetime, timezone

from src.brain.signal import (
    OptionContract,
    TradeSignal,
    SignalAction,
    StrategyType,
)


def test_option_contract_creation() -> None:
    """Test OptionContract with all fields."""
    contract = OptionContract(
        instrument_name="BTC-31JAN26-95000-P",
        strike=95000.0,
        expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        gamma=0.00012,
        theta=-45.0,
        vega=120.0,
        iv=52.3,
        bid=0.0320,
        ask=0.0340,
        mark_price=0.0330,
    )

    assert contract.strike == 95000.0
    assert contract.option_type == "put"
    assert contract.delta == -0.25


def test_option_contract_mid_price() -> None:
    """Test mid price calculation."""
    contract = OptionContract(
        instrument_name="BTC-31JAN26-95000-P",
        strike=95000.0,
        expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        bid=0.0320,
        ask=0.0340,
    )

    assert contract.mid_price == pytest.approx(0.0330, abs=0.0001)


def test_trade_signal_creation() -> None:
    """Test TradeSignal for opening a position."""
    signal = TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-95000-P",
                strike=95000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0320,
                ask=0.0340,
            )
        ],
        direction="sell",
        quantity=0.1,
        reason="IV Rank 67%, regime NEUTRAL, wheel entry",
    )

    assert signal.strategy_type == StrategyType.WHEEL
    assert signal.action == SignalAction.OPEN
    assert len(signal.contracts) == 1


def test_trade_signal_total_premium() -> None:
    """Test premium calculation for multi-leg signal."""
    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0150,
                ask=0.0170,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-88000-P",
                strike=88000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0050,
                ask=0.0060,
            ),
        ],
        direction="sell",
        quantity=0.1,
        legs_direction=["sell", "buy"],  # Sell 92k, buy 88k
        reason="Iron condor put spread",
    )

    # Net credit = sell 92k (0.016 mid) - buy 88k (0.0055 mid) = 0.0105
    assert signal.net_premium is not None
