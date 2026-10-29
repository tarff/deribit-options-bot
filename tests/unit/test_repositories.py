"""Tests for database repositories."""

import pytest
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from src.persistence.database import Database
from src.persistence.repositories import TradeRepository, PositionRepository, SnapshotRepository
from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create initialized test database."""
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def trade_repo(db: Database) -> TradeRepository:
    return TradeRepository(db)


@pytest.fixture
def position_repo(db: Database) -> PositionRepository:
    return PositionRepository(db)


@pytest.fixture
def snapshot_repo(db: Database) -> SnapshotRepository:
    return SnapshotRepository(db)


def test_trade_repository_save_and_get(trade_repo: TradeRepository) -> None:
    """Test saving and retrieving a trade."""
    trade = Trade(
        strategy_id="WHL-001",
        strategy_type="wheel",
        order_id="ORD-123",
        instrument="BTC-28MAR25-100000-P",
        side="sell",
        quantity=0.1,
        price=1500.0,
        status=TradeStatus.FILLED,
        opened_at=datetime.now(timezone.utc),
    )

    trade_id = trade_repo.save(trade)
    assert trade_id > 0

    retrieved = trade_repo.get_by_id(trade_id)
    assert retrieved is not None
    assert retrieved.strategy_id == "WHL-001"
    assert retrieved.order_id == "ORD-123"


def test_trade_repository_get_by_strategy(trade_repo: TradeRepository) -> None:
    """Test retrieving trades by strategy ID."""
    now = datetime.now(timezone.utc)

    trade_repo.save(Trade(
        strategy_id="WHL-001", strategy_type="wheel", instrument="BTC-P",
        side="sell", quantity=0.1, price=1500.0, status=TradeStatus.FILLED, opened_at=now,
    ))
    trade_repo.save(Trade(
        strategy_id="WHL-001", strategy_type="wheel", instrument="BTC-C",
        side="sell", quantity=0.1, price=1200.0, status=TradeStatus.FILLED, opened_at=now,
    ))
    trade_repo.save(Trade(
        strategy_id="IC-001", strategy_type="iron_condor", instrument="BTC-P",
        side="sell", quantity=0.2, price=800.0, status=TradeStatus.FILLED, opened_at=now,
    ))

    wheel_trades = trade_repo.get_by_strategy("WHL-001")
    assert len(wheel_trades) == 2


def test_position_repository_save_and_update(position_repo: PositionRepository) -> None:
    """Test saving and updating a position."""
    position = Position(
        strategy_id="IC-001",
        strategy_type="iron_condor",
        status=PositionStatus.OPEN,
        delta=-0.03,
        theta=47.0,
        opened_at=datetime.now(timezone.utc),
    )

    pos_id = position_repo.save(position)
    assert pos_id > 0

    # Update PnL
    position_repo.update_pnl(pos_id, current_pnl=187.50)

    retrieved = position_repo.get_by_id(pos_id)
    assert retrieved is not None
    assert retrieved.current_pnl == 187.50


def test_snapshot_repository_get_latest(snapshot_repo: SnapshotRepository) -> None:
    """Test retrieving latest snapshot."""
    t1 = datetime(2026, 1, 18, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 18, 10, 5, 0, tzinfo=timezone.utc)

    snapshot_repo.save(MarketSnapshot(
        btc_price=97000.0, dvol=50.0, regime="neutral", timestamp=t1,
    ))
    snapshot_repo.save(MarketSnapshot(
        btc_price=97500.0, dvol=52.0, regime="high_iv", timestamp=t2,
    ))

    latest = snapshot_repo.get_latest()
    assert latest is not None
    assert latest.btc_price == 97500.0
    assert latest.regime == "high_iv"
