#!/usr/bin/env python
"""Run paper trading loop against Deribit testnet."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import PaperTradingConfig, Settings, load_settings
from src.execution.paper_trading import PaperTradingLoop
from src.persistence.database import Database


def setup_logging(verbose: bool = False) -> None:
    """Configure logging.

    Args:
        verbose: If True, enable DEBUG level logging.
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from aiohttp
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def build_paper_config(
    args: argparse.Namespace,
    settings: Settings,
) -> PaperTradingConfig:
    """Build paper trading config from settings with explicit CLI overrides."""
    use_market_orders = settings.paper_trading.use_market_orders
    if getattr(args, "market_orders", False):
        use_market_orders = True
    if getattr(args, "limit_orders", False):
        use_market_orders = False

    return PaperTradingConfig(
        loop_interval_seconds=args.interval,
        position_sync_interval=settings.paper_trading.position_sync_interval,
        use_market_orders=use_market_orders,
        initial_capital_usd=args.capital,
    )


async def run(args: argparse.Namespace) -> int:
    """Run the paper trading loop.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Load settings
    settings = load_settings(args.config)

    config = build_paper_config(args, settings)

    # Initialize database
    db_path = str(args.db)
    db = Database(db_path)
    db.initialize()

    # If fresh start requested, clear paper trading state
    if args.fresh:
        logger.info("Fresh start requested - clearing saved state")
        cursor = db.connection.cursor()
        cursor.execute("DELETE FROM paper_trading_state")
        cursor.execute("DELETE FROM position_contracts")
        cursor.execute("UPDATE positions SET status = 'closed' WHERE status = 'open'")
        db.connection.commit()

    logger.info("Paper Trading Configuration:")
    logger.info(f"  API: {settings.deribit.base_url}")
    logger.info(f"  Currency: {settings.trading.currency}")
    logger.info(f"  Database: {db_path}")
    logger.info(f"  Interval: {config.loop_interval_seconds}s")
    logger.info(f"  Order type: {'market' if config.use_market_orders else 'limit'}")
    logger.info(f"  Initial capital: ${config.initial_capital_usd:,.2f}")
    logger.info(f"  DVOL thresholds: reduce={settings.risk.dvol_reduce_threshold}, halt={settings.risk.dvol_halt_threshold}")

    if args.dry_run:
        logger.info("DRY RUN - no orders will be placed")
        return 0

    # Create loop
    loop = PaperTradingLoop(config, settings, db)

    # Run the loop - shutdown is handled via KeyboardInterrupt

    print("\n" + "=" * 60)
    print(f"  PAPER TRADING - {settings.trading.currency} Options - Deribit Testnet")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")

    try:
        await loop.start()
    except asyncio.CancelledError:
        logger.info("Paper trading cancelled")
    except Exception as e:
        logger.error(f"Paper trading failed: {e}")
        return 1
    finally:
        await loop.stop()

    # Print summary
    print("\n" + "=" * 60)
    print("  SESSION SUMMARY")
    print("=" * 60)
    print(f"  Iterations:    {loop.iteration_count}")
    print(f"  Final Capital: ${loop.capital:,.2f}")
    print(f"  Daily PnL:     ${loop.daily_pnl:+,.2f}")
    print("=" * 60)

    return 0


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run paper trading loop against Deribit testnet"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.yaml"),
        help="Path to settings.yaml (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/paper_trading.db"),
        help="Path to SQLite database (default: data/paper_trading.db)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Loop interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital in USD (default: 10000)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start fresh, ignoring saved state (clears capital/positions)",
    )
    order_group = parser.add_mutually_exclusive_group()
    order_group.add_argument(
        "--limit-orders",
        action="store_true",
        help="Use limit orders instead of market orders",
    )
    order_group.add_argument(
        "--market-orders",
        action="store_true",
        help="Use market orders instead of configured limit orders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without starting loop",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nPaper trading stopped")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
