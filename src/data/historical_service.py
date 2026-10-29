"""Service for fetching and storing historical market data."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import logging
from typing import NamedTuple

from src.backtest.data_fetcher import HistoricalDataFetcher, HistoricalBar
from src.persistence.repositories import HistoricalDataRepository
from src.persistence.models import HistoricalDataPoint

logger = logging.getLogger(__name__)


class FetchResult(NamedTuple):
    """Result of a fetch operation."""

    stored_count: int
    failed_chunks: list[tuple[datetime, datetime, str]]  # (start, end, error)


@dataclass
class FetchConfig:
    """Configuration for historical data fetching.

    Attributes:
        chunk_days: Days per API request chunk. 30 days keeps response sizes
            manageable while minimizing request count.
        rate_limit_delay: Seconds between API requests. Deribit uses a credit-based
            rate limit system (see https://support.deribit.com/hc/en-us/articles/25944617523357).
            Public endpoints have per-IP limits. 0.12s provides ~8 req/s with margin.
        resolution: Candle resolution for BTC price data (e.g., "1D", "1", "60").
            Note: DVOL is always fetched at daily resolution as Deribit only
            provides daily DVOL data via get_volatility_index endpoint.
        max_retries: Maximum retry attempts per chunk on transient failures.
        retry_delay: Base delay between retries (exponential backoff applied).
    """

    chunk_days: int = 30
    rate_limit_delay: float = 0.12  # ~8 req/s with safety margin
    resolution: str = "1D"
    max_retries: int = 3
    retry_delay: float = 1.0


class HistoricalDataService:
    """Fetches and stores historical BTC price and DVOL data."""

    def __init__(
        self,
        fetcher: HistoricalDataFetcher,
        repository: HistoricalDataRepository,
        config: FetchConfig | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            fetcher: HistoricalDataFetcher for API calls.
            repository: HistoricalDataRepository for storage.
            config: Optional fetch configuration.
        """
        self.fetcher = fetcher
        self.repository = repository
        self.config = config or FetchConfig()

    async def fetch_and_store(
        self,
        start_date: datetime,
        end_date: datetime,
        incremental: bool = True,
    ) -> FetchResult:
        """Fetch historical data and store in database.

        Args:
            start_date: Start of date range. Must be timezone-aware.
            end_date: End of date range. Must be timezone-aware.
            incremental: If True, only fetch after last stored timestamp.

        Returns:
            FetchResult with stored count and any failed chunks.

        Raises:
            ValueError: If start_date or end_date is timezone-naive.
        """
        # Fail fast on timezone-naive datetimes
        if start_date.tzinfo is None:
            raise ValueError(
                "start_date must be timezone-aware. "
                f"Got naive datetime: {start_date}"
            )
        if end_date.tzinfo is None:
            raise ValueError(
                "end_date must be timezone-aware. "
                f"Got naive datetime: {end_date}"
            )

        # Normalize to UTC
        start_date = start_date.astimezone(timezone.utc)
        end_date = end_date.astimezone(timezone.utc)

        # Check for incremental update
        if incremental:
            latest = self.repository.get_latest_timestamp()
            if latest:
                # Repository returns UTC timestamps
                if latest.tzinfo is None:
                    # Legacy data without timezone - treat as UTC
                    logger.warning(
                        "Database contains timezone-naive timestamp %s, treating as UTC",
                        latest,
                    )
                    latest = latest.replace(tzinfo=timezone.utc)
                if latest >= start_date:
                    # Start from latest timestamp, not day after.
                    # INSERT OR REPLACE handles duplicates, ensuring we don't
                    # miss updates to the latest day's data.
                    start_date = latest

        if start_date >= end_date:
            return FetchResult(stored_count=0, failed_chunks=[])

        # Fetch in chunks with error handling
        total_stored = 0
        failed_chunks: list[tuple[datetime, datetime, str]] = []
        current = start_date

        while current < end_date:
            chunk_end = min(current + timedelta(days=self.config.chunk_days), end_date)

            try:
                points = await self._fetch_chunk_with_retry(current, chunk_end)

                # Store batch
                if points:
                    self.repository.save_batch(points)
                    total_stored += len(points)
                    logger.info(
                        "Stored %d records for %s to %s",
                        len(points),
                        current.date(),
                        chunk_end.date(),
                    )

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "Failed to fetch chunk %s to %s: %s",
                    current.date(),
                    chunk_end.date(),
                    error_msg,
                )
                failed_chunks.append((current, chunk_end, error_msg))

            current = chunk_end
            await asyncio.sleep(self.config.rate_limit_delay)

        return FetchResult(stored_count=total_stored, failed_chunks=failed_chunks)

    async def _fetch_chunk_with_retry(
        self,
        start: datetime,
        end: datetime,
    ) -> list[HistoricalDataPoint]:
        """Fetch a single chunk with retry logic.

        Args:
            start: Chunk start datetime.
            end: Chunk end datetime.

        Returns:
            List of merged data points.

        Raises:
            Exception: If all retries fail.
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            try:
                # Fetch BTC price
                price_bars = await self.fetcher.fetch_price_history(
                    instrument="BTC-PERPETUAL",
                    start=start,
                    end=end,
                    resolution=self.config.resolution,
                )

                await asyncio.sleep(self.config.rate_limit_delay)

                # Fetch DVOL
                dvol_bars = await self.fetcher.fetch_dvol_history(
                    start=start,
                    end=end,
                    currency="BTC",
                )

                # Merge and return
                return self._merge_data(price_bars, dvol_bars)

            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (2 ** attempt)
                    logger.warning(
                        "Retry %d/%d for chunk %s-%s after error: %s. Waiting %.1fs",
                        attempt + 1,
                        self.config.max_retries,
                        start.date(),
                        end.date(),
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)

        # All retries failed
        raise last_error or RuntimeError("Unknown error during fetch")

    def _merge_data(
        self,
        price_bars: list[HistoricalBar],
        dvol_bars: list[HistoricalBar],
    ) -> list[HistoricalDataPoint]:
        """Merge price and DVOL bars by date.

        Matches bars by date (ignoring time component) since DVOL is only
        available at daily resolution from Deribit. For intraday price data
        support, this would need to be refactored to use timestamp-based
        matching or forward-fill DVOL values.

        Args:
            price_bars: BTC price bars.
            dvol_bars: DVOL bars.

        Returns:
            List of HistoricalDataPoint with aligned data. Only includes
            days where both price and DVOL data exist.
        """
        # Create lookup by date
        dvol_by_date = {bar.timestamp.date(): bar for bar in dvol_bars}

        points = []
        dropped_count = 0

        for price_bar in price_bars:
            dvol_bar = dvol_by_date.get(price_bar.timestamp.date())
            if dvol_bar:
                points.append(HistoricalDataPoint(
                    timestamp=price_bar.timestamp,
                    btc_price=price_bar.close,
                    btc_open=price_bar.open,
                    btc_high=price_bar.high,
                    btc_low=price_bar.low,
                    btc_volume=price_bar.volume,
                    dvol=dvol_bar.close,
                    dvol_open=dvol_bar.open,
                    dvol_high=dvol_bar.high,
                    dvol_low=dvol_bar.low,
                ))
            else:
                dropped_count += 1

        # Warn if significant data was dropped
        if dropped_count > 0:
            logger.warning(
                "Dropped %d price bars due to missing DVOL data (%.1f%% of %d bars)",
                dropped_count,
                100 * dropped_count / len(price_bars) if price_bars else 0,
                len(price_bars),
            )

        return points
