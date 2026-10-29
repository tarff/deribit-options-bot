"""Tests for PaperTradingLoop."""

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.brain.regime_detector import MarketRegime
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.config import Settings, PaperTradingConfig, TradingConfig, DeribitConfig, RiskConfig
from src.data.market_metrics import MarketMetrics
from src.execution.paper_trading import PaperTradingLoop
from src.persistence.database import Database


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        deribit=DeribitConfig(
            base_url="https://test.deribit.com",
            api_key="test_key",
            api_secret="test_secret",
        ),
        risk=RiskConfig(
            max_position_pct=10.0,
            max_exposure_pct=30.0,
            max_daily_loss_pct=5.0,
            max_drawdown_pct=15.0,
            dvol_reduce_threshold=60.0,
            dvol_halt_threshold=80.0,
        ),
    )


@pytest.fixture
def config() -> PaperTradingConfig:
    """Create test paper trading config."""
    return PaperTradingConfig(
        loop_interval_seconds=10,
        use_market_orders=True,
        initial_capital_usd=10000.0,
    )


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test database."""
    db_path = tmp_path / "test_paper_trading.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def sample_metrics() -> MarketMetrics:
    """Create sample market metrics."""
    return MarketMetrics(
        btc_price=100000.0,
        timestamp=datetime.now(timezone.utc),
        dvol=55.0,
        iv_rank=0.45,
        rv_7d=50.0,
        rv_30d=48.0,
        iv_rv_spread=7.0,
    )


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create sample option chain."""
    return [
        OptionContract(
            instrument_name="BTC-28MAR25-95000-P",
            strike=95000.0,
            expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
            option_type="put",
            delta=-0.25,
            bid=0.015,
            ask=0.017,
            mark_price=0.016,
        ),
        OptionContract(
            instrument_name="BTC-28MAR25-105000-C",
            strike=105000.0,
            expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
            option_type="call",
            delta=0.25,
            bid=0.014,
            ask=0.016,
            mark_price=0.015,
        ),
    ]


class TestPaperTradingLoopInitialization:
    """Tests for PaperTradingLoop initialization."""

    def test_initialization(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test that loop initializes correctly."""
        loop = PaperTradingLoop(config, settings, db)

        assert loop.config == config
        assert loop.settings == settings
        assert not loop.is_running
        assert loop.iteration_count == 0
        assert loop.capital == config.initial_capital_usd
        assert loop.daily_pnl == 0.0

    def test_strategies_initialized(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test that all strategies are initialized."""
        loop = PaperTradingLoop(config, settings, db)

        assert StrategyType.WHEEL in loop._strategies
        assert StrategyType.IRON_CONDOR in loop._strategies
        assert StrategyType.GAMMA_SCALP in loop._strategies
        assert StrategyType.CALENDAR_SPREAD in loop._strategies
        assert len(loop._strategies) == 4

    def test_uses_configured_database_when_not_injected(
        self,
        config: PaperTradingConfig,
        tmp_path: Path,
    ) -> None:
        """Loop should honor settings.database.path when no DB is injected."""
        db_path = tmp_path / "configured.db"
        settings = Settings(database={"path": str(db_path)})

        loop = PaperTradingLoop(config, settings)
        try:
            assert loop.db.db_path == str(db_path)
        finally:
            loop.db.close()


class TestPaperTradingLoopHelpers:
    """Tests for helper methods."""

    def test_count_open_positions(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test counting open positions."""
        loop = PaperTradingLoop(config, settings, db)

        # No positions initially
        assert loop._count_open_positions() == 0

        # Activate one strategy
        loop._strategies[StrategyType.WHEEL].state.is_active = True
        assert loop._count_open_positions() == 1

        # Activate another
        loop._strategies[StrategyType.IRON_CONDOR].state.is_active = True
        assert loop._count_open_positions() == 2

    def test_get_exposure(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test exposure calculation."""
        loop = PaperTradingLoop(config, settings, db)

        # No exposure initially
        assert loop._get_exposure(100000.0) == 0.0

        # Add some contracts to a strategy
        loop._strategies[StrategyType.WHEEL].state.is_active = True
        loop._strategies[StrategyType.WHEEL].state.contracts = [
            OptionContract(
                instrument_name="BTC-28MAR25-100000-P",
                strike=100000.0,
                expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
                option_type="put",
            )
        ]

        exposure = loop._get_exposure(100000.0)
        assert exposure > 0.0

    def test_get_exposure_uses_actual_position_size(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
    ) -> None:
        """Exposure should use filled size, not strategy default fraction."""
        loop = PaperTradingLoop(config, settings, db)
        strategy = loop._strategies[StrategyType.WHEEL]
        strategy.state.is_active = True
        strategy.state.position_size = 0.5
        strategy.state.contracts = [
            OptionContract(
                instrument_name="BTC-28MAR25-100000-P",
                strike=100000.0,
                expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
                option_type="put",
            )
        ]

        assert loop._get_exposure(100000.0) == 5.0

    @pytest.mark.asyncio
    async def test_check_daily_reset(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test daily PnL reset on new day."""
        loop = PaperTradingLoop(config, settings, db)

        # Set some PnL
        loop._daily_pnl = 500.0
        loop._current_day = datetime(2025, 1, 1).date()

        # Same day - no reset
        await loop._check_daily_reset(datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc))
        assert loop._daily_pnl == 500.0

        # Next day - should reset
        await loop._check_daily_reset(datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc))
        assert loop._daily_pnl == 0.0


class TestPaperTradingLoopPhases:
    """Tests for manage and entry phases."""

    @pytest.mark.asyncio
    async def test_manage_active_positions(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that manage phase calls manage on active strategies."""
        loop = PaperTradingLoop(config, settings, db)

        # Mock the strategy's manage method
        mock_manage = AsyncMock(return_value=None)
        loop._strategies[StrategyType.WHEEL].manage = mock_manage
        loop._strategies[StrategyType.WHEEL].state.is_active = True

        await loop._manage_active_positions(sample_metrics, sample_option_chain)

        mock_manage.assert_called_once_with(sample_metrics, sample_option_chain)

    @pytest.mark.asyncio
    async def test_manage_skips_inactive(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that manage phase skips inactive strategies."""
        loop = PaperTradingLoop(config, settings, db)

        # Mock the strategy's manage method
        mock_manage = AsyncMock(return_value=None)
        loop._strategies[StrategyType.WHEEL].manage = mock_manage
        loop._strategies[StrategyType.WHEEL].state.is_active = False

        await loop._manage_active_positions(sample_metrics, sample_option_chain)

        mock_manage.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_new_entries_neutral_regime(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test entry evaluation in NEUTRAL regime selects Calendar Spread."""
        loop = PaperTradingLoop(config, settings, db)

        wheel_evaluate = AsyncMock(return_value=None)
        calendar_evaluate = AsyncMock(return_value=None)
        loop._strategies[StrategyType.WHEEL].evaluate = wheel_evaluate
        loop._strategies[StrategyType.CALENDAR_SPREAD].evaluate = calendar_evaluate

        await loop._evaluate_new_entries(
            MarketRegime.NEUTRAL, sample_metrics, sample_option_chain
        )

        wheel_evaluate.assert_not_called()
        calendar_evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_skips_extreme_fear(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test no entries evaluated in EXTREME_FEAR regime."""
        loop = PaperTradingLoop(config, settings, db)

        # Mock all strategies
        for strategy in loop._strategies.values():
            strategy.evaluate = AsyncMock()

        await loop._evaluate_new_entries(
            MarketRegime.EXTREME_FEAR, sample_metrics, sample_option_chain
        )

        # None should be called
        for strategy in loop._strategies.values():
            strategy.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_skips_active_strategy(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test entry skips if strategy already has active position."""
        loop = PaperTradingLoop(config, settings, db)

        # Mark wheel as active
        loop._strategies[StrategyType.WHEEL].state.is_active = True
        mock_evaluate = AsyncMock()
        loop._strategies[StrategyType.CALENDAR_SPREAD].evaluate = mock_evaluate

        await loop._evaluate_new_entries(
            MarketRegime.NEUTRAL, sample_metrics, sample_option_chain
        )

        # Should not evaluate since already active
        mock_evaluate.assert_not_called()


class TestPaperTradingLoopExecution:
    """Tests for signal execution."""

    @pytest.mark.asyncio
    async def test_execute_signal_validates_with_risk_manager(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that signals are validated through risk manager."""
        loop = PaperTradingLoop(config, settings, db)

        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.OPEN,
            contracts=sample_option_chain[:1],
            direction="sell",
            quantity=0.1,
            reason="Test entry",
        )

        # Mock the order executor to track if called
        loop.order_executor.execute_signal = AsyncMock(return_value=[])

        # Mock validation to reject
        loop.risk_manager.validate_signal = MagicMock(return_value=MagicMock(
            approved=False,
            adjusted_quantity=0.0,
            reason="Test rejection",
        ))

        await loop._execute_signal(signal, sample_metrics)

        # Order executor should not be called since validation failed
        loop.order_executor.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_hedge_signal_calls_underlying_hedge_executor(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
    ) -> None:
        """HEDGE signals should execute an underlying perpetual hedge."""
        from src.execution.order_executor import OrderResult

        loop = PaperTradingLoop(config, settings, db)
        loop.order_executor.execute_hedge = AsyncMock(return_value=OrderResult(
            success=True,
            filled_amount=0.2,
            instrument_name="ETH_USDC-PERPETUAL",
        ))
        signal = TradeSignal(
            strategy_type=StrategyType.GAMMA_SCALP,
            action=SignalAction.HEDGE,
            contracts=[],
            direction="sell",
            quantity=0.2,
            target_delta=0.0,
            reason="delta hedge",
        )

        await loop._execute_signal(signal, sample_metrics)

        loop.order_executor.execute_hedge.assert_called_once_with(
            currency=loop.currency,
            is_linear=loop.is_linear,
            direction="sell",
            quantity=0.2,
        )

    @pytest.mark.asyncio
    async def test_execute_hedge_signal_records_hedge_delta(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
    ) -> None:
        """Successful hedges should update strategy hedge state."""
        from src.execution.order_executor import OrderResult

        loop = PaperTradingLoop(config, settings, db)
        strategy = loop._strategies[StrategyType.GAMMA_SCALP]
        strategy.state.is_active = True
        strategy.state.position_id = "gs-001"
        loop.order_executor.execute_hedge = AsyncMock(return_value=OrderResult(
            success=True,
            order_id="hedge1",
            filled_amount=0.2,
            average_price=2500.0,
            instrument_name="ETH_USDC-PERPETUAL",
        ))

        signal = TradeSignal(
            strategy_type=StrategyType.GAMMA_SCALP,
            action=SignalAction.HEDGE,
            contracts=[],
            direction="sell",
            quantity=0.2,
            target_delta=0.0,
            reason="delta hedge",
        )

        await loop._execute_signal(signal, sample_metrics)

        assert strategy.state.hedge_delta == pytest.approx(-0.2)
        hedge_trades = loop.trade_repo.get_by_strategy("gs-001")
        assert hedge_trades[0].instrument == "ETH_USDC-PERPETUAL"
        assert hedge_trades[0].side.value == "sell"

    def test_load_state_restores_hedge_delta_without_polluting_premium(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
    ) -> None:
        """Restart recovery should restore hedge delta from persisted hedge trades."""
        from src.persistence.models import Position, PositionStatus, Trade, TradeSide, TradeStatus
        from src.persistence.repositories import PositionRepository, TradeRepository

        now = datetime.now(timezone.utc)
        PositionRepository(db).save(Position(
            strategy_id="gs-001",
            strategy_type=StrategyType.GAMMA_SCALP.value,
            status=PositionStatus.OPEN,
            phase="open",
            entry_price=2500.0,
            opened_at=now,
        ))
        trade_repo = TradeRepository(db)
        trade_repo.save(Trade(
            strategy_id="gs-001",
            strategy_type=StrategyType.GAMMA_SCALP.value,
            order_id="opt1",
            instrument="ETH_USDC-27MAR26-2500-C",
            side=TradeSide.BUY,
            quantity=0.2,
            price=100.0,
            status=TradeStatus.FILLED,
            opened_at=now,
        ))
        trade_repo.save(Trade(
            strategy_id="gs-001",
            strategy_type=StrategyType.GAMMA_SCALP.value,
            order_id="hedge1",
            instrument="ETH_USDC-PERPETUAL",
            side=TradeSide.SELL,
            quantity=0.3,
            price=2500.0,
            status=TradeStatus.FILLED,
            opened_at=now,
        ))

        loop = PaperTradingLoop(config, settings, db)
        loop._load_state()
        strategy = loop._strategies[StrategyType.GAMMA_SCALP]

        assert strategy.state.hedge_delta == pytest.approx(-0.3)
        assert strategy.state.premium_received == pytest.approx(-20.0)

    @pytest.mark.asyncio
    async def test_close_signal_flattens_existing_hedge(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Closing options should also flatten any recorded hedge."""
        from src.execution.order_executor import OrderResult

        loop = PaperTradingLoop(config, settings, db)
        strategy = loop._strategies[StrategyType.GAMMA_SCALP]
        strategy.state.is_active = True
        strategy.state.position_id = "gs-001"
        strategy.state.premium_received = -0.02
        strategy.state.contracts = sample_option_chain[:1]
        strategy.state.hedge_delta = -0.3

        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(success=True, order_id="close1", filled_amount=0.1, average_price=0.015)
        ])
        loop.order_executor.execute_hedge = AsyncMock(return_value=OrderResult(
            success=True,
            filled_amount=0.3,
            instrument_name="ETH_USDC-PERPETUAL",
        ))

        signal = TradeSignal(
            strategy_type=StrategyType.GAMMA_SCALP,
            action=SignalAction.CLOSE,
            contracts=sample_option_chain[:1],
            direction="sell",
            quantity=0.1,
            reason="exit",
        )

        await loop._execute_signal(signal, sample_metrics)

        loop.order_executor.execute_hedge.assert_called_once_with(
            currency=loop.currency,
            is_linear=loop.is_linear,
            direction="buy",
            quantity=0.3,
        )

    @pytest.mark.asyncio
    async def test_calendar_expired_short_close_records_long_leg_trade(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
    ) -> None:
        """A one-leg calendar close should persist the executed long leg."""
        from src.execution.order_executor import OrderResult

        loop = PaperTradingLoop(config, settings, db)
        strategy = loop._strategies[StrategyType.CALENDAR_SPREAD]
        strategy.state.is_active = True
        strategy.state.position_id = "cal-001"
        strategy.state.premium_received = -0.02
        strategy.state.position_size = 0.1

        expired_short = OptionContract(
            instrument_name="BTC-26APR26-97000-P",
            strike=97000.0,
            expiry=datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc),
            option_type="put",
            bid=0.0,
            ask=0.0,
            mark_price=0.0,
        )
        active_long = OptionContract(
            instrument_name="BTC-29MAY26-97000-P",
            strike=97000.0,
            expiry=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
            option_type="put",
            bid=0.03,
            ask=0.032,
            mark_price=0.031,
        )
        strategy.state.contracts = [expired_short, active_long]

        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(
                success=True,
                order_id="close-long",
                filled_amount=0.1,
                average_price=0.03,
                instrument_name=active_long.instrument_name,
            )
        ])

        signal = TradeSignal(
            strategy_type=StrategyType.CALENDAR_SPREAD,
            action=SignalAction.CLOSE,
            contracts=[active_long],
            direction="sell",
            quantity=0.1,
            legs_direction=["sell"],
            reason="Short leg expired",
        )

        await loop._execute_signal(signal, sample_metrics)

        trades = loop.trade_repo.get_by_strategy("cal-001")
        assert len(trades) == 1
        assert trades[0].instrument == active_long.instrument_name

    @pytest.mark.asyncio
    async def test_emergency_check_executes_close_signal(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
    ) -> None:
        """Emergency DVOL should close active short-vol positions."""
        from src.persistence.models import Position, PositionStatus

        loop = PaperTradingLoop(config, settings, db)
        now = datetime.now(timezone.utc)
        position_id = "ic123"
        loop.position_repo.save(Position(
            strategy_id=position_id,
            strategy_type=StrategyType.IRON_CONDOR.value,
            status=PositionStatus.OPEN,
            phase="open",
            opened_at=now,
        ))
        strategy = loop._strategies[StrategyType.IRON_CONDOR]
        strategy.state.is_active = True
        strategy.state.position_id = position_id
        strategy.state.position_size = 0.2
        strategy.state.contracts = [
            OptionContract("ETH_USDC-27MAR26-1800-P", 1800, now, "put"),
            OptionContract("ETH_USDC-27MAR26-1500-P", 1500, now, "put"),
            OptionContract("ETH_USDC-27MAR26-2600-C", 2600, now, "call"),
            OptionContract("ETH_USDC-27MAR26-3000-C", 3000, now, "call"),
        ]
        metrics = MarketMetrics(
            btc_price=2000.0,
            dvol=101.0,
            timestamp=now,
        )
        loop._execute_signal = AsyncMock()

        handled = await loop._handle_emergency_positions(metrics)

        assert handled is True
        loop._execute_signal.assert_called_once()
        close_signal = loop._execute_signal.call_args.args[0]
        assert close_signal.action == SignalAction.CLOSE
        assert close_signal.legs_direction == ["buy", "sell", "buy", "sell"]

    @pytest.mark.asyncio
    async def test_execute_signal_close_always_approved(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that CLOSE signals are always approved."""
        loop = PaperTradingLoop(config, settings, db)

        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.CLOSE,
            contracts=sample_option_chain[:1],
            direction="buy",
            quantity=0.1,
            reason="Test close",
        )

        # Mock order executor
        from src.execution.order_executor import OrderResult
        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(success=True, order_id="123", filled_amount=0.1, average_price=0.015)
        ])

        # Set up strategy state
        loop._strategies[StrategyType.WHEEL].state.is_active = True
        loop._strategies[StrategyType.WHEEL].state.premium_received = 0.02
        loop._strategies[StrategyType.WHEEL].state.contracts = sample_option_chain[:1]

        await loop._execute_signal(signal, sample_metrics)

        # Order executor should be called
        loop.order_executor.execute_signal.assert_called_once()


class TestPaperTradingLoopRunning:
    """Tests for the main loop."""

    @pytest.mark.asyncio
    async def test_stop(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test that stop() sets running to False."""
        loop = PaperTradingLoop(config, settings, db)
        loop._running = True

        await loop.stop()

        assert not loop._running

    def test_is_running_property(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test is_running property."""
        loop = PaperTradingLoop(config, settings, db)

        assert not loop.is_running
        loop._running = True
        assert loop.is_running

    def test_iteration_count_property(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test iteration_count property."""
        loop = PaperTradingLoop(config, settings, db)

        assert loop.iteration_count == 0
        loop._iteration_count = 5
        assert loop.iteration_count == 5

    def test_capital_property(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test capital property."""
        loop = PaperTradingLoop(config, settings, db)

        assert loop.capital == config.initial_capital_usd
        loop._capital = 15000.0
        assert loop.capital == 15000.0

    def test_daily_pnl_property(self, config: PaperTradingConfig, settings: Settings, db: Database) -> None:
        """Test daily_pnl property."""
        loop = PaperTradingLoop(config, settings, db)

        assert loop.daily_pnl == 0.0
        loop._daily_pnl = 250.0
        assert loop.daily_pnl == 250.0


class TestPartialFillHandling:
    """Tests for partial fill detection and halting."""

    @pytest.mark.asyncio
    async def test_partial_fill_halts_strategy(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that partial fill halts the strategy."""
        loop = PaperTradingLoop(config, settings, db)

        # Create a multi-leg signal (calendar spread)
        signal = TradeSignal(
            strategy_type=StrategyType.CALENDAR_SPREAD,
            action=SignalAction.CLOSE,
            contracts=sample_option_chain[:2],  # Two legs
            direction="sell",
            quantity=1.0,
            legs_direction=["buy", "sell"],
            reason="Test close",
        )

        # Mock order executor to return partial fill (one success, one failure)
        from src.execution.order_executor import OrderResult
        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(success=True, order_id="123", filled_amount=1.0, average_price=0.15,
                       instrument_name="ETH-13FEB26-2800-P"),
            OrderResult(success=False, order_id=None, filled_amount=0.0, average_price=0.0,
                       error="Zero fill", instrument_name="ETH-27MAR26-2800-P"),
        ])

        # Set up strategy state
        loop._strategies[StrategyType.CALENDAR_SPREAD].state.is_active = True
        loop._strategies[StrategyType.CALENDAR_SPREAD].state.premium_received = 0.05

        # Execute signal - should detect partial fill
        await loop._execute_signal(signal, sample_metrics)

        # Strategy should be halted
        assert StrategyType.CALENDAR_SPREAD in loop.halted_strategies

        # Strategy should be deactivated
        assert not loop._strategies[StrategyType.CALENDAR_SPREAD].state.is_active

    @pytest.mark.asyncio
    async def test_halted_strategy_blocks_execution(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that halted strategies don't execute new signals."""
        loop = PaperTradingLoop(config, settings, db)

        # Manually halt the strategy
        loop._halted_strategies.add(StrategyType.WHEEL)

        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.CLOSE,
            contracts=sample_option_chain[:1],
            direction="buy",
            quantity=0.1,
            reason="Test close",
        )

        # Mock order executor
        from src.execution.order_executor import OrderResult
        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(success=True, order_id="123", filled_amount=0.1, average_price=0.015)
        ])

        await loop._execute_signal(signal, sample_metrics)

        # Order executor should NOT be called since strategy is halted
        loop.order_executor.execute_signal.assert_not_called()

    def test_clear_halted_strategy(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
    ) -> None:
        """Test clearing a halted strategy."""
        loop = PaperTradingLoop(config, settings, db)

        # Halt the strategy
        loop._halted_strategies.add(StrategyType.WHEEL)
        assert StrategyType.WHEEL in loop.halted_strategies

        # Clear it
        result = loop.clear_halted_strategy(StrategyType.WHEEL)
        assert result is True
        assert StrategyType.WHEEL not in loop.halted_strategies

        # Clearing again should return False
        result = loop.clear_halted_strategy(StrategyType.WHEEL)
        assert result is False

    def test_halted_strategies_property(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
    ) -> None:
        """Test halted_strategies property returns a copy."""
        loop = PaperTradingLoop(config, settings, db)

        loop._halted_strategies.add(StrategyType.WHEEL)

        # Property should return a copy
        halted = loop.halted_strategies
        halted.add(StrategyType.IRON_CONDOR)

        # Original should not be modified
        assert StrategyType.IRON_CONDOR not in loop._halted_strategies


class TestLinearSettlement:
    """Tests for USDC linear settlement support."""

    def test_is_linear_flag_set(self, config: PaperTradingConfig, db: Database) -> None:
        """Test that is_linear flag is set from settings."""
        linear_settings = Settings(
            deribit=DeribitConfig(
                base_url="https://test.deribit.com",
                api_key="test_key",
                api_secret="test_secret",
            ),
            trading=TradingConfig(currency="ETH", settlement="linear"),
            risk=RiskConfig(),
        )
        loop = PaperTradingLoop(config, linear_settings, db)
        assert loop.is_linear is True

    def test_is_linear_flag_inverse(self, config: PaperTradingConfig, db: Database) -> None:
        """Test that is_linear is False for inverse settlement."""
        inverse_settings = Settings(
            deribit=DeribitConfig(
                base_url="https://test.deribit.com",
                api_key="test_key",
                api_secret="test_secret",
            ),
            trading=TradingConfig(currency="ETH", settlement="inverse"),
            risk=RiskConfig(),
        )
        loop = PaperTradingLoop(config, inverse_settings, db)
        assert loop.is_linear is False

    def test_ic_config_inherits_is_linear(self, config: PaperTradingConfig, db: Database) -> None:
        """Test that IronCondorConfig gets is_linear from settings."""
        linear_settings = Settings(
            deribit=DeribitConfig(
                base_url="https://test.deribit.com",
                api_key="test_key",
                api_secret="test_secret",
            ),
            trading=TradingConfig(currency="ETH", settlement="linear"),
            risk=RiskConfig(),
        )
        loop = PaperTradingLoop(config, linear_settings, db)
        ic_strategy = loop._strategies[StrategyType.IRON_CONDOR]
        assert ic_strategy.ic_config.is_linear is True


class TestConcurrentEntryGuard:
    """Tests for single-position entry guard (Bug fix: Session 69)."""

    @pytest.mark.asyncio
    async def test_entry_blocked_when_another_strategy_active(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that no new entries are evaluated when any position is active."""
        loop = PaperTradingLoop(config, settings, db)

        # IC is active — Wheel should NOT be evaluated even in NEUTRAL regime
        loop._strategies[StrategyType.IRON_CONDOR].state.is_active = True

        mock_evaluate = AsyncMock()
        loop._strategies[StrategyType.CALENDAR_SPREAD].evaluate = mock_evaluate

        await loop._evaluate_new_entries(
            MarketRegime.NEUTRAL, sample_metrics, sample_option_chain
        )

        mock_evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_entry_allowed_when_no_positions_active(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that entries proceed when no positions are active."""
        loop = PaperTradingLoop(config, settings, db)

        # No active positions
        mock_evaluate = AsyncMock(return_value=None)
        loop._strategies[StrategyType.CALENDAR_SPREAD].evaluate = mock_evaluate

        await loop._evaluate_new_entries(
            MarketRegime.NEUTRAL, sample_metrics, sample_option_chain
        )

        mock_evaluate.assert_called_once()


class TestQuantityTracking:
    """Tests for position_contracts.quantity tracking (Bug fix: Session 69)."""

    @pytest.mark.asyncio
    async def test_contract_quantity_set_from_filled_amount(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Database,
        sample_metrics: MarketMetrics,
        sample_option_chain: list[OptionContract],
    ) -> None:
        """Test that position_contracts.quantity uses filled_amount, not default 1.0."""
        loop = PaperTradingLoop(config, settings, db)

        signal = TradeSignal(
            strategy_type=StrategyType.WHEEL,
            action=SignalAction.OPEN,
            contracts=sample_option_chain[:1],
            direction="sell",
            quantity=0.4,
            reason="Test entry",
        )

        # Mock risk manager to approve
        loop.risk_manager.validate_signal = MagicMock(return_value=MagicMock(
            approved=True,
            adjusted_quantity=0.4,
            reason="Approved",
        ))

        # Mock order executor to return 0.4 fill
        from src.execution.order_executor import OrderResult
        loop.order_executor.execute_signal = AsyncMock(return_value=[
            OrderResult(
                success=True, order_id="test_order", filled_amount=0.4,
                average_price=75.0, instrument_name=sample_option_chain[0].instrument_name,
            )
        ])

        await loop._execute_signal(signal, sample_metrics)

        # Check that the saved contract has correct quantity
        # Find the strategy_id that was generated
        strategy = loop._strategies[StrategyType.WHEEL]
        position_id = strategy.state.position_id

        contracts = loop.contract_repo.get_by_strategy_id(position_id)
        assert len(contracts) == 1
        assert contracts[0].quantity == 0.4
