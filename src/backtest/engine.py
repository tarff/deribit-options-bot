"""Backtest engine for strategy validation."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import numpy as np

from src.backtest.data_fetcher import HistoricalBar, HistoricalDataFetcher
from src.backtest.margin_calculator import MarginConfig, MarginMetrics, MarginTracker
from src.backtest.option_chain_generator import (
    SyntheticChainConfig,
    SyntheticOptionChainGenerator,
    _norm_cdf,
)
from src.backtest.position_tracker import PositionTracker
from src.brain.regime_detector import MarketRegime, RegimeDetector
from src.brain.signal import OptionContract, SignalAction, StrategyType, TradeSignal
from src.brain.strategy_selector import StrategySelector
from src.data.market_metrics import MarketMetrics
from src.persistence.models import Position
from src.risk.position_sizer import SizingConfig
from src.risk.risk_manager import RiskConfig, RiskManager
from src.strategies.base import BaseStrategy
from src.strategies.factory import build_strategies


@dataclass
class BacktestConfig:
    """Configuration for backtesting.

    Attributes:
        initial_capital: Starting capital in USD.
        start_date: Backtest start date.
        end_date: Backtest end date.
        commission_pct: Trading commission as percentage.
        strategy_type: Optional strategy to use (None = auto-select by regime).
        risk_config: Risk management configuration.
        sizing_config: Position sizing configuration.
        chain_config: Synthetic option chain configuration.
        margin_config: Margin calculation configuration.
        track_margin: Whether to track margin requirements.
        dvol_halt_threshold: DVOL level to trigger EXTREME_FEAR (default: 80).
        dvol_reduce_threshold: DVOL level to reduce position size to 50% (default: 60).
    """

    initial_capital: float = 100000.0
    start_date: datetime = field(default_factory=datetime.now)
    end_date: datetime = field(default_factory=datetime.now)
    commission_pct: float = 0.0005  # 0.05%
    strategy_type: Optional[StrategyType] = None
    risk_config: Optional[RiskConfig] = None
    sizing_config: Optional[SizingConfig] = None
    chain_config: Optional[SyntheticChainConfig] = None
    margin_config: Optional[MarginConfig] = None
    track_margin: bool = True
    dvol_halt_threshold: float = 80.0
    dvol_reduce_threshold: float = 60.0
    currency: str = "ETH"
    is_linear: bool = True


@dataclass
class BacktestResult:
    """Results from a backtest run.

    Attributes:
        total_return: Total return percentage.
        sharpe_ratio: Annualized Sharpe ratio.
        max_drawdown: Maximum drawdown percentage.
        win_rate: Percentage of winning trades.
        total_trades: Number of trades executed.
        final_capital: Ending capital.
        regime_distribution: Count of bars per regime.
        profit_factor: Gross profit / gross loss.
        avg_trade_pnl: Average P&L per trade.
        margin_metrics: Margin usage metrics (if tracking enabled).
    """

    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    final_capital: float = 0.0
    regime_distribution: dict[str, int] = field(default_factory=dict)
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    margin_metrics: Optional[MarginMetrics] = None


class BacktestEngine:
    """Engine for running strategy backtests.

    Simulates trading by replaying historical data through
    the regime detector and strategies.
    """

    def __init__(self, config: BacktestConfig) -> None:
        """Initialize backtest engine.

        Args:
            config: Backtest configuration.
        """
        if config.strategy_type == StrategyType.WHEEL:
            raise ValueError(
                "Wheel strategy is retired for Deribit cash-settled options; "
                "use calendar_spread or strategy_type=None for auto routing"
            )

        self.config = config
        self.capital = config.initial_capital
        self.peak_capital = config.initial_capital
        self.positions: list[Position] = []
        self.trades: list[dict[str, Any]] = []
        self.equity_curve: list[float] = []

        # Initialize components with configurable regime thresholds
        self.regime_detector = RegimeDetector(
            dvol_halt_threshold=config.dvol_halt_threshold,
        )
        self.strategy_selector = StrategySelector()
        self.position_tracker = PositionTracker(commission_pct=config.commission_pct)

        # Risk manager (with DVOL-based position sizing thresholds)
        risk_config = config.risk_config or RiskConfig()
        sizing_config = config.sizing_config or SizingConfig()
        self.risk_manager = RiskManager(
            risk_config,
            sizing_config,
            dvol_reduce_threshold=config.dvol_reduce_threshold,
            dvol_halt_threshold=config.dvol_halt_threshold,
        )

        # Option chain generator
        chain_config = config.chain_config or SyntheticChainConfig()
        self.chain_generator = SyntheticOptionChainGenerator(chain_config)

        # Margin tracker (for capital requirement analysis)
        self.margin_tracker: Optional[MarginTracker] = None
        if config.track_margin:
            margin_config = config.margin_config or MarginConfig()
            self.margin_tracker = MarginTracker(config.initial_capital, margin_config)

        # Strategy instances
        self._strategies: dict[StrategyType, BaseStrategy] = {}
        self._initialize_strategies()

        # Regime tracking
        self._regime_counts: dict[str, int] = {}
        self._daily_pnl: float = 0.0
        self._current_day: Optional[date] = None

    def _initialize_strategies(self) -> None:
        """Initialize strategy instances.

        Uses the same calibrated configs as live trading so research and
        runtime behavior do not drift.
        """
        fixed_type = self.config.strategy_type
        strategies = build_strategies(
            self.config.currency,
            self.config.is_linear,
            include_vol_arb=True,
        )
        if fixed_type is None:
            self._strategies = strategies
        else:
            self._strategies[fixed_type] = strategies[fixed_type]

    def build_metrics(
        self,
        price_bar: HistoricalBar,
        dvol_bar: Optional[HistoricalBar] = None,
        iv_rank: Optional[float] = None,
        rv_30d: Optional[float] = None,
        rv_7d: Optional[float] = None,
    ) -> MarketMetrics:
        """Build MarketMetrics from historical bars.

        Args:
            price_bar: Price OHLCV bar.
            dvol_bar: DVOL OHLCV bar (optional).
            iv_rank: IV rank if available.
            rv_30d: 30-day realized vol if available.
            rv_7d: 7-day realized vol if available.

        Returns:
            MarketMetrics for the bar timestamp.
        """
        dvol = dvol_bar.close if dvol_bar else None
        iv_rv_spread = None
        if dvol is not None and rv_30d is not None:
            iv_rv_spread = dvol - rv_30d

        return MarketMetrics(
            btc_price=price_bar.open,  # Use open price to avoid look-ahead bias
            dvol=dvol,
            iv_rank=iv_rank,
            rv_30d=rv_30d,
            rv_7d=rv_7d,
            iv_rv_spread=iv_rv_spread,
            timestamp=price_bar.timestamp,
        )

    async def run(
        self,
        price_bars: list[HistoricalBar],
        dvol_bars: list[HistoricalBar],
    ) -> BacktestResult:
        """Run backtest over historical data.

        Args:
            price_bars: Historical price bars.
            dvol_bars: Historical DVOL bars.

        Returns:
            BacktestResult with performance metrics.
        """
        # Align bars by timestamp
        dvol_by_ts = {bar.timestamp: bar for bar in dvol_bars}

        # Pre-compute proper IV rank, RV7d, RV30d from historical data
        # These use rolling lookback windows to avoid look-ahead bias
        self._iv_ranks = HistoricalDataFetcher.calculate_iv_rank(dvol_bars)
        self._rv_30d = HistoricalDataFetcher.calculate_realized_vol(price_bars, lookback=30)
        self._rv_7d = HistoricalDataFetcher.calculate_realized_vol(price_bars, lookback=7)

        self.equity_curve = [self.capital]
        self._regime_counts = {}

        for price_bar in price_bars:
            dvol_bar = dvol_by_ts.get(price_bar.timestamp)

            # Process the bar
            await self._process_bar(price_bar, dvol_bar)

            self.equity_curve.append(self.capital)
            self.peak_capital = max(self.peak_capital, self.capital)

        return self._calculate_results()

    async def _process_bar(
        self,
        price_bar: HistoricalBar,
        dvol_bar: Optional[HistoricalBar],
    ) -> None:
        """Process a single bar.

        Args:
            price_bar: Price bar.
            dvol_bar: DVOL bar (optional).
        """
        # Reset daily PnL on new day
        bar_day = price_bar.timestamp.date()
        if self._current_day is None or bar_day != self._current_day:
            self._daily_pnl = 0.0
            self._current_day = bar_day

        # Build metrics using pre-computed IV rank, RV from historical data
        ts = price_bar.timestamp
        iv_rank = self._iv_ranks.get(ts)
        rv_30d = self._rv_30d.get(ts)
        rv_7d = self._rv_7d.get(ts)
        metrics = self.build_metrics(
            price_bar, dvol_bar, iv_rank=iv_rank, rv_30d=rv_30d, rv_7d=rv_7d,
        )

        # Detect regime
        regime = self.regime_detector.detect(metrics)
        self._regime_counts[regime.value] = self._regime_counts.get(regime.value, 0) + 1

        # Generate synthetic option chain using open price (consistent with metrics)
        # Default DVOL of 50 is median of typical range (40-60) for neutral markets
        dvol_value = dvol_bar.close if dvol_bar else 50.0
        option_chain = self.chain_generator.generate(
            spot_price=price_bar.open,
            dvol=dvol_value,
            timestamp=price_bar.timestamp,
        )

        # Add contracts for open positions to ensure they can be marked to market
        # The synthetic chain may not include strikes from when positions were opened
        option_chain = self._add_position_strikes_to_chain(
            option_chain, price_bar.open, dvol_value, price_bar.timestamp
        )

        # Mark existing positions to market (used for tracking, not returned yet)
        _ = self.position_tracker.mark_to_market(option_chain, price_bar.open)

        # Record margin snapshot for capital requirement analysis
        if self.margin_tracker is not None:
            self.margin_tracker.record_snapshot(
                positions=self.position_tracker.positions,
                capital=self.capital,
                spot_price=price_bar.open,
                timestamp=price_bar.timestamp,
            )

        # First, let any strategy with an active position manage it
        # This ensures positions are managed even when regime changes
        for strat in self._strategies.values():
            if strat.state.is_active:
                signal = await strat.manage(metrics, option_chain)
                if signal:
                    await self._execute_signal(signal, option_chain, price_bar, metrics)

        # Then, evaluate for new entries with the regime-appropriate strategy
        strategy = self._get_strategy(regime)
        if strategy is None:
            return

        if not strategy.state.is_active:
            signal = await strategy.evaluate(metrics, option_chain)
            if signal:
                await self._execute_signal(signal, option_chain, price_bar, metrics)

    async def _execute_signal(
        self,
        signal: TradeSignal,
        option_chain: list[OptionContract],
        price_bar: HistoricalBar,
        metrics: MarketMetrics,
    ) -> None:
        """Execute a trade signal.

        Args:
            signal: Trade signal to execute.
            option_chain: Current option chain.
            price_bar: Current price bar.
            metrics: Current market metrics.
        """
        # Validate with risk manager (use open price for consistency)
        exposure = self.position_tracker.get_exposure(self.capital, price_bar.open)
        validation = self.risk_manager.validate_signal(
            signal=signal,
            metrics=metrics,
            capital=self.capital,
            current_exposure=exposure,
            open_positions=len(self.position_tracker.positions),
            daily_pnl=self._daily_pnl,
            peak_capital=self.peak_capital,
        )

        if not validation.approved:
            return

        # Get strategy
        strategy = self._strategies.get(signal.strategy_type)
        if strategy is None:
            return

        if signal.action == SignalAction.HEDGE:
            signed_delta = (
                validation.adjusted_quantity
                if signal.direction == "buy"
                else -validation.adjusted_quantity
            )
            strategy.state.hedge_delta += signed_delta
            if abs(strategy.state.hedge_delta) < 1e-9:
                strategy.state.hedge_delta = 0.0
            self.trades.append({
                "type": "hedge",
                "strategy": signal.strategy_type.value,
                "timestamp": price_bar.timestamp,
                "spot_price": price_bar.open,
                "quantity": validation.adjusted_quantity,
                "direction": signal.direction,
            })
            return

        if signal.action == SignalAction.OPEN:
            # Basic capital check - skip trades if capital depleted
            if self.capital <= 0:
                return

            # Check margin availability if tracking enabled
            if self.margin_tracker is not None:
                legs_dir = signal.legs_direction or [signal.direction] * len(
                    signal.contracts
                )
                required_margin = self.margin_tracker.get_margin_for_signal(
                    contracts=signal.contracts,
                    legs_direction=legs_dir,
                    quantity=validation.adjusted_quantity,
                    spot_price=price_bar.open,
                    max_loss=signal.max_loss,
                )
                current_margin = self.margin_tracker.get_current_margin_required(
                    self.position_tracker.positions, price_bar.open
                )
                available_margin = self.capital - current_margin
                if required_margin > available_margin:
                    # Not enough margin - skip this trade
                    return

            # Adjust quantity based on validation
            adjusted_signal = TradeSignal(
                strategy_type=signal.strategy_type,
                action=signal.action,
                contracts=signal.contracts,
                direction=signal.direction,
                quantity=validation.adjusted_quantity,
                legs_direction=signal.legs_direction,
                reason=signal.reason,
                max_profit=signal.max_profit,
                max_loss=signal.max_loss,
            )

            pos_id = self.position_tracker.open_position(
                adjusted_signal,
                spot_price=price_bar.open,
                timestamp=price_bar.timestamp,
            )
            strategy.activate(pos_id, price_bar.open, "open", entry_time=price_bar.timestamp)

            # Set contracts and premium_received on strategy state
            # These are required for manage() to calculate profit targets
            strategy.state.contracts = adjusted_signal.contracts
            premium = sum(c.mid_price or 0 for c in adjusted_signal.contracts)
            # For sold options, premium is received; for bought, it's paid
            if adjusted_signal.direction == "sell":
                strategy.state.premium_received = premium
            else:
                strategy.state.premium_received = -premium  # Cost, not credit

            # Record trade
            self.trades.append({
                "type": "open",
                "strategy": signal.strategy_type.value,
                "timestamp": price_bar.timestamp,
                "spot_price": price_bar.open,
                "quantity": validation.adjusted_quantity,
            })

        elif signal.action == SignalAction.CLOSE:
            # Find the position to close
            close_pos_id = strategy.state.position_id
            if close_pos_id is not None and close_pos_id in self.position_tracker.positions:
                pnl = self.position_tracker.close_position(
                    close_pos_id,
                    option_chain,
                    spot_price=price_bar.open,
                    timestamp=price_bar.timestamp,
                )

                # Update capital (clamp to 0 to prevent negative capital breaking risk checks)
                self.capital += pnl * price_bar.open  # Convert BTC P&L to USD
                self.capital = max(0.0, self.capital)
                self._daily_pnl += pnl * price_bar.open
                strategy.deactivate()

                # Record trade
                self.trades.append({
                    "type": "close",
                    "strategy": signal.strategy_type.value,
                    "timestamp": price_bar.timestamp,
                    "spot_price": price_bar.open,
                    "pnl": pnl,
                })

    def _add_position_strikes_to_chain(
        self,
        option_chain: list[OptionContract],
        spot_price: float,
        dvol: float,
        timestamp: datetime,
    ) -> list[OptionContract]:
        """Add contracts for open position strikes to the option chain.

        The synthetic chain generator creates strikes centered on current spot.
        When spot moves significantly, open positions' strikes may not exist
        in the chain. This method regenerates contracts at those strikes
        so positions can be marked to market.

        Args:
            option_chain: Generated option chain.
            spot_price: Current spot price.
            dvol: Current DVOL.
            timestamp: Current timestamp.

        Returns:
            Option chain with position strikes added.
        """
        # Collect all strikes/types we need for open positions
        needed: set[tuple[float, str, datetime]] = set()

        for strategy in self._strategies.values():
            if strategy.state.is_active and strategy.state.contracts:
                for contract in strategy.state.contracts:
                    needed.add((contract.strike, contract.option_type, contract.expiry))

        if not needed:
            return option_chain

        # Check which strikes are missing from the chain
        existing: set[tuple[float, str, datetime]] = {
            (c.strike, c.option_type, c.expiry) for c in option_chain
        }

        missing = needed - existing

        if not missing:
            return option_chain

        # Generate contracts for missing strikes
        chain_config = self.config.chain_config or SyntheticChainConfig()
        iv = dvol / 100.0

        for strike, option_type, expiry in missing:
            dte = (expiry - timestamp).days
            if dte <= 0:
                # Contract expired - don't regenerate
                continue
            contract = self._create_synthetic_contract(
                spot_price, strike, expiry, dte, iv, option_type, chain_config
            )
            option_chain.append(contract)

        return option_chain

    def _create_synthetic_contract(
        self,
        spot_price: float,
        strike: float,
        expiry: datetime,
        dte: int,
        iv: float,
        option_type: str,
        config: SyntheticChainConfig,
    ) -> OptionContract:
        """Create a synthetic option contract for backtesting.

        Uses same approximations as SyntheticOptionChainGenerator.

        Args:
            spot_price: Current spot price.
            strike: Strike price.
            expiry: Expiry datetime.
            dte: Days to expiry.
            iv: Implied volatility as decimal.
            option_type: 'call' or 'put'.
            config: Chain configuration for spread.

        Returns:
            OptionContract with approximate greeks and premium.
        """
        import math

        # Approximate delta using moneyness (same logic as chain generator)
        moneyness = spot_price / strike
        scale = 10.0 / max(1, math.sqrt(dte / 30)) if dte > 0 else 10.0

        if option_type == "call":
            raw = (moneyness - 1.0) * scale
            delta = 0.50 + 0.50 * (2 / math.pi) * math.atan(raw)
        else:
            raw = (1.0 - moneyness) * scale
            delta = -(0.50 + 0.50 * (2 / math.pi) * math.atan(raw))

        delta = round(delta, 4)

        # Black-Scholes pricing (r=0, consistent with option_chain_generator)
        t = dte / 365.0 if dte > 0 else 0.0

        if t <= 0 or iv <= 0:
            if option_type == "call":
                premium = max(0.0, (spot_price - strike) / spot_price)
            else:
                premium = max(0.0, (strike - spot_price) / spot_price)
        else:
            sqrt_t = math.sqrt(t)
            d1 = (math.log(spot_price / strike) + 0.5 * iv * iv * t) / (iv * sqrt_t)
            d2 = d1 - iv * sqrt_t
            if option_type == "call":
                price = spot_price * _norm_cdf(d1) - strike * _norm_cdf(d2)
            else:
                price = strike * _norm_cdf(-d2) - spot_price * _norm_cdf(-d1)
            premium = round(max(price / spot_price, 0.000001), 6)

        # Apply bid-ask spread
        half_spread = premium * config.spread_pct / 2
        bid = max(0.0001, premium - half_spread)
        ask = premium + half_spread

        # Generate instrument name
        expiry_str = expiry.strftime("%d%b%y").upper()
        opt_char = "C" if option_type == "call" else "P"
        instrument = f"BTC-{expiry_str}-{int(strike)}-{opt_char}"

        return OptionContract(
            instrument_name=instrument,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            delta=delta,
            iv=iv * 100,
            bid=bid,
            ask=ask,
            mark_price=premium,
        )

    def _get_strategy(self, regime: MarketRegime) -> Optional[BaseStrategy]:
        """Get strategy for current regime.

        Args:
            regime: Current market regime.

        Returns:
            Strategy instance or None.
        """
        if self.config.strategy_type:
            # Use fixed strategy if configured
            if not self.strategy_selector.is_allowed(self.config.strategy_type, regime):
                return None
            return self._strategies.get(self.config.strategy_type)
        else:
            # Auto-select based on regime
            strategy_type = self.strategy_selector.select(regime)
            if strategy_type is None:
                return None
            return self._strategies.get(strategy_type)

    def _estimate_iv_rank(self, dvol_bar: Optional[HistoricalBar]) -> Optional[float]:
        """Estimate IV rank from DVOL.

        Simple heuristic: normalize DVOL to 0-1 range.

        DVOL range based on historical BTC DVOL data (2021-2024):
        - Min observed: ~30 (calm markets, late 2023)
        - Max observed: ~150+ (March 2020 crash, FTX collapse)
        - Typical range: 40-80

        For backtesting IV rank estimation, we use 30-100 as the
        normalization range. This approximates the 1-year percentile
        ranking that true IV rank would provide.

        Note: For accurate IV rank, use HistoricalDataFetcher.calculate_iv_rank()
        with actual historical DVOL data over the lookback period.

        Args:
            dvol_bar: DVOL bar.

        Returns:
            Estimated IV rank (0.0 to 1.0).
        """
        if dvol_bar is None:
            return None

        dvol = dvol_bar.close
        # Historical DVOL range for normalization
        # 30 = historical calm (2023 lows), 150 = historical crisis (March 2020, FTX)
        min_dvol = 30.0
        max_dvol = 150.0
        normalized = (dvol - min_dvol) / (max_dvol - min_dvol)
        return max(0.0, min(1.0, normalized))

    def _calculate_results(self) -> BacktestResult:
        """Calculate backtest performance metrics.

        Returns:
            BacktestResult with calculated metrics.
        """
        if len(self.equity_curve) < 2:
            return BacktestResult(
                final_capital=self.capital,
                regime_distribution=self._regime_counts.copy(),
            )

        equity = np.array(self.equity_curve)
        returns = np.diff(equity) / equity[:-1]

        # Total return
        total_return = (self.capital - self.config.initial_capital) / self.config.initial_capital

        # Sharpe ratio (annualized, assuming daily bars)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd = float(np.max(drawdown))

        # Win rate and profit metrics
        closed_trades = self.position_tracker.closed_trades
        winning = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = winning / len(closed_trades) if closed_trades else 0.0

        # Profit factor
        gross_profit = sum(t.pnl for t in closed_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in closed_trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # Average trade P&L
        avg_trade_pnl = sum(t.pnl for t in closed_trades) / len(closed_trades) if closed_trades else 0.0

        # Calculate margin metrics if tracking enabled
        margin_metrics = None
        if self.margin_tracker is not None:
            margin_metrics = self.margin_tracker.calculate_metrics()

        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=float(sharpe),
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=len(closed_trades),
            final_capital=self.capital,
            regime_distribution=self._regime_counts.copy(),
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            margin_metrics=margin_metrics,
        )
