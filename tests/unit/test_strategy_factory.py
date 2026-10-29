"""Tests for shared strategy configuration factory."""

from src.brain.signal import StrategyType
from src.strategies.factory import build_strategy_configs
from src.strategies.calendar_spread import CalendarSpreadConfig
from src.strategies.iron_condor import IronCondorConfig
from src.strategies.wheel import WheelConfig


def test_eth_strategy_configs_use_live_calibrated_parameters() -> None:
    """ETH configs should centralize the calibrated live parameters."""
    configs = build_strategy_configs(currency="ETH", is_linear=True)

    wheel = configs[StrategyType.WHEEL]
    assert isinstance(wheel, WheelConfig)
    assert wheel.enabled is False
    assert wheel.target_dte_min == 21
    assert wheel.target_dte_max == 35
    assert wheel.target_delta == 0.25
    assert wheel.min_iv_rank == 0.46

    calendar = configs[StrategyType.CALENDAR_SPREAD]
    assert isinstance(calendar, CalendarSpreadConfig)
    assert calendar.max_iv_rank == 0.20
    assert calendar.profit_target == 0.25
    assert calendar.exit_price_move_pct == 0.12

    ic = configs[StrategyType.IRON_CONDOR]
    assert isinstance(ic, IronCondorConfig)
    assert ic.target_dte_min == 23
    assert ic.target_dte_max == 55
    assert ic.profit_target == 0.25
    assert ic.short_delta == 0.15
    assert ic.wing_delta == 0.05
    assert ic.max_delta_diff == 0.08
    assert ic.is_linear is True


def test_inverse_configs_disable_wheel_for_deribit_settlement() -> None:
    """Deribit options are cash-settled, so factory configs should not use Wheel."""
    configs = build_strategy_configs(currency="ETH", is_linear=False)

    wheel = configs[StrategyType.WHEEL]

    assert isinstance(wheel, WheelConfig)
    assert wheel.enabled is False
