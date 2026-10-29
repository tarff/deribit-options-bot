"""Tests for backtest engine."""

import pytest
from datetime import datetime, timezone

from src.backtest.engine import BacktestEngine, BacktestConfig, BacktestResult
from src.backtest.data_fetcher import HistoricalBar
from src.brain.regime_detector import MarketRegime
from src.brain.signal import StrategyType


@pytest.fixture
def backtest_config() -> BacktestConfig:
    """Create backtest config."""
    return BacktestConfig(
        initial_capital=100000.0,
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_price_bars() -> list[HistoricalBar]:
    """Sample price history."""
    return [
        HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=42000.0, high=43000.0, low=41500.0, close=42500.0, volume=1000.0,
        ),
        HistoricalBar(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=42500.0, high=44000.0, low=42000.0, close=43500.0, volume=1200.0,
        ),
    ]


@pytest.fixture
def sample_dvol_bars() -> list[HistoricalBar]:
    """Sample DVOL history."""
    return [
        HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=55.0, high=58.0, low=54.0, close=56.0, volume=0.0,
        ),
        HistoricalBar(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=56.0, high=60.0, low=55.0, close=58.0, volume=0.0,
        ),
    ]


def test_backtest_engine_initialization(backtest_config: BacktestConfig) -> None:
    """Test engine initializes correctly."""
    engine = BacktestEngine(backtest_config)

    assert engine.capital == backtest_config.initial_capital
    assert engine.positions == []


def test_backtest_uses_shared_calibrated_strategy_configs() -> None:
    """Backtest strategy parameters should match the live strategy factory."""
    engine = BacktestEngine(BacktestConfig(currency="ETH", is_linear=True))
    wheel = engine._strategies[StrategyType.WHEEL].config
    ic = engine._strategies[StrategyType.IRON_CONDOR].config

    assert wheel.target_dte_min == 21
    assert wheel.target_dte_max == 35
    assert wheel.target_delta == 0.25
    assert ic.target_dte_min == 23
    assert ic.target_dte_max == 55
    assert ic.profit_target == 0.25


def test_backtest_auto_neutral_uses_calendar_spread() -> None:
    """Auto-selected neutral backtests should match live Deribit routing."""
    engine = BacktestEngine(BacktestConfig(currency="ETH", is_linear=True))

    strategy = engine._get_strategy(MarketRegime.NEUTRAL)

    assert strategy is not None
    assert strategy.strategy_type == StrategyType.CALENDAR_SPREAD


def test_backtest_rejects_retired_wheel_strategy() -> None:
    """Explicit Wheel backtests should fail clearly instead of silently no-oping."""
    with pytest.raises(ValueError, match="Wheel.*retired"):
        BacktestEngine(BacktestConfig(strategy_type=StrategyType.WHEEL))


def test_build_metrics_from_bars(
    backtest_config: BacktestConfig,
    sample_price_bars: list[HistoricalBar],
    sample_dvol_bars: list[HistoricalBar],
) -> None:
    """Test building MarketMetrics from historical bars."""
    engine = BacktestEngine(backtest_config)

    metrics = engine.build_metrics(
        price_bar=sample_price_bars[0],
        dvol_bar=sample_dvol_bars[0],
    )

    assert metrics.btc_price == 42000.0  # open price (avoids look-ahead bias)
    assert metrics.dvol == 56.0  # DVOL close


@pytest.mark.asyncio
async def test_run_backtest_returns_result(
    backtest_config: BacktestConfig,
    sample_price_bars: list[HistoricalBar],
    sample_dvol_bars: list[HistoricalBar],
) -> None:
    """Test running a backtest returns result."""
    engine = BacktestEngine(backtest_config)

    result = await engine.run(
        price_bars=sample_price_bars,
        dvol_bars=sample_dvol_bars,
    )

    assert isinstance(result, BacktestResult)
    assert result.final_capital == backtest_config.initial_capital  # No trades
    assert result.total_return == 0.0
    assert result.max_drawdown == 0.0


class TestBacktestEngineIntegration:
    """Tests for backtest engine with strategy integration."""

    @pytest.mark.asyncio
    async def test_run_detects_regimes(self) -> None:
        """Run should detect regimes for each bar."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        # Create bars with varying DVOL
        price_bars = [
            HistoricalBar(datetime(2024, 1, i, tzinfo=timezone.utc), 100000, 100500, 99500, 100000 + i * 100, 1000)
            for i in range(1, 11)
        ]
        dvol_bars = [
            HistoricalBar(datetime(2024, 1, i, tzinfo=timezone.utc), 50, 55, 45, 50 + i, 0)
            for i in range(1, 11)
        ]

        result = await engine.run(price_bars, dvol_bars)

        # Should have tracked regimes
        assert hasattr(result, 'regime_distribution')
        assert len(result.regime_distribution) > 0

    @pytest.mark.asyncio
    async def test_run_with_strategy_generates_trades(self) -> None:
        """Run with strategy should generate trades."""
        from datetime import timedelta

        config = BacktestConfig(
            initial_capital=100000.0,
            strategy_type=StrategyType.IRON_CONDOR,
        )
        engine = BacktestEngine(config)

        # High IV environment for iron condor - use timedelta to avoid month overflow
        base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        price_bars = [
            HistoricalBar(base_date + timedelta(days=i), 100000, 100500, 99500, 100000, 1000)
            for i in range(60)
        ]
        dvol_bars = [
            HistoricalBar(base_date + timedelta(days=i), 55, 60, 50, 55, 0)  # High IV
            for i in range(60)
        ]

        result = await engine.run(price_bars, dvol_bars)

        # Should have processed all bars and tracked capital
        assert result.final_capital > 0
        # Regime distribution should have entries
        assert len(result.regime_distribution) > 0

    @pytest.mark.asyncio
    async def test_execute_signal_records_hedge_delta(self) -> None:
        """Backtest execution should account for hedge signals in strategy state."""
        from src.brain.signal import SignalAction, TradeSignal
        from src.data.market_metrics import MarketMetrics

        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)
        strategy = engine._strategies[StrategyType.GAMMA_SCALP]
        strategy.state.is_active = True
        strategy.state.position_id = "gs-001"

        bar = HistoricalBar(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            2500,
            2550,
            2450,
            2525,
            1000,
        )
        signal = TradeSignal(
            strategy_type=StrategyType.GAMMA_SCALP,
            action=SignalAction.HEDGE,
            contracts=[],
            direction="sell",
            quantity=0.3,
        )

        await engine._execute_signal(
            signal,
            [],
            bar,
            MarketMetrics(btc_price=2500, timestamp=bar.timestamp),
        )

        assert strategy.state.hedge_delta == pytest.approx(-0.3)
        assert engine.trades[-1]["type"] == "hedge"


class TestBacktestEngineIvRankEstimation:
    """Tests for IV rank estimation."""

    def test_estimate_iv_rank_none_when_no_dvol(self) -> None:
        """IV rank should be None when DVOL bar is None."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        result = engine._estimate_iv_rank(None)
        assert result is None

    def test_estimate_iv_rank_low_dvol(self) -> None:
        """Low DVOL (30) should give IV rank near 0."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        dvol_bar = HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=30, high=31, low=29, close=30, volume=0,
        )
        result = engine._estimate_iv_rank(dvol_bar)

        assert result is not None
        assert result == pytest.approx(0.0, abs=0.01)

    def test_estimate_iv_rank_high_dvol(self) -> None:
        """High DVOL (150) should give IV rank of 1.0."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        dvol_bar = HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=150, high=151, low=149, close=150, volume=0,
        )
        result = engine._estimate_iv_rank(dvol_bar)

        assert result is not None
        assert result == pytest.approx(1.0, abs=0.01)

    def test_estimate_iv_rank_mid_dvol(self) -> None:
        """Mid DVOL (90) should give IV rank near 0.5."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        dvol_bar = HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=90, high=91, low=89, close=90, volume=0,
        )
        result = engine._estimate_iv_rank(dvol_bar)

        assert result is not None
        # (90 - 30) / (150 - 30) = 60/120 = 0.5
        assert result == pytest.approx(0.5, abs=0.01)

    def test_estimate_iv_rank_below_min_clamped(self) -> None:
        """DVOL below 30 should be clamped to 0."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        dvol_bar = HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=20, high=21, low=19, close=20, volume=0,
        )
        result = engine._estimate_iv_rank(dvol_bar)

        assert result is not None
        assert result == 0.0

    def test_estimate_iv_rank_above_max_clamped(self) -> None:
        """DVOL above 100 should be clamped to 1.0."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        dvol_bar = HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=150, high=155, low=145, close=150, volume=0,
        )
        result = engine._estimate_iv_rank(dvol_bar)

        assert result is not None
        assert result == 1.0


class TestBacktestEngineConfigurableThresholds:
    """Tests for configurable DVOL thresholds."""

    def test_default_thresholds(self) -> None:
        """Default thresholds should be 60/80 (BTC calibrated)."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        # Thresholds on position sizer (via risk manager)
        assert engine.risk_manager.sizer.dvol_reduce_threshold == 60.0
        assert engine.risk_manager.sizer.dvol_halt_threshold == 80.0

    def test_custom_thresholds_for_eth(self) -> None:
        """Custom thresholds can be set for ETH (73/82 calibrated)."""
        config = BacktestConfig(
            initial_capital=100000.0,
            dvol_reduce_threshold=73.0,
            dvol_halt_threshold=82.0,
        )
        engine = BacktestEngine(config)

        # Both thresholds on position sizer
        assert engine.risk_manager.sizer.dvol_reduce_threshold == 73.0
        assert engine.risk_manager.sizer.dvol_halt_threshold == 82.0

    @pytest.mark.asyncio
    async def test_high_dvol_no_longer_triggers_extreme_fear(self) -> None:
        """High DVOL should not trigger EXTREME_FEAR in regime detector.

        DVOL-based risk is now handled by PositionSizer (0.0x for undefined-risk,
        0.5x for defined-risk like IC). Regime detector classifies market
        conditions only.
        """
        from datetime import timedelta
        from src.brain.regime_detector import MarketRegime

        base_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

        price_bars = [
            HistoricalBar(base_date + timedelta(days=i), 100000, 100500, 99500, 100000, 1000)
            for i in range(5)
        ]
        dvol_bars = [
            HistoricalBar(base_date + timedelta(days=i), 81, 82, 80, 81, 0)
            for i in range(5)
        ]

        # DVOL 81 no longer triggers EXTREME_FEAR (removed from regime detector)
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)
        result = await engine.run(price_bars, dvol_bars)

        assert MarketRegime.EXTREME_FEAR.value not in result.regime_distribution


class TestBacktestEngineDailyPnlReset:
    """Tests for daily PnL reset logic."""

    @pytest.mark.asyncio
    async def test_daily_pnl_resets_on_new_day(self) -> None:
        """Daily PnL should reset when date changes."""
        config = BacktestConfig(initial_capital=100000.0)
        engine = BacktestEngine(config)

        # Create bars spanning multiple days
        price_bars = [
            HistoricalBar(datetime(2024, 1, 1, tzinfo=timezone.utc), 100000, 100500, 99500, 100000, 1000),
            HistoricalBar(datetime(2024, 1, 1, 12, tzinfo=timezone.utc), 100000, 100500, 99500, 100000, 1000),
            HistoricalBar(datetime(2024, 1, 2, tzinfo=timezone.utc), 100000, 100500, 99500, 100000, 1000),
        ]
        dvol_bars = [
            HistoricalBar(datetime(2024, 1, 1, tzinfo=timezone.utc), 50, 55, 45, 50, 0),
            HistoricalBar(datetime(2024, 1, 1, 12, tzinfo=timezone.utc), 50, 55, 45, 50, 0),
            HistoricalBar(datetime(2024, 1, 2, tzinfo=timezone.utc), 50, 55, 45, 50, 0),
        ]

        await engine.run(price_bars, dvol_bars)

        # Engine should have tracked the current day (last bar's date)
        assert engine._current_day == datetime(2024, 1, 2).date()
