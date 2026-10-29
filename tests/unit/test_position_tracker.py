"""Tests for backtest position tracker."""

import pytest
from datetime import datetime, timezone

from src.backtest.position_tracker import PositionTracker
from src.brain.signal import (
    OptionContract,
    TradeSignal,
    SignalAction,
    StrategyType,
)


from datetime import timedelta


def make_contract(
    strike: float,
    option_type: str,
    bid: float,
    ask: float,
    expiry: datetime | None = None,
) -> OptionContract:
    """Helper to create test contracts."""
    exp = expiry or datetime.now(timezone.utc)
    return OptionContract(
        instrument_name=f"BTC-TEST-{int(strike)}-{option_type[0].upper()}",
        strike=strike,
        expiry=exp,
        option_type=option_type,
        delta=-0.15 if option_type == "put" else 0.15,
        bid=bid,
        ask=ask,
        mark_price=(bid + ask) / 2,
    )


class TestPositionTracker:
    """Tests for PositionTracker."""

    def test_open_position_creates_position(self) -> None:
        """Opening a position should create a BacktestPosition."""
        tracker = PositionTracker(commission_pct=0.0005)

        signal = TradeSignal(
            strategy_type=StrategyType.IRON_CONDOR,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.010, 0.012)],
            direction="sell",
            quantity=0.1,
            legs_direction=["sell"],
        )

        pos_id = tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        assert pos_id in tracker.positions
        assert tracker.positions[pos_id].strategy_type == StrategyType.IRON_CONDOR
        assert tracker.positions[pos_id].quantity == 0.1

    def test_close_position_calculates_pnl(self) -> None:
        """Closing a position should calculate correct P&L."""
        tracker = PositionTracker(commission_pct=0.0)
        # Use consistent expiry for entry and close contracts
        expiry = datetime(2024, 2, 1, tzinfo=timezone.utc)

        # Open: sell option at 0.011 mid
        signal = TradeSignal(
            strategy_type=StrategyType.IRON_CONDOR,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.010, 0.012, expiry=expiry)],
            direction="sell",
            quantity=1.0,
            legs_direction=["sell"],
        )
        pos_id = tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        # Close: buy back at 0.005 mid (same expiry)
        close_chain = [make_contract(95000, "put", 0.004, 0.006, expiry=expiry)]
        pnl = tracker.close_position(pos_id, close_chain, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        # Sold at 0.011, bought back at 0.005 = profit of 0.006 per unit
        assert pnl == pytest.approx(0.006, rel=0.01)
        assert pos_id not in tracker.positions

    def test_commission_deducted_on_close(self) -> None:
        """Commission should be deducted from P&L."""
        tracker = PositionTracker(commission_pct=0.01)  # 1% for easy math
        expiry = datetime(2024, 2, 1, tzinfo=timezone.utc)

        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.010, 0.010, expiry=expiry)],
            direction="sell",
            quantity=1.0,
            legs_direction=["sell"],
        )
        pos_id = tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        close_chain = [make_contract(95000, "put", 0.005, 0.005, expiry=expiry)]
        pnl = tracker.close_position(pos_id, close_chain, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        # Gross P&L: 0.010 - 0.005 = 0.005
        # Commission: 1% of (0.010 + 0.005) = 0.00015
        assert pnl < 0.005  # Commission reduces profit

    def test_mark_to_market_unrealized_pnl(self) -> None:
        """Mark to market should return correct unrealized P&L."""
        tracker = PositionTracker(commission_pct=0.0)
        expiry = datetime(2024, 2, 1, tzinfo=timezone.utc)

        signal = TradeSignal(
            strategy_type=StrategyType.IRON_CONDOR,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.010, 0.010, expiry=expiry)],
            direction="sell",
            quantity=1.0,
            legs_direction=["sell"],
        )
        tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        # Current price dropped to 0.006 (same expiry)
        current_chain = [make_contract(95000, "put", 0.006, 0.006, expiry=expiry)]
        unrealized = tracker.mark_to_market(current_chain, spot_price=100000.0)

        # Sold at 0.010, current cost to close is 0.006, unrealized profit = 0.004
        assert unrealized == pytest.approx(0.004, rel=0.01)

    def test_get_open_positions_count(self) -> None:
        """Should return correct count of open positions."""
        tracker = PositionTracker(commission_pct=0.0)

        assert len(tracker.positions) == 0

        for i in range(3):
            signal = TradeSignal(
                strategy_type=StrategyType.WHEEL,
                action=SignalAction.OPEN,
                contracts=[make_contract(95000 + i * 1000, "put", 0.01, 0.01)],
                direction="sell",
                quantity=0.1,
                legs_direction=["sell"],
            )
            tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        assert len(tracker.positions) == 3

    def test_multi_leg_position_iron_condor(self) -> None:
        """Test handling of multi-leg iron condor position."""
        tracker = PositionTracker(commission_pct=0.0)
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=30)

        # Iron condor: sell put spread + sell call spread (4 legs)
        contracts = [
            make_contract(95000, "put", 0.010, 0.012, expiry),   # sell put
            make_contract(90000, "put", 0.005, 0.007, expiry),   # buy put
            make_contract(105000, "call", 0.010, 0.012, expiry), # sell call
            make_contract(110000, "call", 0.005, 0.007, expiry), # buy call
        ]

        signal = TradeSignal(
            strategy_type=StrategyType.IRON_CONDOR,
            action=SignalAction.OPEN,
            contracts=contracts,
            direction="sell",
            quantity=1.0,
            legs_direction=["sell", "buy", "sell", "buy"],
        )

        pos_id = tracker.open_position(signal, spot_price=100000.0, timestamp=now)

        assert pos_id in tracker.positions
        assert len(tracker.positions[pos_id].contracts) == 4
        # Net credit: sell 0.011 + 0.011 - buy 0.006 - 0.006 = 0.010
        assert tracker.positions[pos_id].entry_premium == pytest.approx(0.010, rel=0.01)

    def test_get_exposure_calculates_correctly(self) -> None:
        """Test exposure calculation as fraction of capital."""
        tracker = PositionTracker(commission_pct=0.0)

        # No positions = 0 exposure
        assert tracker.get_exposure(capital=100000.0, btc_price=100000.0) == 0.0

        # Open position with 1.0 BTC quantity
        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.01, 0.01)],
            direction="sell",
            quantity=1.0,
            legs_direction=["sell"],
        )
        tracker.open_position(signal, spot_price=100000.0, timestamp=datetime.now(timezone.utc))

        # 1.0 BTC * $100k = $100k notional / $100k capital = 1.0 exposure
        exposure = tracker.get_exposure(capital=100000.0, btc_price=100000.0)
        assert exposure == pytest.approx(1.0, rel=0.01)

    def test_get_exposure_zero_capital(self) -> None:
        """Test exposure returns 0 when capital is zero."""
        tracker = PositionTracker(commission_pct=0.0)
        assert tracker.get_exposure(capital=0.0, btc_price=100000.0) == 0.0

    def test_different_expiries_tracked_separately(self) -> None:
        """Test that same strike/type with different expiries are tracked separately."""
        tracker = PositionTracker(commission_pct=0.0)
        now = datetime.now(timezone.utc)
        expiry_30d = now + timedelta(days=30)
        expiry_60d = now + timedelta(days=60)

        # Position with 30-day expiry
        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.OPEN,
            contracts=[make_contract(95000, "put", 0.010, 0.010, expiry_30d)],
            direction="sell",
            quantity=1.0,
            legs_direction=["sell"],
        )
        _pos_id = tracker.open_position(signal, spot_price=100000.0, timestamp=now)

        # Close chain has same strike/type but DIFFERENT expiry (60d)
        # This should NOT match and should use fallback pricing
        close_chain_wrong_expiry = [make_contract(95000, "put", 0.001, 0.001, expiry_60d)]

        # Mark to market - should use original contract mark (0.010) not the wrong expiry one
        unrealized = tracker.mark_to_market(close_chain_wrong_expiry, spot_price=100000.0)

        # With fallback to original mark, unrealized should be ~0
        # (entry premium - exit premium where exit falls back to original)
        assert unrealized == pytest.approx(0.0, abs=0.001)

    def test_close_nonexistent_position_returns_zero(self) -> None:
        """Test closing a non-existent position returns 0."""
        tracker = PositionTracker(commission_pct=0.0)

        pnl = tracker.close_position(
            "nonexistent_pos",
            current_chain=[],
            spot_price=100000.0,
            timestamp=datetime.now(timezone.utc),
        )

        assert pnl == 0.0
