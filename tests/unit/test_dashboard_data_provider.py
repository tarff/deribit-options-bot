"""Tests for DashboardDataProvider."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.persistence.database import Database
from src.persistence.repositories import PositionRepository, SnapshotRepository
from src.persistence.models import (
    HistoricalDataPoint,
    Position,
    PositionStatus,
    MarketSnapshot,
)
from src.dashboard.data_provider import DashboardDataProvider


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a temporary database."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.initialize()
    return database


@pytest.fixture
def provider(db: Database) -> DashboardDataProvider:
    """Create a DashboardDataProvider with test database."""
    return DashboardDataProvider(db)


def make_historical_point(
    timestamp: datetime,
    btc_price: float = 50000.0,
    dvol: float = 60.0,
) -> HistoricalDataPoint:
    """Create a test HistoricalDataPoint."""
    return HistoricalDataPoint(
        timestamp=timestamp,
        btc_price=btc_price,
        btc_open=btc_price - 100,
        btc_high=btc_price + 200,
        btc_low=btc_price - 200,
        btc_volume=1000.0,
        dvol=dvol,
        dvol_open=dvol - 1,
        dvol_high=dvol + 2,
        dvol_low=dvol - 2,
    )


class TestDashboardDataProvider:
    """Tests for DashboardDataProvider."""

    def test_get_historical_data_empty(self, provider: DashboardDataProvider) -> None:
        """Test getting historical data when empty."""
        data = provider.get_historical_data()
        assert data == []

    def test_get_historical_data_with_data(self, provider: DashboardDataProvider) -> None:
        """Test getting historical data with records."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            provider.historical_repo.save(
                make_historical_point(base_ts + timedelta(days=i))
            )

        # Get all data
        data = provider.get_historical_data(
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        assert len(data) == 10

    def test_get_historical_data_with_range(self, provider: DashboardDataProvider) -> None:
        """Test getting historical data with date range filter."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            provider.historical_repo.save(
                make_historical_point(base_ts + timedelta(days=i))
            )

        # Get subset
        data = provider.get_historical_data(
            start=datetime(2024, 1, 10, tzinfo=timezone.utc),
            end=datetime(2024, 1, 20, tzinfo=timezone.utc),
        )
        assert len(data) == 11

    def test_get_open_positions_empty(self, provider: DashboardDataProvider) -> None:
        """Test getting open positions when none exist."""
        positions = provider.get_open_positions()
        assert positions == []

    def test_get_open_positions_with_data(self, db: Database, provider: DashboardDataProvider) -> None:
        """Test getting open positions."""
        position_repo = PositionRepository(db)

        # Create an open position
        position = Position(
            strategy_id="test-1",
            strategy_type="wheel",
            status=PositionStatus.OPEN,
            entry_price=45000.0,
            current_pnl=500.0,
            delta=0.5,
            gamma=0.001,
            theta=-10.0,
            vega=50.0,
            opened_at=datetime.now(timezone.utc),
        )
        position_repo.save(position)

        # Create a closed position (should not appear)
        closed_position = Position(
            strategy_id="test-2",
            strategy_type="iron_condor",
            status=PositionStatus.CLOSED,
            entry_price=46000.0,
            opened_at=datetime.now(timezone.utc),
        )
        position_repo.save(closed_position)

        positions = provider.get_open_positions()
        assert len(positions) == 1
        assert positions[0]["strategy_id"] == "test-1"
        assert positions[0]["strategy_type"] == "wheel"
        assert positions[0]["current_pnl"] == 500.0

    def test_get_latest_market_state_empty(self, provider: DashboardDataProvider) -> None:
        """Test getting market state when no snapshots exist."""
        state = provider.get_latest_market_state()
        assert state is None

    def test_get_latest_market_state_with_data(self, db: Database, provider: DashboardDataProvider) -> None:
        """Test getting latest market state."""
        snapshot_repo = SnapshotRepository(db)

        # Add snapshots
        old_snapshot = MarketSnapshot(
            btc_price=44000.0,
            dvol=55.0,
            iv_rank=0.4,
            regime="neutral",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        snapshot_repo.save(old_snapshot)

        new_snapshot = MarketSnapshot(
            btc_price=45000.0,
            dvol=60.0,
            iv_rank=0.6,
            regime="high_iv_overpriced",
            timestamp=datetime.now(timezone.utc),
        )
        snapshot_repo.save(new_snapshot)

        state = provider.get_latest_market_state()
        assert state is not None
        assert state["btc_price"] == 45000.0
        assert state["dvol"] == 60.0
        assert state["regime"] == "high_iv_overpriced"

    def test_get_regime_distribution_empty(self, provider: DashboardDataProvider) -> None:
        """Test getting regime distribution when no snapshots exist."""
        distribution = provider.get_regime_distribution()
        assert distribution == {}

    def test_get_regime_distribution_with_data(self, db: Database, provider: DashboardDataProvider) -> None:
        """Test getting regime distribution."""
        snapshot_repo = SnapshotRepository(db)

        # Add snapshots with different regimes
        now = datetime.now(timezone.utc)
        regimes = ["neutral", "neutral", "neutral", "high_stress", "high_stress", "extreme_fear"]

        for i, regime in enumerate(regimes):
            snapshot = MarketSnapshot(
                btc_price=45000.0 + i * 100,
                dvol=60.0,
                regime=regime,
                timestamp=now - timedelta(hours=i),
            )
            snapshot_repo.save(snapshot)

        distribution = provider.get_regime_distribution(start=now - timedelta(days=1))
        assert distribution["neutral"] == 3
        assert distribution["high_stress"] == 2
        assert distribution["extreme_fear"] == 1

    def test_get_historical_data_count(self, provider: DashboardDataProvider) -> None:
        """Test getting historical data count."""
        assert provider.get_historical_data_count() == 0

        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(5):
            provider.historical_repo.save(
                make_historical_point(base_ts + timedelta(days=i))
            )

        assert provider.get_historical_data_count() == 5

    def test_get_historical_date_range_empty(self, provider: DashboardDataProvider) -> None:
        """Test getting date range when empty."""
        start, end = provider.get_historical_date_range()
        assert start is None
        assert end is None

    def test_get_historical_date_range_with_data(self, provider: DashboardDataProvider) -> None:
        """Test getting date range with data."""
        start_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_ts = datetime(2024, 1, 10, tzinfo=timezone.utc)

        provider.historical_repo.save(make_historical_point(start_ts))
        provider.historical_repo.save(make_historical_point(end_ts))

        start, end = provider.get_historical_date_range()
        assert start == start_ts
        assert end == end_ts
