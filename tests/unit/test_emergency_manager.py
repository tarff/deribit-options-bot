"""Tests for emergency manager."""

import pytest
from datetime import datetime, timedelta, timezone

from src.risk.emergency_manager import EmergencyManager, EmergencyConfig
from src.data.market_metrics import MarketMetrics
from src.brain.signal import SignalAction, OptionContract
from src.persistence.models import Position, PositionStatus


@pytest.fixture
def emergency_config() -> EmergencyConfig:
    """Create emergency config."""
    return EmergencyConfig(
        dvol_emergency_threshold=100.0,
    )


@pytest.fixture
def extreme_metrics() -> MarketMetrics:
    """DVOL > 100 crisis metrics."""
    return MarketMetrics(
        btc_price=85000.0,
        dvol=105.0,
        iv_rank=0.99,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def normal_metrics() -> MarketMetrics:
    """Normal market conditions."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )


def test_is_emergency_true_when_dvol_extreme(
    emergency_config: EmergencyConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test emergency detected when DVOL > 100."""
    manager = EmergencyManager(emergency_config)

    assert manager.is_emergency(extreme_metrics) is True


def test_is_emergency_false_when_dvol_normal(
    emergency_config: EmergencyConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test no emergency in normal conditions."""
    manager = EmergencyManager(emergency_config)

    assert manager.is_emergency(normal_metrics) is False


def test_is_emergency_false_at_boundary(
    emergency_config: EmergencyConfig,
) -> None:
    """Test DVOL exactly at threshold does NOT trigger emergency (strict >)."""
    manager = EmergencyManager(emergency_config)
    boundary_metrics = MarketMetrics(
        btc_price=90000.0,
        dvol=100.0,  # Exactly at threshold
        iv_rank=0.80,
        timestamp=datetime.now(timezone.utc),
    )

    # DVOL == 100 should NOT be emergency (we use > not >=)
    assert manager.is_emergency(boundary_metrics) is False


def test_is_emergency_false_when_dvol_none(
    emergency_config: EmergencyConfig,
) -> None:
    """Test no emergency when DVOL is None."""
    manager = EmergencyManager(emergency_config)
    metrics_no_dvol = MarketMetrics(
        btc_price=90000.0,
        dvol=None,
        iv_rank=0.50,
        timestamp=datetime.now(timezone.utc),
    )

    assert manager.is_emergency(metrics_no_dvol) is False


@pytest.fixture
def short_vol_positions() -> list[Position]:
    """Mix of short vol and other positions."""
    now = datetime.now(timezone.utc)
    return [
        Position(
            strategy_id="vol-001",
            strategy_type="vol_arb",
            status=PositionStatus.OPEN,
            phase="sell_vol",  # SHORT vol
            opened_at=now,
        ),
        Position(
            strategy_id="ic-001",
            strategy_type="iron_condor",
            status=PositionStatus.OPEN,
            phase=None,  # Iron condor is short vol
            opened_at=now,
        ),
        Position(
            strategy_id="vol-002",
            strategy_type="vol_arb",
            status=PositionStatus.OPEN,
            phase="buy_vol",  # LONG vol - don't close
            opened_at=now,
        ),
        Position(
            strategy_id="whl-001",
            strategy_type="wheel",
            status=PositionStatus.OPEN,
            phase="csp",  # Wheel - don't close
            opened_at=now,
        ),
    ]


def test_identify_short_vol_positions(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
) -> None:
    """Test identifying positions to close in emergency."""
    manager = EmergencyManager(emergency_config)

    to_close = manager.identify_short_vol_positions(short_vol_positions)

    # Should identify vol_arb sell_vol and iron_condor
    assert len(to_close) == 2
    strategy_ids = [p.strategy_id for p in to_close]
    assert "vol-001" in strategy_ids  # sell_vol
    assert "ic-001" in strategy_ids   # iron condor
    assert "vol-002" not in strategy_ids  # buy_vol is long, keep
    assert "whl-001" not in strategy_ids  # wheel is different risk


def test_generate_close_signals(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
    extreme_metrics: MarketMetrics,
) -> None:
    """Test generating CLOSE signals for short vol positions."""
    manager = EmergencyManager(emergency_config)
    now = datetime.now(timezone.utc)

    # Provide contracts from active strategy state
    dummy_contract = OptionContract(
        instrument_name="BTC-28FEB25-85000-P",
        strike=85000.0,
        expiry=now + timedelta(days=30),
        option_type="put",
    )
    strategy_contracts = {
        "vol-001": ([dummy_contract], ["sell"], 0.1),
        "ic-001": ([dummy_contract], ["sell"], 0.1),
    }

    signals = manager.check_emergency(
        extreme_metrics, short_vol_positions, strategy_contracts
    )

    # Should generate 2 close signals
    assert len(signals) == 2

    for signal in signals:
        assert signal.action == SignalAction.CLOSE
        assert len(signal.contracts) > 0
        assert "DVOL emergency" in signal.reason.lower() or "emergency" in signal.reason.lower()


def test_no_signals_when_not_emergency(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
    normal_metrics: MarketMetrics,
) -> None:
    """Test no signals in normal conditions."""
    manager = EmergencyManager(emergency_config)

    signals = manager.check_emergency(normal_metrics, short_vol_positions)

    assert len(signals) == 0


def test_identify_short_vol_positions_empty_list(
    emergency_config: EmergencyConfig,
) -> None:
    """Test handling of empty positions list."""
    manager = EmergencyManager(emergency_config)

    to_close = manager.identify_short_vol_positions([])

    assert to_close == []


def test_identify_short_vol_positions_filters_closed(
    emergency_config: EmergencyConfig,
) -> None:
    """Test that closed positions are filtered out."""
    now = datetime.now(timezone.utc)
    positions = [
        Position(
            strategy_id="ic-closed",
            strategy_type="iron_condor",
            status=PositionStatus.CLOSED,  # Should be filtered
            phase=None,
            opened_at=now,
        ),
        Position(
            strategy_id="ic-open",
            strategy_type="iron_condor",
            status=PositionStatus.OPEN,  # Should be included
            phase=None,
            opened_at=now,
        ),
    ]
    manager = EmergencyManager(emergency_config)

    to_close = manager.identify_short_vol_positions(positions)

    assert len(to_close) == 1
    assert to_close[0].strategy_id == "ic-open"


def test_check_emergency_empty_positions(
    emergency_config: EmergencyConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test no signals when positions list is empty."""
    manager = EmergencyManager(emergency_config)

    signals = manager.check_emergency(extreme_metrics, [])

    assert signals == []
