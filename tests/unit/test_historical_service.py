"""Tests for HistoricalDataService."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.data.historical_service import HistoricalDataService, FetchConfig
from src.backtest.data_fetcher import HistoricalBar
from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository


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


@pytest.fixture
def mock_fetcher():
    """Create a mock HistoricalDataFetcher."""
    fetcher = MagicMock()
    fetcher.fetch_price_history = AsyncMock()
    fetcher.fetch_dvol_history = AsyncMock()
    return fetcher


def make_price_bar(ts: datetime, price: float) -> HistoricalBar:
    """Create a test price bar."""
    return HistoricalBar(
        timestamp=ts,
        open=price - 50,
        high=price + 100,
        low=price - 100,
        close=price,
        volume=1000.0,
    )


def make_dvol_bar(ts: datetime, dvol: float) -> HistoricalBar:
    """Create a test DVOL bar."""
    return HistoricalBar(
        timestamp=ts,
        open=dvol - 1,
        high=dvol + 2,
        low=dvol - 2,
        close=dvol,
        volume=0.0,
    )


class TestHistoricalDataService:
    """Tests for HistoricalDataService."""

    @pytest.mark.asyncio
    async def test_fetch_and_store_basic(self, mock_fetcher, repository):
        """Test basic fetch and store operation."""
        # Setup mock data
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        price_bars = [make_price_bar(base_ts + timedelta(days=i), 45000 + i * 100) for i in range(5)]
        dvol_bars = [make_dvol_bar(base_ts + timedelta(days=i), 55 + i) for i in range(5)]

        mock_fetcher.fetch_price_history.return_value = price_bars
        mock_fetcher.fetch_dvol_history.return_value = dvol_bars

        # Create service with fast config
        config = FetchConfig(chunk_days=30, rate_limit_delay=0.001)
        service = HistoricalDataService(mock_fetcher, repository, config)

        # Fetch and store
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 10, tzinfo=timezone.utc)
        result = await service.fetch_and_store(start, end, incremental=False)

        assert result.stored_count == 5
        assert result.failed_chunks == []
        assert repository.count() == 5

        # Verify data was merged correctly
        points = repository.get_range()
        assert points[0].btc_price == 45000
        assert points[0].dvol == 55

    @pytest.mark.asyncio
    async def test_fetch_and_store_incremental(self, mock_fetcher, repository):
        """Test incremental fetch skips already stored data."""
        # Pre-populate with some data
        from src.persistence.models import HistoricalDataPoint

        existing_ts = datetime(2024, 1, 5, tzinfo=timezone.utc)
        repository.save(HistoricalDataPoint(
            timestamp=existing_ts,
            btc_price=40000,
            btc_open=39900,
            btc_high=40200,
            btc_low=39800,
            btc_volume=500,
            dvol=50,
            dvol_open=49,
            dvol_high=52,
            dvol_low=48,
        ))

        # Setup mock for new data
        new_ts = datetime(2024, 1, 6, tzinfo=timezone.utc)
        price_bars = [make_price_bar(new_ts + timedelta(days=i), 42000 + i * 100) for i in range(3)]
        dvol_bars = [make_dvol_bar(new_ts + timedelta(days=i), 52 + i) for i in range(3)]

        mock_fetcher.fetch_price_history.return_value = price_bars
        mock_fetcher.fetch_dvol_history.return_value = dvol_bars

        config = FetchConfig(chunk_days=30, rate_limit_delay=0.001)
        service = HistoricalDataService(mock_fetcher, repository, config)

        # Fetch incrementally - should only get data after Jan 5
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, tzinfo=timezone.utc)
        result = await service.fetch_and_store(start, end, incremental=True)

        assert result.stored_count == 3
        assert result.failed_chunks == []
        assert repository.count() == 4  # 1 existing + 3 new

    @pytest.mark.asyncio
    async def test_fetch_and_store_already_up_to_date(self, mock_fetcher, repository):
        """Test that no fetch happens when already up to date."""
        # Pre-populate with data up to Jan 10
        from src.persistence.models import HistoricalDataPoint

        for i in range(10):
            ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
            repository.save(HistoricalDataPoint(
                timestamp=ts,
                btc_price=40000 + i * 100,
                btc_open=39900,
                btc_high=40200,
                btc_low=39800,
                btc_volume=500,
                dvol=50 + i,
                dvol_open=49,
                dvol_high=52,
                dvol_low=48,
            ))

        config = FetchConfig(chunk_days=30, rate_limit_delay=0.001)
        service = HistoricalDataService(mock_fetcher, repository, config)

        # Request data that's already stored
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)
        result = await service.fetch_and_store(start, end, incremental=True)

        assert result.stored_count == 0
        assert result.failed_chunks == []
        # Fetcher should not be called
        mock_fetcher.fetch_price_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_and_store_chunked(self, mock_fetcher, repository):
        """Test that large date ranges are chunked."""
        # Setup to track calls
        call_count = 0

        async def track_price_calls(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            start = kwargs.get("start") or args[1]
            return [make_price_bar(start + timedelta(days=i), 45000 + i * 100) for i in range(5)]

        async def track_dvol_calls(*args, **kwargs):
            start = kwargs.get("start") or args[0]
            return [make_dvol_bar(start + timedelta(days=i), 55 + i) for i in range(5)]

        mock_fetcher.fetch_price_history.side_effect = track_price_calls
        mock_fetcher.fetch_dvol_history.side_effect = track_dvol_calls

        # Small chunk size to force multiple chunks
        config = FetchConfig(chunk_days=10, rate_limit_delay=0.001)
        service = HistoricalDataService(mock_fetcher, repository, config)

        # Request 30 days - should be 3 chunks
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)
        await service.fetch_and_store(start, end, incremental=False)

        # Should have called price fetch 3 times
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_merge_data_filters_unmatched(self, mock_fetcher, repository):
        """Test that merge only includes bars present in both datasets."""
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)

        # Price bars for days 1-5
        price_bars = [make_price_bar(base_ts + timedelta(days=i), 45000) for i in range(5)]

        # DVOL bars for days 2-6 (indices 2,3,4,5,6 -> Jan 3-7)
        # Price bars: Jan 1-5 (indices 0,1,2,3,4)
        # Overlap: Jan 3, 4, 5 (indices 2,3,4) = 3 days
        dvol_bars = [make_dvol_bar(base_ts + timedelta(days=i), 55) for i in range(2, 7)]

        mock_fetcher.fetch_price_history.return_value = price_bars
        mock_fetcher.fetch_dvol_history.return_value = dvol_bars

        config = FetchConfig(chunk_days=30, rate_limit_delay=0.001)
        service = HistoricalDataService(mock_fetcher, repository, config)

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 10, tzinfo=timezone.utc)
        result = await service.fetch_and_store(start, end, incremental=False)

        # Only Jan 3, 4, 5 stored (3 overlapping days between price and DVOL)
        assert result.stored_count == 3
        assert result.failed_chunks == []

    def test_merge_data_empty(self, mock_fetcher, repository):
        """Test merge with empty inputs."""
        config = FetchConfig()
        service = HistoricalDataService(mock_fetcher, repository, config)

        # Empty price bars
        result = service._merge_data([], [make_dvol_bar(datetime.now(timezone.utc), 55)])
        assert len(result) == 0

        # Empty dvol bars
        result = service._merge_data([make_price_bar(datetime.now(timezone.utc), 45000)], [])
        assert len(result) == 0
