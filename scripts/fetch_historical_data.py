"""CLI script to fetch and store historical market data."""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient
from src.backtest.data_fetcher import HistoricalDataFetcher
from src.data.historical_service import HistoricalDataService, FetchConfig
from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository


def parse_date(date_str: str, arg_name: str) -> datetime:
    """Parse date string to datetime with error handling.

    Args:
        date_str: Date in YYYY-MM-DD format.
        arg_name: Argument name for error message.

    Returns:
        Parsed datetime with UTC timezone.

    Raises:
        SystemExit: If date format is invalid.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: Invalid date format for {arg_name}: '{date_str}'")
        print("Expected format: YYYY-MM-DD (e.g., 2024-01-15)")
        sys.exit(1)


def calculate_chunks(start: datetime, end: datetime, chunk_days: int) -> list[tuple[datetime, datetime]]:
    """Calculate the date chunks that would be fetched.

    Args:
        start: Start date.
        end: End date.
        chunk_days: Days per chunk.

    Returns:
        List of (chunk_start, chunk_end) tuples.
    """
    from datetime import timedelta

    chunks = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=chunk_days), end)
        chunks.append((current, chunk_end))
        current = chunk_end
    return chunks


async def run(args: argparse.Namespace) -> int:
    """Execute the fetch operation.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    # Parse dates
    start_date = parse_date(args.start, "--start")
    end_date = (
        parse_date(args.end, "--end")
        if args.end
        else datetime.now(timezone.utc)
    )

    if start_date >= end_date:
        print(f"Error: Start date ({start_date.date()}) must be before end date ({end_date.date()})")
        return 1

    # Dry-run mode: show what would be fetched without calling API
    if args.dry_run:
        total_days = (end_date - start_date).days
        chunks = calculate_chunks(start_date, end_date, args.chunk_days)

        print("=== DRY RUN ===")
        print(f"Date range: {start_date.date()} to {end_date.date()} ({total_days} days)")
        print(f"Chunk size: {args.chunk_days} days")
        print(f"Number of chunks: {len(chunks)}")
        print(f"API requests: {len(chunks) * 2} (price + DVOL per chunk)")
        print(f"Database: {args.db}")
        print(f"Mode: {'Full fetch' if args.no_incremental else 'Incremental'}")
        print("\nChunks:")
        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            chunk_days = (chunk_end - chunk_start).days
            print(f"  {i}. {chunk_start.date()} to {chunk_end.date()} ({chunk_days} days)")

        # Check existing data if db exists
        if Path(args.db).exists():
            db = Database(args.db)
            db.initialize()
            repo = HistoricalDataRepository(db)
            existing = repo.count()
            latest = repo.get_latest_timestamp()
            db.close()

            print(f"\nExisting data: {existing} records")
            if latest:
                print(f"Latest timestamp: {latest.date()}")
                if not args.no_incremental and latest >= start_date:
                    from datetime import timedelta
                    effective_start = latest + timedelta(days=1)
                    if effective_start >= end_date:
                        print("Status: Already up to date (no fetch needed)")
                    else:
                        effective_days = (end_date - effective_start).days
                        print(f"Incremental start: {effective_start.date()} ({effective_days} days to fetch)")

        return 0

    print(f"Fetching data from {start_date.date()} to {end_date.date()}...")

    # Initialize components
    client = DeribitClient()
    db: Database | None = None

    try:
        fetcher = HistoricalDataFetcher(client)
        db = Database(args.db)
        db.initialize()
        repository = HistoricalDataRepository(db)
        config = FetchConfig(chunk_days=args.chunk_days)
        service = HistoricalDataService(fetcher, repository, config)

        existing = repository.count()
        print(f"Existing records: {existing}")

        latest = repository.get_latest_timestamp()
        if latest:
            print(f"Latest timestamp: {latest.date()}")

        result = await service.fetch_and_store(
            start_date=start_date,
            end_date=end_date,
            incremental=not args.no_incremental,
        )

        print(f"Stored {result.stored_count} new records")

        # Report any failures
        if result.failed_chunks:
            print(f"\nWarning: {len(result.failed_chunks)} chunk(s) failed:")
            for start, end, error in result.failed_chunks:
                print(f"  {start.date()} to {end.date()}: {error}")
        print(f"Total records: {repository.count()}")

        # Show date range
        data = repository.get_range()
        if data:
            print(f"Date range: {data[0].timestamp.date()} to {data[-1].timestamp.date()}")

        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 130  # Standard exit code for Ctrl+C

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        return 1

    finally:
        await client.close()
        if db:
            db.close()


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Fetch historical BTC + DVOL data from Deribit"
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD), defaults to today",
    )
    parser.add_argument(
        "--db",
        default="data/trading.db",
        help="Database path (default: data/trading.db)",
    )
    parser.add_argument(
        "--no-incremental",
        action="store_true",
        help="Fetch all data, not just new",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=30,
        help="Days per API request chunk (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without calling API",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
