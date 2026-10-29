"""Integration tests for strategy execution flow."""

import pytest
from datetime import datetime, timezone, timedelta

from src.brain.regime_detector import MarketRegime
from src.brain.strategy_selector import StrategySelector
from src.brain.signal import StrategyType, OptionContract
from src.strategies.wheel import WheelStrategy, WheelConfig
from src.strategies.iron_condor import IronCondorStrategy, IronCondorConfig
from src.strategies.vol_arb import VolArbStrategy, VolArbConfig
from src.strategies.gamma_scalp import GammaScalpStrategy, GammaScalpConfig
from src.strategies.calendar_spread import CalendarSpreadStrategy, CalendarSpreadConfig
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create comprehensive option chain for testing.

    For BTC at $97,000, creates puts and calls with realistic deltas:
    - Puts from far OTM to ATM (-0.08 to -0.50)
    - Calls from ATM to far OTM (0.50 to 0.08)
    """
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    options = []

    # Put options with realistic deltas (sorted by strike, low to high)
    # Lower strikes = more OTM = smaller |delta|
    put_data = [
        (85000, -0.08),   # ~12% OTM
        (88000, -0.12),   # ~9% OTM
        (90000, -0.16),   # ~7% OTM - short put for IC
        (91000, -0.20),   # ~6% OTM
        (93000, -0.28),   # ~4% OTM - CSP target for Wheel
        (95000, -0.38),   # ~2% OTM
        (97000, -0.50),   # ATM - straddle put
    ]

    for strike, delta in put_data:
        premium = abs(delta) * 0.10  # Rough premium approximation
        options.append(OptionContract(
            instrument_name=f"BTC-31JAN26-{strike}-P",
            strike=float(strike),
            expiry=expiry,
            option_type="put",
            delta=delta,
            gamma=0.00012,
            theta=-50.0,
            vega=100.0,
            iv=52.0,
            bid=premium * 0.95,
            ask=premium * 1.05,
        ))

    # Call options with realistic deltas (sorted by strike, low to high)
    # Higher strikes = more OTM = smaller delta
    call_data = [
        (97000, 0.50),    # ATM - straddle call
        (99000, 0.38),    # ~2% OTM
        (101000, 0.28),   # ~4% OTM - CC target for Wheel
        (103000, 0.20),   # ~6% OTM
        (104000, 0.16),   # ~7% OTM - short call for IC
        (106000, 0.12),   # ~9% OTM
        (110000, 0.08),   # ~13% OTM
    ]

    for strike, delta in call_data:
        premium = delta * 0.10  # Rough premium approximation
        options.append(OptionContract(
            instrument_name=f"BTC-31JAN26-{strike}-C",
            strike=float(strike),
            expiry=expiry,
            option_type="call",
            delta=delta,
            gamma=0.00012,
            theta=-50.0,
            vega=100.0,
            iv=52.0,
            bid=premium * 0.95,
            ask=premium * 1.05,
        ))

    return options


@pytest.mark.asyncio
async def test_regime_to_strategy_flow(sample_option_chain: list[OptionContract]) -> None:
    """Test complete flow: regime detection -> strategy selection -> signal generation."""
    selector = StrategySelector()

    # Test NEUTRAL regime -> Calendar Spread strategy
    regime = MarketRegime.NEUTRAL
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.CALENDAR_SPREAD

    # Create and evaluate Calendar Spread strategy
    calendar = CalendarSpreadStrategy(CalendarSpreadConfig(name="calendar", enabled=True))
    now = datetime.now(timezone.utc)
    calendar_chain = [
        OptionContract(
            instrument_name="BTC-17JAN26-97000-P",
            strike=97000.0,
            expiry=now + timedelta(days=17),
            option_type="put",
            delta=-0.50,
            bid=0.020,
            ask=0.022,
            mark_price=0.021,
        ),
        OptionContract(
            instrument_name="BTC-20FEB26-97000-P",
            strike=97000.0,
            expiry=now + timedelta(days=50),
            option_type="put",
            delta=-0.50,
            bid=0.050,
            ask=0.055,
            mark_price=0.052,
        ),
    ]

    neutral_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.15,
        rv_30d=48.0,
        timestamp=now,
    )

    signal = await calendar.evaluate(neutral_metrics, calendar_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.CALENDAR_SPREAD


@pytest.mark.asyncio
async def test_high_iv_regime_iron_condor(sample_option_chain: list[OptionContract]) -> None:
    """Test HIGH_IV regime triggers Iron Condor."""
    selector = StrategySelector()

    regime = MarketRegime.HIGH_IV_OVERPRICED
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.IRON_CONDOR

    # Create and evaluate Iron Condor
    config = IronCondorConfig(name="ic", enabled=True)
    ic = IronCondorStrategy(config)

    high_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=62.0,
        iv_rank=0.72,
        iv_rv_spread=15.0,
        rv_30d=47.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await ic.evaluate(high_iv_metrics, sample_option_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.IRON_CONDOR
    assert len(signal.contracts) == 4


@pytest.mark.asyncio
async def test_low_iv_regime_gamma_scalp(sample_option_chain: list[OptionContract]) -> None:
    """Test LOW_IV regime triggers Gamma Scalp."""
    selector = StrategySelector()

    regime = MarketRegime.LOW_IV_UNDERPRICED
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.GAMMA_SCALP

    # Create and evaluate Gamma Scalp
    config = GammaScalpConfig(name="gs", enabled=True, target_dte_min=20, target_dte_max=40)
    gs = GammaScalpStrategy(config)

    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=38.0,
        iv_rank=0.18,
        iv_rv_spread=-12.0,
        rv_7d=52.0,
        rv_30d=50.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await gs.evaluate(low_iv_metrics, sample_option_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.GAMMA_SCALP
    assert signal.direction == "buy"


@pytest.mark.asyncio
async def test_extreme_fear_no_strategy() -> None:
    """Test EXTREME_FEAR regime returns no strategy."""
    selector = StrategySelector()

    regime = MarketRegime.EXTREME_FEAR
    strategy_type = selector.select(regime)

    assert strategy_type is None


@pytest.mark.asyncio
async def test_multiple_strategies_can_coexist(sample_option_chain: list[OptionContract]) -> None:
    """Test that multiple strategies can be instantiated and evaluated."""
    strategies = [
        WheelStrategy(WheelConfig(name="wheel", enabled=True, min_iv_rank=0.30)),
        IronCondorStrategy(IronCondorConfig(name="ic", enabled=True)),
        VolArbStrategy(VolArbConfig(name="va", enabled=True)),
        GammaScalpStrategy(GammaScalpConfig(name="gs", enabled=True, target_dte_min=20, target_dte_max=40)),
    ]

    # Metrics that could trigger multiple strategies
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=65.0,
        iv_rank=0.65,  # Above IC's 0.60 threshold
        iv_rv_spread=10.0,
        rv_7d=48.0,
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )

    signals = []
    for strategy in strategies:
        signal = await strategy.evaluate(metrics, sample_option_chain)
        if signal:
            signals.append(signal)

    # Wheel (iv_rank > 0.30), IC (iv_rank > 0.60), and Gamma Scalp (rv_7d > 40)
    # should all trigger. Vol Arb excluded (iv_rv_spread between thresholds).
    assert len(signals) >= 3
