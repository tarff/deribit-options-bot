"""Shared strategy configuration and construction helpers."""

from typing import cast

from src.brain.signal import StrategyType
from src.strategies.base import BaseStrategy, StrategyConfig
from src.strategies.calendar_spread import CalendarSpreadConfig, CalendarSpreadStrategy
from src.strategies.gamma_scalp import GammaScalpConfig, GammaScalpStrategy
from src.strategies.iron_condor import IronCondorConfig, IronCondorStrategy
from src.strategies.vol_arb import VolArbConfig, VolArbStrategy
from src.strategies.wheel import WheelConfig, WheelStrategy


def build_strategy_configs(
    currency: str,
    is_linear: bool,
    include_vol_arb: bool = False,
) -> dict[StrategyType, StrategyConfig]:
    """Build calibrated strategy configs for live trading and backtests."""
    currency = currency.upper()
    neutral_iv_rank_threshold = {"BTC": 0.30, "ETH": 0.46}
    gamma_scalp_min_rv = {"BTC": 40.0, "ETH": 54.0}

    configs: dict[StrategyType, StrategyConfig] = {
        StrategyType.WHEEL: WheelConfig(
            name="wheel",
            enabled=False,
            target_dte_min=21,
            target_dte_max=35,
            target_delta=0.25,
            profit_target=0.50,
            loss_limit=3.0,
            min_iv_rank=neutral_iv_rank_threshold.get(currency, 0.30),
        ),
        StrategyType.IRON_CONDOR: IronCondorConfig(
            name="iron_condor",
            enabled=True,
            target_dte_min=23,
            target_dte_max=55,
            profit_target=0.25,
            loss_limit=2.0,
            short_delta=0.15,
            wing_delta=0.05,
            max_delta_diff=0.08,
            is_linear=is_linear,
        ),
        StrategyType.GAMMA_SCALP: GammaScalpConfig(
            name="gamma_scalp",
            enabled=True,
            target_dte_min=14,
            target_dte_max=30,
            min_rv=gamma_scalp_min_rv.get(currency, 40.0),
            scalp_threshold=0.10,
            # Calibrated via scripts/calibrate_gamma_scalp_stop.py on 1000
            # days of ETH+BTC daily data (2023-08 to 2026-05). Both
            # currencies' p90 max-intra-trade drawdown converged near 0.40
            # under a buy-and-hold proxy (no scalp PnL). A 0.40 stop catches
            # the worst ~10% of trades and lets the other 90% breathe.
            # The buy-and-hold proxy is conservative — production scalping
            # should reduce realized drawdowns vs this estimate.
            long_debit_stop_loss_pct=0.40,
        ),
        StrategyType.CALENDAR_SPREAD: CalendarSpreadConfig(
            name="calendar_spread",
            enabled=True,
            target_dte_min=14,
            target_dte_max=21,
            max_iv_rank=(
                0.20 if currency == "ETH" else neutral_iv_rank_threshold.get(currency, 0.30)
            ),
            profit_target=0.25,
            exit_price_move_pct=0.12,
            short_dte_min=14,
            short_dte_max=21,
            long_dte_min=45,
            long_dte_max=60,
            option_type="put",
        ),
    }

    if include_vol_arb:
        configs[StrategyType.VOL_ARB] = VolArbConfig(
            name="vol_arb",
            enabled=True,
            target_dte_min=30,
            target_dte_max=60,
            profit_target=0.50,
            loss_limit=2.0,
            target_delta=0.30,
            iv_rv_threshold_sell=15.0 if currency == "BTC" else -100.0,
            iv_rv_threshold_buy=-10.0 if currency == "BTC" else -19.0,
            delta_hedge_threshold=0.10,
        )

    return configs


def build_strategies(
    currency: str,
    is_linear: bool,
    include_vol_arb: bool = False,
) -> dict[StrategyType, BaseStrategy]:
    """Build strategy instances from shared calibrated configs."""
    configs = build_strategy_configs(currency, is_linear, include_vol_arb=include_vol_arb)
    strategies: dict[StrategyType, BaseStrategy] = {
        StrategyType.WHEEL: WheelStrategy(cast(WheelConfig, configs[StrategyType.WHEEL])),
        StrategyType.IRON_CONDOR: IronCondorStrategy(
            cast(IronCondorConfig, configs[StrategyType.IRON_CONDOR])
        ),
        StrategyType.GAMMA_SCALP: GammaScalpStrategy(
            cast(GammaScalpConfig, configs[StrategyType.GAMMA_SCALP])
        ),
        StrategyType.CALENDAR_SPREAD: CalendarSpreadStrategy(
            cast(CalendarSpreadConfig, configs[StrategyType.CALENDAR_SPREAD])
        ),
    }
    if include_vol_arb:
        strategies[StrategyType.VOL_ARB] = VolArbStrategy(
            cast(VolArbConfig, configs[StrategyType.VOL_ARB])
        )
    return strategies
