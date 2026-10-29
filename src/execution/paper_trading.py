"""Paper trading loop for live trading against Deribit testnet."""

import asyncio
import logging
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from src.brain.regime_detector import RegimeDetector, MarketRegime
from src.data.volatility import calculate_iv_rank
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.brain.strategy_selector import StrategySelector
from src.config import Settings, PaperTradingConfig
from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer
from src.data.market_metrics import MarketMetrics
from src.execution.order_executor import OrderExecutor, OrderResult
from src.persistence.database import Database
from src.persistence.models import (
    Position, Trade, PositionStatus, TradeStatus, TradeSide,
    PositionContract as PositionContractModel, PaperTradingState,
    MarketSnapshot,
)
from src.persistence.repositories import (
    PositionRepository, TradeRepository, PositionContractRepository,
    PaperTradingStateRepository, SnapshotRepository,
)
from src.risk.circuit_breaker import CircuitBreaker, BreakerConfig
from src.risk.emergency_manager import EmergencyConfig as EmergencyManagerConfig
from src.risk.emergency_manager import EmergencyManager
from src.risk.position_sizer import SizingConfig
from src.risk.risk_manager import RiskManager, RiskConfig
from src.strategies.base import BaseStrategy
from src.strategies.factory import build_strategies
from src.monitoring.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class PaperTradingLoop:
    """Paper trading loop for executing strategies against Deribit testnet.

    Runs a continuous loop that:
    1. Fetches market data and detects regime
    2. Manages all active strategy positions (MANAGE phase)
    3. Evaluates new entries for regime-appropriate strategy (ENTRY phase)
    4. Validates and executes signals through the API
    """

    def __init__(
        self,
        config: PaperTradingConfig,
        settings: Settings,
        db: Optional[Database] = None,
    ) -> None:
        """Initialize paper trading loop.

        Args:
            config: Paper trading configuration.
            settings: Application settings.
            db: Database instance for persistence. If None, uses default path.
        """
        self.config = config
        self.settings = settings

        # Initialize database and repositories
        if db is None:
            db = Database(settings.database.path)
        self.db = db
        self.db.initialize()
        self.position_repo = PositionRepository(db)
        self.trade_repo = TradeRepository(db)
        self.contract_repo = PositionContractRepository(db)
        self.state_repo = PaperTradingStateRepository(db)
        self.snapshot_repo = SnapshotRepository(db)

        # Store trading currency and settlement type
        self.currency = settings.trading.currency.upper()
        self.is_linear = settings.trading.settlement == "linear"

        # Initialize Deribit client
        self.client = DeribitClient(
            base_url=settings.deribit.base_url,
            api_key=settings.deribit.api_key,
            api_secret=settings.deribit.api_secret,
        )

        # Initialize market analyzer with currency-specific thresholds
        # HIGH_IV_OVERPRICED spread threshold:
        #   ETH: Set to -100 (effectively disabled) based on
        #   scripts/analyze_spread_filter_impact.py (2026-02-10):
        #   - IC Sharpe monotonically decreases as min spread rises
        #   - Spread < 0: 95.5% win, PF 6.55 (BEST)
        #   - Spread >= 16: 57.1% win, PF 1.07 (WORST)
        #   - Correlation(spread, IC P&L) = -0.177
        #   - IV Rank alone is sufficient gating for IC entries
        #   BTC: Kept at 15.0 (not yet re-calibrated for IC)
        iv_rv_thresholds = {
            "BTC": {"high": 15.0, "low": -10.0},
            "ETH": {"high": -100.0, "low": -19.0},  # Recalibrated 2026-02-10
        }
        currency_thresholds = iv_rv_thresholds.get(self.currency, iv_rv_thresholds["BTC"])

        self.regime_detector = RegimeDetector(
            high_iv_spread_threshold=currency_thresholds["high"],
            low_iv_spread_threshold=currency_thresholds["low"],
        )
        self.analyzer = MarketAnalyzer(
            self.client, self.regime_detector, currency=self.currency
        )

        # Initialize strategy selector
        self.strategy_selector = StrategySelector()

        # Initialize risk management
        self.circuit_breaker = CircuitBreaker(
            BreakerConfig(
                daily_loss_limit_pct=settings.risk.max_daily_loss_pct / 100,
                dvol_halt_threshold=settings.risk.dvol_halt_threshold,
            )
        )

        risk_config = RiskConfig(
            max_positions=5,
            max_daily_loss_pct=settings.risk.max_daily_loss_pct / 100,
            max_drawdown_pct=settings.risk.max_drawdown_pct / 100,
        )
        sizing_config = SizingConfig(
            max_position_pct=settings.risk.max_position_pct / 100,
            max_total_exposure_pct=settings.risk.max_exposure_pct / 100,
        )
        non_ic_position_pct = min(settings.risk.max_position_pct / 100, 0.05)
        strategy_sizing_configs = {
            StrategyType.WHEEL: SizingConfig(
                max_position_pct=settings.risk.max_position_pct / 100,
                max_total_exposure_pct=settings.risk.max_exposure_pct / 100,
                base_win_rate=0.65,
                base_avg_win=0.02,
                base_avg_loss=0.01,
            ),
            StrategyType.CALENDAR_SPREAD: SizingConfig(
                max_position_pct=non_ic_position_pct,
                max_total_exposure_pct=settings.risk.max_exposure_pct / 100,
                base_win_rate=0.60,
                base_avg_win=0.01,
                base_avg_loss=0.01,
            ),
            StrategyType.GAMMA_SCALP: SizingConfig(
                max_position_pct=non_ic_position_pct,
                max_total_exposure_pct=settings.risk.max_exposure_pct / 100,
                base_win_rate=0.55,
                base_avg_win=0.03,
                base_avg_loss=0.02,
            ),
            StrategyType.VOL_ARB: SizingConfig(
                max_position_pct=non_ic_position_pct,
                max_total_exposure_pct=settings.risk.max_exposure_pct / 100,
                base_win_rate=0.55,
                base_avg_win=0.02,
                base_avg_loss=0.02,
            ),
        }
        self.risk_manager = RiskManager(
            risk_config,
            sizing_config,
            self.circuit_breaker,
            strategy_sizing_configs=strategy_sizing_configs,
            dvol_reduce_threshold=settings.risk.dvol_reduce_threshold,
            dvol_halt_threshold=settings.risk.dvol_halt_threshold,
        )

        # Initialize order executor
        self.order_executor = OrderExecutor(
            self.client,
            self.circuit_breaker,
            use_market_orders=config.use_market_orders,
        )

        # Initialize strategies
        self._strategies = self._initialize_strategies()

        self.emergency_manager = EmergencyManager(
            EmergencyManagerConfig(
                dvol_emergency_threshold=settings.emergency.dvol_emergency_threshold
            )
        )

        # Initialize Telegram notifier
        self.telegram = TelegramNotifier(settings.telegram)

        # State tracking (will be loaded from DB in start())
        self._running = False
        self._iteration_count = 0
        self._daily_pnl = 0.0
        self._current_day: Optional[date] = None
        self._capital = config.initial_capital_usd
        self._peak_capital = config.initial_capital_usd
        self._capital_lock = asyncio.Lock()

        # Track strategies halted due to partial fills or uncertain state
        # These require manual intervention before resuming
        self._halted_strategies: set[StrategyType] = set()

        # Cooldown: skip new entries for one cycle after closing a position.
        # Prevents entering on stale option chain data (fetched before the
        # close trades moved prices) and avoids overlapping strikes.
        self._closed_this_cycle = False

    def _initialize_strategies(self) -> dict[StrategyType, BaseStrategy]:
        """Initialize all strategy instances.

        Returns:
            Dict mapping strategy type to strategy instance.
        """
        return build_strategies(self.currency, self.is_linear, include_vol_arb=False)


    def _load_state(self) -> None:
        """Load persisted state from database.

        Restores:
        - Capital and daily PnL tracking
        - Open positions and their contracts
        - Strategy states for open positions
        """
        # Load paper trading state (capital, daily PnL)
        saved_state = self.state_repo.get()
        if saved_state:
            self._capital = saved_state.capital
            self._peak_capital = saved_state.peak_capital
            self._daily_pnl = saved_state.daily_pnl
            if saved_state.current_day:
                self._current_day = saved_state.current_day.date()
            logger.info(
                f"Loaded state: capital=${self._capital:,.2f}, "
                f"peak=${self._peak_capital:,.2f}, daily_pnl=${self._daily_pnl:,.2f}"
            )
        else:
            # Initialize with config defaults
            logger.info("No saved state found, starting fresh")
            self._save_state()

        # Load open positions and restore strategy states
        open_positions = self.position_repo.get_open()
        for position in open_positions:
            # Find the strategy type
            try:
                strategy_type = StrategyType(position.strategy_type)
            except ValueError:
                logger.warning(f"Unknown strategy type: {position.strategy_type}")
                continue

            strategy = self._strategies.get(strategy_type)
            if strategy is None:
                logger.warning(f"Strategy not found: {strategy_type}")
                continue

            # Load contracts for this position
            contracts = self.contract_repo.get_by_strategy_id(position.strategy_id)

            # Convert to OptionContract objects
            option_contracts = [
                OptionContract(
                    instrument_name=c.instrument_name,
                    strike=c.strike,
                    expiry=c.expiry,
                    option_type=c.option_type,
                    delta=c.delta,
                    gamma=c.gamma,
                    theta=c.theta,
                    vega=c.vega,
                    iv=c.iv,
                    bid=c.bid,
                    ask=c.ask,
                    mark_price=c.mark_price,
                )
                for c in contracts
            ]

            # Restore strategy state
            strategy.state.is_active = True
            strategy.state.position_id = position.strategy_id
            strategy.state.phase = position.phase
            strategy.state.entry_time = position.opened_at
            strategy.state.entry_price = position.entry_price
            strategy.state.current_pnl = position.current_pnl or 0.0
            strategy.state.contracts = option_contracts

            # Calculate premium_received from trades (accounting for direction)
            # SELL = credit received (positive), BUY = debit paid (negative)
            trades = self.trade_repo.get_by_strategy(position.strategy_id)
            total_premium = 0.0
            hedge_delta = 0.0
            option_trades: list[Trade] = []
            for t in trades:
                if self._is_hedge_instrument(t.instrument):
                    hedge_delta += self._signed_hedge_delta(
                        "buy" if t.side == TradeSide.BUY else "sell",
                        t.quantity,
                    )
                    continue
                option_trades.append(t)
                if t.side == TradeSide.SELL:
                    total_premium += t.price * t.quantity  # Credit
                else:
                    total_premium -= t.price * t.quantity  # Debit
            strategy.state.premium_received = total_premium
            strategy.state.hedge_delta = hedge_delta
            # Restore position_size and entry fees from trades
            if option_trades:
                strategy.state.position_size = option_trades[0].quantity
                strategy.state.entry_fees = sum(t.fees for t in option_trades)

            logger.info(
                f"Restored {strategy_type.value} position: {position.strategy_id} "
                f"({len(option_contracts)} contracts, premium={total_premium:.6f})"
            )

    def _save_state(self) -> None:
        """Save current state to database."""
        state = PaperTradingState(
            capital=self._capital,
            peak_capital=self._peak_capital,
            daily_pnl=self._daily_pnl,
            current_day=datetime.combine(
                self._current_day, datetime.min.time()
            ).replace(tzinfo=timezone.utc) if self._current_day else None,
        )
        self.state_repo.save(state)

    async def start(self) -> None:
        """Start the paper trading loop.

        Runs until stop() is called.
        """
        logger.info("Starting paper trading loop")

        # Load persisted state before starting
        self._load_state()

        self._running = True

        try:
            # Initial authentication
            await self.client.authenticate()
            logger.info("Authenticated with Deribit")

            while self._running:
                try:
                    await self._run_iteration()
                    # Save state after each successful iteration
                    self._save_state()
                except Exception as e:
                    logger.error(f"Iteration failed: {e}")
                    self.circuit_breaker.record_api_error()

                await asyncio.sleep(self.config.loop_interval_seconds)

        except Exception as e:
            logger.error(f"Paper trading loop failed: {e}")
            raise
        finally:
            # Save state before closing
            self._save_state()
            await self.telegram.close()
            await self.client.close()
            logger.info("Paper trading loop stopped")

    async def stop(self) -> None:
        """Stop the paper trading loop gracefully."""
        logger.info("Stopping paper trading loop...")
        self._running = False

    def _get_local_iv_rank(self, current_dvol: float) -> Optional[float]:
        """Calculate IV Rank using local historical database.

        Testnet has unrealistic DVOL history (max ~240 vs production ~83),
        so we use our local trading.db which has production DVOL data.

        Args:
            current_dvol: Current DVOL value.

        Returns:
            IV Rank from local data, or None if unavailable.
        """
        local_db_path = Path("data/trading.db")
        if not local_db_path.exists():
            return None

        try:
            with sqlite3.connect(str(local_db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT dvol FROM historical_data WHERE dvol IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 252"
                )
                historical_dvol = [r[0] for r in cursor.fetchall()]

            if len(historical_dvol) >= 10:
                return calculate_iv_rank(current_dvol, historical_dvol)
        except Exception as e:
            logger.debug(f"Could not load local IV Rank: {e}")

        return None

    async def _try_api_recovery(self) -> bool:
        """Attempt to recover from API error circuit breaker trip.

        Makes a simple health check API call. If successful, resets the
        circuit breaker. Uses exponential backoff between attempts.

        Returns:
            True if recovery successful, False otherwise.
        """
        if not self.circuit_breaker.can_attempt_api_recovery():
            return False

        logger.info("Attempting API recovery health check...")

        try:
            # Simple health check: get index price (lightweight call)
            await self.client.authenticate()
            index_price = await self.client.get_index_price(f"{self.currency.lower()}_usd")

            if index_price and index_price > 0:
                logger.info(f"API health check passed (index: ${index_price:,.0f})")
                self.circuit_breaker.record_recovery_attempt(success=True)
                return True
            else:
                logger.warning("API health check returned invalid data")
                self.circuit_breaker.record_recovery_attempt(success=False)
                return False

        except Exception as e:
            logger.warning(f"API health check failed: {e}")
            self.circuit_breaker.record_recovery_attempt(success=False)
            return False

    async def _run_iteration(self) -> None:
        """Run a single iteration of the trading loop.

        DVOL-based risk is handled by PositionSizer (0.5x at elevated, 0.0x at
        extreme for undefined-risk; 0.5x for defined-risk like IC). The circuit
        breaker handles API errors and daily loss only.
        """
        self._iteration_count += 1
        self._closed_this_cycle = False
        logger.debug(f"Starting iteration {self._iteration_count}")

        # 1. Re-authenticate (handle token expiration)
        await self.client.authenticate()

        # 2. Check circuit breaker (API errors, daily loss)
        if not self.circuit_breaker.can_trade():
            if await self._try_api_recovery():
                logger.info("API recovered, resuming trading")
            else:
                wait_seconds = self.circuit_breaker.get_next_recovery_wait()
                if wait_seconds > 0:
                    logger.warning(
                        f"Circuit breaker halted: {self.circuit_breaker.trip_reason} "
                        f"(next recovery attempt in {wait_seconds}s)"
                    )
                else:
                    logger.warning(
                        f"Circuit breaker halted: {self.circuit_breaker.trip_reason}"
                    )
                return

        # 3. Fetch market data
        metrics = await self.analyzer.get_current_metrics()

        # Override IV Rank with local calculation if available
        # (testnet DVOL history has unrealistic extremes)
        local_iv_rank = None
        if metrics.dvol is not None:
            local_iv_rank = self._get_local_iv_rank(metrics.dvol)
        if local_iv_rank is not None:
            api_iv_rank = metrics.iv_rank
            metrics = MarketMetrics(
                btc_price=metrics.btc_price,
                dvol=metrics.dvol,
                iv_rank=local_iv_rank,
                iv_percentile=metrics.iv_percentile,
                rv_7d=metrics.rv_7d,
                rv_30d=metrics.rv_30d,
                iv_rv_spread=metrics.iv_rv_spread,
                timestamp=metrics.timestamp,
            )
            logger.debug(f"IV Rank override: API={api_iv_rank:.1%} -> Local={local_iv_rank:.1%}")

        logger.info(
            f"Market: {self.currency}=${metrics.btc_price:,.0f} DVOL={metrics.dvol:.1f} "
            f"IV Rank={metrics.iv_rank:.1%}"
        )

        # 4. Reset daily PnL if new day
        await self._check_daily_reset(metrics.timestamp)

        # 5. Detect regime
        regime = self.regime_detector.detect(metrics)
        logger.info(f"Detected regime: {regime.value}")

        # 6. Save market snapshot
        active_strategy = None
        for s_type, strategy in self._strategies.items():
            if strategy.state.is_active:
                active_strategy = s_type.value
                break

        snapshot = MarketSnapshot(
            btc_price=metrics.btc_price,
            dvol=metrics.dvol,
            iv_rank=metrics.iv_rank,
            iv_percentile=metrics.iv_percentile,
            rv_7d=metrics.rv_7d,
            rv_30d=metrics.rv_30d,
            iv_rv_spread=metrics.iv_rv_spread,
            regime=regime.value,
            active_strategy=active_strategy,
            timestamp=metrics.timestamp,
        )
        self.snapshot_repo.save(snapshot)

        # 7. Fetch option chain (filtered by DTE and strike proximity)
        option_chain = await self._fetch_option_chain(metrics.btc_price)
        logger.debug(f"Fetched {len(option_chain)} options")

        # 8. MANAGE PHASE - all active strategies
        if await self._handle_emergency_positions(metrics):
            return

        await self._manage_active_positions(metrics, option_chain)

        # 9. ENTRY PHASE - PositionSizer handles DVOL-based size reduction
        await self._evaluate_new_entries(regime, metrics, option_chain)

    async def _check_daily_reset(self, timestamp: datetime) -> None:
        """Reset daily PnL if new day.

        Args:
            timestamp: Current timestamp.
        """
        current_day = timestamp.date()

        if self._current_day is None:
            self._current_day = current_day
        elif current_day > self._current_day:
            async with self._capital_lock:
                logger.info(f"New day detected, resetting daily PnL ({self._daily_pnl:+.2f})")
                self._daily_pnl = 0.0
                self._current_day = current_day

    # Option chain filter parameters
    # DTE range covers all strategies: Gamma Scalp (14-30), Wheel/IC (30-45) + buffer
    MIN_DTE_DAYS = 7
    MAX_DTE_DAYS = 60
    # Strike range as fraction of spot price (±65%)
    # Calibrated via scripts/analyze_strike_range_coverage.py (2026-02-02):
    # - 5-delta options can be 50-65% OTM during high DVOL periods
    # - 0.65 provides 99.1% capture rate across 999 days historical data
    # - Previous 0.35: only 17.9% capture rate (missed most high-IV days)
    STRIKE_RANGE_PCT = 0.65

    async def _fetch_option_chain(self, price: float) -> list[OptionContract]:
        """Fetch filtered option chain from Deribit.

        Filters options by DTE and strike proximity before fetching tickers
        to reduce API calls from ~1000 to ~50-100.

        Args:
            price: Current underlying price for strike filtering.

        Returns:
            List of OptionContract objects.
        """
        # Linear (USDC) options use currency="USDC" and have ETH_USDC- prefix
        # Inverse options use the underlying currency directly (e.g., "ETH")
        if self.is_linear:
            instruments = await self.client.get_instruments("USDC", "option")
            # Filter to only this currency's USDC options (e.g., ETH_USDC-)
            usdc_prefix = f"{self.currency}_USDC-"
            instruments = [i for i in instruments if i["instrument_name"].startswith(usdc_prefix)]
        else:
            instruments = await self.client.get_instruments(self.currency, "option")
        now = datetime.now(timezone.utc)

        # Calculate strike bounds
        min_strike = price * (1 - self.STRIKE_RANGE_PCT)
        max_strike = price * (1 + self.STRIKE_RANGE_PCT)

        # Filter instruments before fetching tickers
        filtered_instruments = []
        for inst in instruments:
            try:
                # Parse from instrument metadata (available without ticker call)
                parts = inst["instrument_name"].split("-")
                expiry_str = parts[1]
                strike = float(parts[2])

                # Parse expiry
                expiry = datetime.strptime(expiry_str, "%d%b%y")
                expiry = expiry.replace(hour=8, tzinfo=timezone.utc)

                # Filter by DTE
                dte = (expiry - now).days
                if dte < self.MIN_DTE_DAYS or dte > self.MAX_DTE_DAYS:
                    continue

                # Filter by strike proximity
                if strike < min_strike or strike > max_strike:
                    continue

                filtered_instruments.append((inst, expiry, strike))

            except Exception as e:
                logger.debug(f"Failed to parse instrument {inst.get('instrument_name')}: {e}")
                continue

        logger.info(
            f"Option chain filter: {len(instruments)} total → {len(filtered_instruments)} "
            f"(DTE {self.MIN_DTE_DAYS}-{self.MAX_DTE_DAYS}d, strike ${min_strike:,.0f}-${max_strike:,.0f})"
        )

        # Now fetch tickers only for filtered instruments
        option_chain: list[OptionContract] = []
        for inst, expiry, strike in filtered_instruments:
            try:
                ticker = await self.client.get_ticker(inst["instrument_name"])

                option_type = "put" if inst["instrument_name"].endswith("-P") else "call"
                greeks = ticker.get("greeks", {})

                bid = ticker.get("best_bid_price") or 0
                ask = ticker.get("best_ask_price") or 0

                # Skip options with no liquidity (both bid and ask are 0)
                # These cannot be traded - no counterparty available
                if bid == 0 and ask == 0:
                    logger.debug(
                        f"Skipping {inst['instrument_name']}: no liquidity (bid=0, ask=0)"
                    )
                    continue

                contract = OptionContract(
                    instrument_name=inst["instrument_name"],
                    strike=strike,
                    expiry=expiry,
                    option_type=option_type,
                    delta=greeks.get("delta"),
                    gamma=greeks.get("gamma"),
                    theta=greeks.get("theta"),
                    vega=greeks.get("vega"),
                    iv=ticker.get("mark_iv"),
                    bid=bid if bid > 0 else None,
                    ask=ask if ask > 0 else None,
                    mark_price=ticker.get("mark_price"),
                )
                option_chain.append(contract)

            except Exception as e:
                logger.debug(f"Failed to fetch ticker for {inst.get('instrument_name')}: {e}")
                continue

        return option_chain

    async def _manage_active_positions(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> None:
        """Manage all active strategy positions.

        Calls manage() on each active strategy.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.
        """
        for strategy_type, strategy in self._strategies.items():
            if not strategy.state.is_active:
                continue

            logger.debug(f"Managing active {strategy_type.value} position")

            try:
                signal = await strategy.manage(metrics, option_chain)

                if signal:
                    logger.info(f"Manage signal: {signal.action.value} {signal.reason}")
                    await self._execute_signal(signal, metrics)

            except Exception as e:
                logger.error(f"Failed to manage {strategy_type.value}: {e}")

    async def _evaluate_new_entries(
        self,
        regime: MarketRegime,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> None:
        """Evaluate new entries for regime-appropriate strategy.

        Tries primary strategy first, then fallback if primary declines.

        Args:
            regime: Current market regime.
            metrics: Current market metrics.
            option_chain: Available options.
        """
        # Skip entries for one cycle after closing a position.
        # The option chain was fetched before close trades executed, so
        # prices are stale and new entries could overlap closed strikes.
        if self._closed_this_cycle:
            logger.info("Skipping entry: position closed this cycle (cooldown)")
            return

        # Block all entries if any strategy already has an active position.
        # Without exchange state reconciliation, concurrent positions risk
        # untracked state drift (e.g., Session 69: IC + Wheel opened simultaneously).
        if self._count_open_positions() > 0:
            logger.debug("Skipping entry: active position exists (single-position mode)")
            return

        # Get primary strategy for current regime
        strategy_type = self.strategy_selector.select(regime)

        if strategy_type is None:
            logger.debug("No strategy for current regime (EXTREME_FEAR)")
            return

        # Try primary strategy
        signal = await self._try_strategy_entry(strategy_type, metrics, option_chain)

        # If primary declined, try fallback strategy
        if signal is None:
            fallback_type = self.strategy_selector.get_fallback(regime)
            if fallback_type and fallback_type != strategy_type:
                logger.debug(f"Primary {strategy_type.value} declined, trying fallback {fallback_type.value}")
                signal = await self._try_strategy_entry(fallback_type, metrics, option_chain)

        if signal:
            logger.info(f"Entry signal: {signal.strategy_type.value} - {signal.reason}")
            await self._execute_signal(signal, metrics)

    async def _try_strategy_entry(
        self,
        strategy_type: StrategyType,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Try to get entry signal from a strategy.

        Args:
            strategy_type: Strategy to evaluate.
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Trade signal if entry conditions met, None otherwise.
        """
        strategy = self._strategies.get(strategy_type)

        if strategy is None:
            logger.warning(f"Strategy {strategy_type.value} not initialized")
            return None

        if strategy.state.is_active:
            logger.debug(f"{strategy_type.value} already has active position")
            return None

        logger.debug(f"Evaluating entry for {strategy_type.value}")

        try:
            return await strategy.evaluate(metrics, option_chain)
        except Exception as e:
            logger.error(f"Failed to evaluate {strategy_type.value}: {e}")
            return None

    async def _execute_signal(
        self,
        signal: TradeSignal,
        metrics: MarketMetrics,
    ) -> None:
        """Validate and execute a trade signal.

        Args:
            signal: Trade signal to execute.
            metrics: Current market metrics.
        """
        # Check if strategy is halted due to partial fill or uncertain state
        if signal.strategy_type in self._halted_strategies:
            logger.warning(
                f"Strategy {signal.strategy_type.value} is HALTED - "
                f"requires manual intervention to clear position state"
            )
            return

        # Validate with RiskManager
        validation = self.risk_manager.validate_signal(
            signal=signal,
            metrics=metrics,
            capital=self._capital,
            current_exposure=self._get_exposure(metrics.btc_price),
            open_positions=self._count_open_positions(),
            daily_pnl=self._daily_pnl,
            peak_capital=self._peak_capital,
        )

        if not validation.approved:
            logger.info(f"Signal rejected: {validation.reason}")
            return

        if signal.action == SignalAction.HEDGE:
            result = await self.order_executor.execute_hedge(
                currency=self.currency,
                is_linear=self.is_linear,
                direction=signal.direction,
                quantity=validation.adjusted_quantity,
            )
            strategy = self._strategies.get(signal.strategy_type)
            if strategy and result.filled_amount > 0:
                self._record_hedge_fill(strategy, signal.direction, result.filled_amount)
                self._save_hedge_trade(signal.strategy_type, strategy, signal.direction, result)
            if result.success:
                logger.info(
                    f"Hedge executed: {signal.direction} {result.filled_amount} "
                    f"{result.instrument_name} @ {result.average_price}"
                )
            else:
                logger.error(f"Hedge execution failed: {result.error}")
                if strategy and result.filled_amount > 0:
                    logger.critical(
                        f"Partial hedge fill for {signal.strategy_type.value}: "
                        f"recorded {result.filled_amount}, manual review required"
                    )
            return

        # Update quantity to risk-adjusted size
        adjusted_signal = TradeSignal(
            strategy_type=signal.strategy_type,
            action=signal.action,
            contracts=signal.contracts,
            direction=signal.direction,
            quantity=validation.adjusted_quantity,
            legs_direction=signal.legs_direction,
            reason=signal.reason,
            target_delta=signal.target_delta,
            max_loss=signal.max_loss,
            max_profit=signal.max_profit,
        )

        # Execute via OrderExecutor
        results = await self.order_executor.execute_signal(
            adjusted_signal, metrics.btc_price
        )

        # Check if all legs succeeded
        all_success = all(r.success for r in results)
        any_success = any(r.success for r in results)

        if not all_success:
            failed = [r for r in results if not r.success]
            succeeded = [r for r in results if r.success]

            # CRITICAL: Detect partial fills - some legs executed, some didn't
            # This leaves position in uncertain state on exchange
            if any_success and len(results) > 1:
                logger.critical(
                    f"PARTIAL FILL DETECTED for {signal.strategy_type.value}! "
                    f"Succeeded: {[r.instrument_name for r in succeeded]}, "
                    f"Failed: {[r.instrument_name for r in failed]}. "
                    f"Strategy HALTED - manual intervention required to reconcile position."
                )
                # Halt the strategy to prevent retry loop that would worsen position
                self._halted_strategies.add(signal.strategy_type)

                # Deactivate strategy to stop manage() from generating more signals
                strategy = self._strategies.get(signal.strategy_type)
                if strategy:
                    strategy.deactivate()
            else:
                logger.error(f"Order execution failed: {[r.error for r in failed]}")

            return

        # Update strategy state based on action
        strategy = self._strategies.get(signal.strategy_type)
        if strategy is None:
            return

        if signal.action == SignalAction.OPEN:
            # Calculate net premium from fills (accounting for direction)
            # SELL legs = credit received (positive), BUY legs = debit paid (negative)
            total_premium = 0.0
            directions = signal.legs_direction or [signal.direction] * len(results)
            for r, direction in zip(results, directions):
                if direction == "sell":
                    total_premium += r.filled_amount * r.average_price  # Credit
                else:
                    total_premium -= r.filled_amount * r.average_price  # Debit

            # Generate position ID
            position_id = str(uuid.uuid4())[:8]
            now = datetime.now(timezone.utc)

            # Save position to database
            position = Position(
                strategy_id=position_id,
                strategy_type=signal.strategy_type.value,
                status=PositionStatus.OPEN,
                phase="open",
                entry_price=metrics.btc_price,
                max_profit=signal.max_profit,
                max_loss=signal.max_loss,
                current_pnl=0.0,
                opened_at=now,
            )
            self.position_repo.save(position)

            # Save trades to database
            for i, (r, contract) in enumerate(zip(results, signal.contracts)):
                direction = signal.legs_direction[i] if signal.legs_direction else signal.direction
                trade = Trade(
                    strategy_id=position_id,
                    strategy_type=signal.strategy_type.value,
                    order_id=r.order_id,
                    instrument=contract.instrument_name,
                    side=TradeSide.SELL if direction == "sell" else TradeSide.BUY,
                    quantity=r.filled_amount,
                    price=r.average_price,
                    fees=r.fee,
                    status=TradeStatus.FILLED,
                    opened_at=now,
                )
                self.trade_repo.save(trade)

            # Save contracts to database with correct direction and quantity from signal
            directions = signal.legs_direction or [signal.direction] * len(signal.contracts)
            for i, contract in enumerate(signal.contracts):
                direction = directions[i] if i < len(directions) else "long"
                contract_model = PositionContractModel(
                    strategy_id=position_id,
                    instrument_name=contract.instrument_name,
                    strike=contract.strike,
                    expiry=contract.expiry,
                    option_type=contract.option_type,
                    delta=contract.delta,
                    gamma=contract.gamma,
                    theta=contract.theta,
                    vega=contract.vega,
                    iv=contract.iv,
                    bid=contract.bid,
                    ask=contract.ask,
                    mark_price=contract.mark_price,
                    direction=direction,
                    quantity=results[i].filled_amount,
                )
                self.contract_repo.save(contract_model)

            # Activate strategy with appropriate phase
            # Vol arb needs sell_vol/buy_vol phase for exit logic and delta calc
            if signal.strategy_type == StrategyType.VOL_ARB:
                phase = f"{signal.direction}_vol"
            else:
                phase = "open"
            strategy.activate(
                position_id=position_id,
                entry_price=metrics.btc_price,
                phase=phase,
            )
            strategy.state.contracts = signal.contracts
            strategy.state.premium_received = total_premium
            strategy.state.position_size = results[0].filled_amount
            strategy.state.entry_fees = sum(r.fee for r in results)

            if self.is_linear:
                logger.info(
                    f"Opened {signal.strategy_type.value} position "
                    f"(id={position_id}, premium=${total_premium:,.2f} USDC)"
                )
            else:
                logger.info(
                    f"Opened {signal.strategy_type.value} position "
                    f"(id={position_id}, premium={total_premium:.6f} {self.currency})"
                )

            # Send Telegram notification
            await self.telegram.notify_trade_entry(
                strategy=signal.strategy_type.value,
                contracts=[c.instrument_name for c in signal.contracts],
                premium=total_premium,
                btc_price=metrics.btc_price,
                currency=self.currency,
                is_linear=self.is_linear,
            )

        elif signal.action == SignalAction.CLOSE:
            # Calculate realized PnL (accounting for direction)
            # CLOSE directions are opposite of OPEN:
            # - Closing SHORT position = BUY to close = pay (negative)
            # - Closing LONG position = SELL to close = receive (positive)
            close_directions = signal.legs_direction or [signal.direction] * len(results)
            close_value = 0.0
            for r, direction in zip(results, close_directions):
                if direction == "sell":
                    close_value += r.filled_amount * r.average_price  # Receive when selling
                else:
                    close_value -= r.filled_amount * r.average_price  # Pay when buying

            # PnL = open_premium + close_value
            # Short position: +credit (open) + (-cost to close) = credit - cost
            # Long position: -debit (open) + (+receive on close) = receive - debit
            close_fees = sum(r.fee for r in results)
            total_fees = strategy.state.entry_fees + close_fees
            realized_pnl = strategy.state.premium_received + close_value - total_fees
            # Linear (USDC) premiums are already in USD; inverse premiums need conversion
            if self.is_linear:
                realized_pnl_usd = realized_pnl
            else:
                realized_pnl_usd = realized_pnl * metrics.btc_price

            # Update tracking (atomic to prevent race conditions on concurrent closes)
            async with self._capital_lock:
                self._daily_pnl += realized_pnl_usd
                self._capital += realized_pnl_usd
                self._peak_capital = max(self._peak_capital, self._capital)

            # Persist capital immediately to survive crashes
            self._save_state()

            close_position_id = strategy.state.position_id
            now = datetime.now(timezone.utc)

            # Save exit trades to database
            for i, r in enumerate(results):
                contract_opt = signal.contracts[i] if i < len(signal.contracts) else None
                instrument = (
                    r.instrument_name
                    or (contract_opt.instrument_name if contract_opt else None)
                    or f"unknown_{i}"
                )
                # Use actual close direction from signal
                close_dir = close_directions[i] if i < len(close_directions) else signal.direction
                trade = Trade(
                    strategy_id=close_position_id or "unknown",
                    strategy_type=signal.strategy_type.value,
                    order_id=r.order_id,
                    instrument=instrument,
                    side=TradeSide.SELL if close_dir == "sell" else TradeSide.BUY,
                    quantity=r.filled_amount,
                    price=r.average_price,
                    fees=r.fee,
                    status=TradeStatus.FILLED,
                    opened_at=now,
                    closed_at=now,
                    pnl=realized_pnl / len(results),  # Distribute PnL across legs
                )
                self.trade_repo.save(trade)

            # Close position in database
            if close_position_id:
                db_position = self.position_repo.get_by_strategy_id(close_position_id)
                if db_position and db_position.id:
                    self.position_repo.close(
                        position_id=db_position.id,
                        close_reason=signal.reason,
                        final_pnl=realized_pnl,
                    )
                # Clean up contracts (keep for historical reference by not deleting)
                # self.contract_repo.delete_by_strategy_id(close_position_id)

            if self.is_linear:
                logger.info(
                    f"Closed {signal.strategy_type.value} position "
                    f"(PnL=${realized_pnl_usd:,.2f} USDC)"
                )
            else:
                logger.info(
                    f"Closed {signal.strategy_type.value} position "
                    f"(PnL={realized_pnl:.6f} {self.currency} / ${realized_pnl_usd:,.2f})"
                )

            # Send Telegram notification
            await self.telegram.notify_trade_exit(
                strategy=signal.strategy_type.value,
                pnl=realized_pnl,
                pnl_usd=realized_pnl_usd,
                reason=signal.reason,
                currency=self.currency,
                is_linear=self.is_linear,
            )

            hedge_flattened = await self._flatten_strategy_hedge(signal.strategy_type, strategy)
            if not hedge_flattened:
                self._halted_strategies.add(signal.strategy_type)
                strategy.state.contracts = []
                logger.critical(
                    f"{signal.strategy_type.value} options closed but hedge remains open. "
                    "Strategy halted for manual reconciliation."
                )
                return

            # Deactivate strategy
            strategy.deactivate()

            # Set cooldown to skip new entries this cycle — option chain
            # is stale (fetched before close trades moved prices)
            self._closed_this_cycle = True

            # Check daily loss circuit breaker
            self.circuit_breaker.check_daily_loss(self._daily_pnl, self._capital)
            if not self.circuit_breaker.can_trade():
                await self.telegram.notify_circuit_breaker(
                    reason=self.circuit_breaker.trip_reason or "Daily loss limit exceeded",
                    daily_pnl=self._daily_pnl,
                )

    def _get_exposure(self, btc_price: float) -> float:
        """Calculate current exposure as fraction of capital.

        Args:
            btc_price: Current BTC price.

        Returns:
            Exposure fraction (0.0 to 1.0).
        """
        total_exposure_usd = 0.0

        for strategy in self._strategies.values():
            if strategy.state.is_active:
                qty = strategy.state.position_size or strategy.config.max_position_size
                for contract in strategy.state.contracts:
                    total_exposure_usd += contract.strike * qty

        if self._capital <= 0:
            return 0.0

        return total_exposure_usd / self._capital

    def _count_open_positions(self) -> int:
        """Count number of open positions.

        Returns:
            Number of active strategies.
        """
        return sum(1 for s in self._strategies.values() if s.state.is_active)

    @staticmethod
    def _signed_hedge_delta(direction: str, filled_amount: float) -> float:
        """Return signed underlying delta for a hedge fill."""
        return filled_amount if direction == "buy" else -filled_amount

    @staticmethod
    def _is_hedge_instrument(instrument: str) -> bool:
        """Return True for underlying perpetual hedge instruments."""
        return instrument.endswith("PERPETUAL")

    def _record_hedge_fill(
        self,
        strategy: BaseStrategy,
        direction: str,
        filled_amount: float,
    ) -> None:
        """Record an underlying hedge fill on strategy state."""
        strategy.state.hedge_delta += self._signed_hedge_delta(direction, filled_amount)
        if abs(strategy.state.hedge_delta) < 1e-9:
            strategy.state.hedge_delta = 0.0

    def _save_hedge_trade(
        self,
        strategy_type: StrategyType,
        strategy: BaseStrategy,
        direction: str,
        result: OrderResult,
    ) -> None:
        """Persist a filled hedge trade so hedge state survives restarts."""
        if not strategy.state.position_id or result.filled_amount <= 0:
            return

        trade = Trade(
            strategy_id=strategy.state.position_id,
            strategy_type=strategy_type.value,
            order_id=result.order_id,
            instrument=result.instrument_name or f"{self.currency}-PERPETUAL",
            side=TradeSide.BUY if direction == "buy" else TradeSide.SELL,
            quantity=result.filled_amount,
            price=result.average_price,
            fees=result.fee,
            status=TradeStatus.FILLED if result.success else TradeStatus.PARTIALLY_FILLED,
            opened_at=datetime.now(timezone.utc),
        )
        self.trade_repo.save(trade)

    async def _flatten_strategy_hedge(
        self,
        strategy_type: StrategyType,
        strategy: BaseStrategy,
    ) -> bool:
        """Flatten any underlying hedge before clearing strategy state."""
        hedge_delta = strategy.state.hedge_delta
        if abs(hedge_delta) < 1e-9:
            return True

        direction = "sell" if hedge_delta > 0 else "buy"
        result = await self.order_executor.execute_hedge(
            currency=self.currency,
            is_linear=self.is_linear,
            direction=direction,
            quantity=abs(hedge_delta),
        )
        if result.filled_amount > 0:
            self._record_hedge_fill(strategy, direction, result.filled_amount)
            self._save_hedge_trade(strategy_type, strategy, direction, result)

        if abs(strategy.state.hedge_delta) < 1e-9:
            logger.info(f"Flattened {strategy_type.value} hedge via {direction} {result.filled_amount}")
            return True

        logger.critical(
            f"Failed to fully flatten {strategy_type.value} hedge: {result.error}; "
            f"remaining hedge delta {strategy.state.hedge_delta:.6f}"
        )
        return False

    async def _handle_emergency_positions(self, metrics: MarketMetrics) -> bool:
        """Close emergency short-vol positions before normal management."""
        open_positions = self.position_repo.get_open()
        strategy_contracts: dict[str, tuple[list[OptionContract], list[str], float]] = {}

        for strategy_type, strategy in self._strategies.items():
            if not strategy.state.is_active or not strategy.state.position_id:
                continue
            if strategy_type == StrategyType.IRON_CONDOR:
                legs_direction = ["sell", "buy", "sell", "buy"]
            elif strategy_type == StrategyType.VOL_ARB and strategy.state.phase == "sell_vol":
                legs_direction = ["sell"] * len(strategy.state.contracts)
            else:
                continue

            strategy_contracts[strategy.state.position_id] = (
                strategy.state.contracts,
                legs_direction,
                strategy.state.position_size,
            )

        signals = self.emergency_manager.check_emergency(
            metrics,
            open_positions,
            strategy_contracts=strategy_contracts,
        )
        for signal in signals:
            logger.critical(signal.reason)
            await self._execute_signal(signal, metrics)
        return bool(signals)

    def clear_halted_strategy(self, strategy_type: StrategyType) -> bool:
        """Clear a halted strategy after manual intervention.

        Call this after manually closing positions on the exchange to allow
        the strategy to resume normal operation.

        Args:
            strategy_type: Strategy type to clear.

        Returns:
            True if strategy was halted and is now cleared, False otherwise.
        """
        if strategy_type in self._halted_strategies:
            self._halted_strategies.remove(strategy_type)
            logger.info(f"Cleared halted state for {strategy_type.value}")
            return True
        return False

    @property
    def halted_strategies(self) -> set[StrategyType]:
        """Get set of halted strategy types."""
        return self._halted_strategies.copy()

    @property
    def is_running(self) -> bool:
        """Check if loop is running."""
        return self._running

    @property
    def iteration_count(self) -> int:
        """Get number of iterations completed."""
        return self._iteration_count

    @property
    def capital(self) -> float:
        """Get current capital."""
        return self._capital

    @property
    def daily_pnl(self) -> float:
        """Get current daily PnL."""
        return self._daily_pnl
