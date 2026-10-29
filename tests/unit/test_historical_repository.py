"""Tests for HistoricalDataRepository."""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository
from src.persistence.models import HistoricalDataPoint


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a temporary database."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.initialize()
    return database


@pytest.fixture
def repository(db: Database) -> HistoricalDataRepository:
    """Create a HistoricalDataRepository with test database."""
    return HistoricalDataRepository(db)


def make_point(
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


class TestHistoricalDataRepository:
    """Tests for HistoricalDataRepository."""

    def test_save_and_retrieve(self, repository):
        """Test saving and retrieving a single point."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        point = make_point(ts, btc_price=45000.0, dvol=55.0)

        point_id = repository.save(point)
        assert point_id > 0

        # Retrieve
        points = repository.get_range(ts, ts)
        assert len(points) == 1
        assert points[0].btc_price == 45000.0
        assert points[0].dvol == 55.0
        assert points[0].timestamp == ts

    def test_save_batch(self, repository):
        """Test bulk insert of multiple points."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        points = [
            make_point(base_ts + timedelta(days=i), btc_price=40000 + i * 100)
            for i in range(10)
        ]

        count = repository.save_batch(points)
        assert count == 10
        assert repository.count() == 10

    def test_save_batch_empty(self, repository):
        """Test bulk insert with empty list."""
        count = repository.save_batch([])
        assert count == 0

    def test_get_latest_timestamp(self, repository):
        """Test getting the most recent timestamp."""
        # Empty database
        assert repository.get_latest_timestamp() is None

        # Add some data
        ts1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        ts3 = datetime(2024, 1, 10, tzinfo=timezone.utc)

        repository.save(make_point(ts1))
        repository.save(make_point(ts2))
        repository.save(make_point(ts3))

        latest = repository.get_latest_timestamp()
        assert latest == ts2

    def test_get_range_with_bounds(self, repository):
        """Test retrieving data within a specific range."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            repository.save(make_point(base_ts + timedelta(days=i)))

        # Get middle range
        start = datetime(2024, 1, 10, tzinfo=timezone.utc)
        end = datetime(2024, 1, 20, tzinfo=timezone.utc)
        points = repository.get_range(start, end)

        assert len(points) == 11  # 10th to 20th inclusive
        assert points[0].timestamp == start
        assert points[-1].timestamp == end

    def test_get_range_no_bounds(self, repository):
        """Test retrieving all data with no bounds."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(5):
            repository.save(make_point(base_ts + timedelta(days=i)))

        points = repository.get_range()
        assert len(points) == 5

    def test_get_range_start_only(self, repository):
        """Test retrieving data with only start bound."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            repository.save(make_point(base_ts + timedelta(days=i)))

        start = datetime(2024, 1, 5, tzinfo=timezone.utc)
        points = repository.get_range(start=start)
        assert len(points) == 6  # 5th to 10th

    def test_get_range_end_only(self, repository):
        """Test retrieving data with only end bound."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(10):
            repository.save(make_point(base_ts + timedelta(days=i)))

        end = datetime(2024, 1, 5, tzinfo=timezone.utc)
        points = repository.get_range(end=end)
        assert len(points) == 5  # 1st to 5th

    def test_count(self, repository):
        """Test counting records."""
        assert repository.count() == 0

        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(15):
            repository.save(make_point(base_ts + timedelta(days=i)))

        assert repository.count() == 15

    def test_upsert_on_duplicate_timestamp(self, repository):
        """Test that saving with same timestamp updates the record."""
        ts = datetime(2024, 1, 15, tzinfo=timezone.utc)

        # Save first
        repository.save(make_point(ts, btc_price=40000.0))
        assert repository.count() == 1

        # Save with same timestamp but different price
        repository.save(make_point(ts, btc_price=45000.0))
        assert repository.count() == 1  # Still 1 record

        # Verify updated
        points = repository.get_range()
        assert points[0].btc_price == 45000.0

    def test_data_sorted_by_timestamp(self, repository):
        """Test that retrieved data is sorted by timestamp."""
        timestamps = [
            datetime(2024, 1, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 5, tzinfo=timezone.utc),
            datetime(2024, 1, 25, tzinfo=timezone.utc),
            datetime(2024, 1, 10, tzinfo=timezone.utc),
        ]

        for ts in timestamps:
            repository.save(make_point(ts))

        points = repository.get_range()
        assert len(points) == 4
        assert points[0].timestamp == datetime(2024, 1, 5, tzinfo=timezone.utc)
        assert points[1].timestamp == datetime(2024, 1, 10, tzinfo=timezone.utc)
        assert points[2].timestamp == datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert points[3].timestamp == datetime(2024, 1, 25, tzinfo=timezone.utc)

    def test_get_date_bounds_empty(self, repository):
        """Test get_date_bounds with empty database."""
        start, end = repository.get_date_bounds()
        assert start is None
        assert end is None

    def test_get_date_bounds_with_data(self, repository):
        """Test get_date_bounds returns min/max timestamps."""
        # Insert in non-chronological order
        timestamps = [
            datetime(2024, 1, 15, tzinfo=timezone.utc),
            datetime(2024, 1, 5, tzinfo=timezone.utc),
            datetime(2024, 1, 25, tzinfo=timezone.utc),
        ]

        for ts in timestamps:
            repository.save(make_point(ts))

        start, end = repository.get_date_bounds()
        assert start == datetime(2024, 1, 5, tzinfo=timezone.utc)
        assert end == datetime(2024, 1, 25, tzinfo=timezone.utc)
