"""Unit tests for margin calculator."""

from datetime import datetime, timedelta

import pytest

from src.backtest.margin_calculator import (
    MarginCalculator,
    MarginConfig,
    MarginMetrics,
    MarginTracker,
    infer_margin_type,
)
from src.backtest.position_tracker import BacktestPosition
from src.brain.signal import OptionContract, StrategyType


@pytest.fixture
def sample_call_contract() -> OptionContract:
    """Create a sample call option contract."""
    return OptionContract(
        instrument_name="BTC-31JAN25-100000-C",
        strike=100000.0,
        expiry=datetime(2025, 1, 31),
        option_type="call",
        delta=0.30,
        iv=50.0,
        bid=0.025,
        ask=0.027,
        mark_price=0.026,
    )


@pytest.fixture
def sample_put_contract() -> OptionContract:
    """Create a sample put option contract."""
    return OptionContract(
        instrument_name="BTC-31JAN25-90000-P",
        strike=90000.0,
        expiry=datetime(2025, 1, 31),
        option_type="put",
        delta=-0.30,
        iv=50.0,
        bid=0.018,
        ask=0.020,
        mark_price=0.019,
    )


class TestInferMarginType:
    """Tests for infer_margin_type function."""

    def test_all_buys_returns_long_premium(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """All buy legs should return long_premium margin type."""
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.GAMMA_SCALP,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["buy", "buy"],
            entry_price=95000.0,
            entry_premium=-0.045,  # Debit
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = infer_margin_type(position)
        assert result == "long_premium"

    def test_all_sells_returns_naked_short(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """All sell legs should return naked_short margin type."""
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.VOL_ARB,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "sell"],
            entry_price=95000.0,
            entry_premium=0.045,  # Credit
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = infer_margin_type(position)
        assert result == "naked_short"

    def test_mixed_directions_returns_spread(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Mixed buy/sell legs should return spread margin type."""
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.IRON_CONDOR,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "buy"],
            entry_price=95000.0,
            entry_premium=0.010,  # Net credit
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = infer_margin_type(position)
        assert result == "spread"

    def test_empty_legs_returns_long_premium(
        self, sample_call_contract: OptionContract
    ) -> None:
        """Empty legs_direction should default to long_premium."""
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=[],
            entry_price=95000.0,
            entry_premium=0.0,
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = infer_margin_type(position)
        assert result == "long_premium"


class TestMarginCalculator:
    """Tests for MarginCalculator class."""

    def test_long_margin_is_premium_paid(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Long position margin should equal premium paid."""
        calculator = MarginCalculator()
        spot_price = 95000.0

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.GAMMA_SCALP,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["buy", "buy"],
            entry_price=spot_price,
            entry_premium=-0.045,
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = calculator.calculate(position, spot_price)

        # Premium paid = (0.026 + 0.019) * 95000 * 1.0 = 4275.0
        expected_premium = (0.026 + 0.019) * spot_price
        assert result.initial_margin == pytest.approx(expected_premium, rel=0.01)
        assert result.margin_type == "long_premium"
        assert result.maintenance_margin == result.initial_margin * 0.80

    def test_naked_short_margin_is_pct_of_notional(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Naked short margin should be percentage of notional."""
        config = MarginConfig(naked_short_pct=0.15)
        calculator = MarginCalculator(config)
        spot_price = 95000.0

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.VOL_ARB,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "sell"],
            entry_price=spot_price,
            entry_premium=0.045,
            entry_time=datetime.now(),
            quantity=1.0,
        )

        result = calculator.calculate(position, spot_price)

        # Margin = notional * 15% = 95000 * 1.0 * 0.15 = 14250
        expected_margin = spot_price * 1.0 * 0.15
        assert result.initial_margin == pytest.approx(expected_margin, rel=0.01)
        assert result.margin_type == "naked_short"

    def test_spread_margin_uses_max_loss(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Spread margin should use max_loss when available."""
        calculator = MarginCalculator()
        spot_price = 95000.0

        # Iron condor with known max loss
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.IRON_CONDOR,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "buy"],
            entry_price=spot_price,
            entry_premium=0.010,
            entry_time=datetime.now(),
            quantity=1.0,
            max_loss=0.05,  # 0.05 BTC max loss
        )

        result = calculator.calculate(position, spot_price)

        # Margin = max_loss * spot * quantity = 0.05 * 95000 * 1.0 = 4750
        expected_margin = 0.05 * spot_price * 1.0
        assert result.initial_margin == pytest.approx(expected_margin, rel=0.01)
        assert result.margin_type == "spread"

    def test_spread_without_max_loss_uses_fallback(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Spread without max_loss should use reduced notional fallback."""
        config = MarginConfig(naked_short_pct=0.15)
        calculator = MarginCalculator(config)
        spot_price = 95000.0

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.IRON_CONDOR,
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "buy"],
            entry_price=spot_price,
            entry_premium=0.010,
            entry_time=datetime.now(),
            quantity=1.0,
            max_loss=None,  # No max loss known
        )

        result = calculator.calculate(position, spot_price)

        # Fallback = notional * naked_short_pct * 0.5
        expected_margin = spot_price * 1.0 * 0.15 * 0.5
        assert result.initial_margin == pytest.approx(expected_margin, rel=0.01)
        assert result.margin_type == "spread"


class TestMarginTracker:
    """Tests for MarginTracker class."""

    def test_record_snapshot_captures_margin_state(
        self, sample_call_contract: OptionContract
    ) -> None:
        """record_snapshot should capture current margin state."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        timestamp = datetime.now()

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=timestamp,
            quantity=1.0,
        )

        snapshot = tracker.record_snapshot(
            positions={"pos_1": position},
            capital=100000.0,
            spot_price=spot_price,
            timestamp=timestamp,
        )

        assert snapshot.timestamp == timestamp
        assert snapshot.total_margin_required > 0
        assert snapshot.available_capital < 100000.0
        assert 0 <= snapshot.margin_utilization <= 1.0
        assert len(tracker.snapshots) == 1

    def test_tracks_peak_margin(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """Tracker should track peak margin usage."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        now = datetime.now()

        # First snapshot with one position
        pos1 = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=now,
            quantity=1.0,
        )
        tracker.record_snapshot(
            positions={"pos_1": pos1},
            capital=100000.0,
            spot_price=spot_price,
            timestamp=now,
        )
        first_peak = tracker._peak_margin

        # Second snapshot with two positions (higher margin)
        pos2 = BacktestPosition(
            position_id="pos_2",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_put_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.019,
            entry_time=now,
            quantity=2.0,
        )
        tracker.record_snapshot(
            positions={"pos_1": pos1, "pos_2": pos2},
            capital=100000.0,
            spot_price=spot_price,
            timestamp=now + timedelta(hours=1),
        )

        assert tracker._peak_margin > first_peak

    def test_counts_margin_breaches(
        self, sample_call_contract: OptionContract
    ) -> None:
        """Tracker should count when margin exceeds capital."""
        tracker = MarginTracker(initial_capital=10000.0)  # Low capital
        spot_price = 95000.0
        now = datetime.now()

        # Position that requires more margin than available capital
        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=now,
            quantity=1.0,
        )

        tracker.record_snapshot(
            positions={"pos_1": position},
            capital=10000.0,
            spot_price=spot_price,
            timestamp=now,
        )

        assert tracker._breach_count >= 1

    def test_calculate_metrics_returns_correct_values(
        self, sample_call_contract: OptionContract
    ) -> None:
        """calculate_metrics should return correct summary metrics."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        now = datetime.now()

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=now,
            quantity=1.0,
        )

        # Record multiple snapshots
        for i in range(5):
            tracker.record_snapshot(
                positions={"pos_1": position},
                capital=100000.0,
                spot_price=spot_price,
                timestamp=now + timedelta(hours=i),
            )

        metrics = tracker.calculate_metrics()

        assert isinstance(metrics, MarginMetrics)
        assert metrics.peak_margin_used > 0
        assert metrics.min_capital_required > metrics.peak_margin_used  # 5% buffer
        assert 0 <= metrics.avg_margin_utilization <= 1.0
        assert metrics.margin_breach_count >= 0

    def test_min_capital_required_includes_buffer(
        self, sample_call_contract: OptionContract
    ) -> None:
        """min_capital_required should include safety buffer."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        now = datetime.now()

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=now,
            quantity=1.0,
        )

        tracker.record_snapshot(
            positions={"pos_1": position},
            capital=100000.0,
            spot_price=spot_price,
            timestamp=now,
        )

        metrics = tracker.calculate_metrics()

        # min_capital should be peak * 1.05 (5% buffer)
        expected_min = tracker._peak_margin * 1.05
        assert metrics.min_capital_required == pytest.approx(expected_min, rel=0.01)

    def test_get_margin_for_signal_long(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """get_margin_for_signal should calculate long premium correctly."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0

        margin = tracker.get_margin_for_signal(
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["buy", "buy"],
            quantity=1.0,
            spot_price=spot_price,
        )

        # Long margin = premium * spot * quantity
        expected = (0.026 + 0.019) * spot_price * 1.0
        assert margin == pytest.approx(expected, rel=0.01)

    def test_get_margin_for_signal_naked_short(
        self, sample_call_contract: OptionContract
    ) -> None:
        """get_margin_for_signal should calculate naked short correctly."""
        config = MarginConfig(naked_short_pct=0.15)
        tracker = MarginTracker(initial_capital=100000.0, config=config)
        spot_price = 95000.0

        margin = tracker.get_margin_for_signal(
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            quantity=1.0,
            spot_price=spot_price,
        )

        # Naked short margin = notional * 15%
        expected = spot_price * 1.0 * 0.15
        assert margin == pytest.approx(expected, rel=0.01)

    def test_get_margin_for_signal_spread_with_max_loss(
        self, sample_call_contract: OptionContract, sample_put_contract: OptionContract
    ) -> None:
        """get_margin_for_signal should use max_loss for spreads."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        max_loss = 0.05  # BTC

        margin = tracker.get_margin_for_signal(
            contracts=[sample_call_contract, sample_put_contract],
            legs_direction=["sell", "buy"],
            quantity=1.0,
            spot_price=spot_price,
            max_loss=max_loss,
        )

        # Spread margin = max_loss * spot * quantity
        expected = max_loss * spot_price * 1.0
        assert margin == pytest.approx(expected, rel=0.01)

    def test_reset_clears_state(
        self, sample_call_contract: OptionContract
    ) -> None:
        """reset should clear all tracker state."""
        tracker = MarginTracker(initial_capital=100000.0)
        spot_price = 95000.0
        now = datetime.now()

        position = BacktestPosition(
            position_id="pos_1",
            strategy_type=StrategyType.WHEEL,
            contracts=[sample_call_contract],
            legs_direction=["sell"],
            entry_price=spot_price,
            entry_premium=0.026,
            entry_time=now,
            quantity=1.0,
        )

        tracker.record_snapshot(
            positions={"pos_1": position},
            capital=100000.0,
            spot_price=spot_price,
            timestamp=now,
        )

        assert len(tracker.snapshots) > 0
        assert tracker._peak_margin > 0

        tracker.reset()

        assert len(tracker.snapshots) == 0
        assert tracker._peak_margin == 0.0
        assert tracker._breach_count == 0


class TestMarginConfig:
    """Tests for MarginConfig dataclass."""

    def test_default_values(self) -> None:
        """Default config values should be set correctly.

        naked_short_pct calibrated 2026-01-30 via scripts/calibrate_margin_pct.py:
        OTM median 15.7%, ATM median 18.7%, overall median 17.9%
        Using 18% for conservative backtesting.
        """
        config = MarginConfig()

        assert config.naked_short_pct == 0.18
        assert config.spread_margin_type == "max_loss"
        assert config.maintenance_ratio == 0.80

    def test_custom_values(self) -> None:
        """Custom config values should override defaults."""
        config = MarginConfig(
            naked_short_pct=0.20,
            spread_margin_type="custom",
            maintenance_ratio=0.75,
        )

        assert config.naked_short_pct == 0.20
        assert config.spread_margin_type == "custom"
        assert config.maintenance_ratio == 0.75
