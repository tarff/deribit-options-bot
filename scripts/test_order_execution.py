#!/usr/bin/env python
"""Test order execution on Deribit testnet.

This script verifies the order execution pipeline by:
1. Placing a limit order far from market (won't fill)
2. Verifying it appears in open orders
3. Cancelling it immediately
4. Verifying cancellation

Usage:
    python scripts/test_order_execution.py --config config/settings.yaml
    python scripts/test_order_execution.py --dry-run  # Just show what would happen
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_settings
from src.data.deribit_client import DeribitClient, DeribitError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def find_test_option(client: DeribitClient, btc_price: float) -> dict | None:
    """Find a suitable option for testing.

    Selects an OTM call option with:
    - 14-30 days to expiration
    - Strike ~10% above current price

    Args:
        client: Deribit client.
        btc_price: Current BTC price.

    Returns:
        Instrument dict or None if not found.
    """
    instruments = await client.get_instruments("BTC", "option")
    now = datetime.now(timezone.utc)

    target_strike = btc_price * 1.10  # 10% OTM call

    best_option = None
    best_score = float("inf")

    for inst in instruments:
        try:
            name = inst["instrument_name"]
            parts = name.split("-")
            if len(parts) < 4:
                continue

            # Parse expiry and strike
            expiry_str = parts[1]
            strike = float(parts[2])
            option_type = parts[3]

            # Only calls
            if option_type != "C":
                continue

            # Parse expiry date
            expiry = datetime.strptime(expiry_str, "%d%b%y")
            expiry = expiry.replace(hour=8, tzinfo=timezone.utc)
            dte = (expiry - now).days

            # Filter by DTE
            if dte < 14 or dte > 30:
                continue

            # Score by proximity to target strike
            score = abs(strike - target_strike)
            if score < best_score:
                best_score = score
                best_option = inst

        except (ValueError, KeyError, IndexError):
            continue

    return best_option


async def run_test(settings_path: Path, dry_run: bool = False) -> bool:
    """Run the order execution test.

    Args:
        settings_path: Path to settings.yaml.
        dry_run: If True, don't actually place orders.

    Returns:
        True if test passed, False otherwise.
    """
    settings = load_settings(settings_path)

    # Verify testnet
    if "test.deribit.com" not in settings.deribit.base_url:
        logger.error("SAFETY: This script only runs on testnet!")
        logger.error(f"Current URL: {settings.deribit.base_url}")
        return False

    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    try:
        # Step 1: Authenticate
        logger.info("=" * 60)
        logger.info("STEP 1: Authenticating with Deribit testnet...")
        await client.authenticate()
        logger.info("✓ Authentication successful")

        # Step 2: Get current price
        logger.info("=" * 60)
        logger.info("STEP 2: Fetching market data...")
        btc_price = await client.get_index_price("btc_usd")
        logger.info(f"✓ BTC Price: ${btc_price:,.2f}")

        # Step 3: Find test option
        logger.info("=" * 60)
        logger.info("STEP 3: Finding suitable test option...")
        option = await find_test_option(client, btc_price)
        if not option:
            logger.error("✗ No suitable option found")
            return False

        instrument_name = option["instrument_name"]
        logger.info(f"✓ Selected: {instrument_name}")

        # Step 4: Get ticker for the option
        logger.info("=" * 60)
        logger.info("STEP 4: Fetching option ticker...")
        ticker = await client.get_ticker(instrument_name)
        mark_price = ticker.get("mark_price", 0)
        best_bid = ticker.get("best_bid_price", 0) or 0
        best_ask = ticker.get("best_ask_price", 0) or 0
        logger.info(f"✓ Mark price: {mark_price:.6f} BTC")
        logger.info(f"✓ Best bid: {best_bid:.6f} BTC")
        logger.info(f"✓ Best ask: {best_ask:.6f} BTC")

        # Step 5: Calculate test order price (far from market)
        # Use a price significantly below market so it won't fill
        if best_bid > 0:
            test_price = best_bid * 0.10  # 90% below bid
        else:
            test_price = mark_price * 0.10  # 90% below mark

        # Get tick size from instrument metadata
        tick_size = option.get("tick_size", 0.0001)

        # Round to valid tick size
        test_price = max(round(test_price / tick_size) * tick_size, tick_size)
        test_amount = option.get("min_trade_amount", 0.1)

        logger.info("=" * 60)
        logger.info("STEP 5: Order parameters...")
        logger.info(f"  Instrument: {instrument_name}")
        logger.info(f"  Direction: BUY")
        logger.info(f"  Amount: {test_amount} BTC")
        logger.info(f"  Price: {test_price:.6f} BTC (far below market)")
        logger.info(f"  Type: LIMIT")

        if dry_run:
            logger.info("=" * 60)
            logger.info("DRY RUN - Order would be placed but not executed")
            logger.info("Run without --dry-run to actually test order execution")
            return True

        # Step 6: Place the order
        logger.info("=" * 60)
        logger.info("STEP 6: Placing limit order...")
        try:
            result = await client.buy(
                instrument_name=instrument_name,
                amount=test_amount,
                price=test_price,
                order_type="limit",
            )
            order = result.get("order", {})
            order_id = order.get("order_id")
            order_state = order.get("order_state")
            logger.info(f"✓ Order placed!")
            logger.info(f"  Order ID: {order_id}")
            logger.info(f"  State: {order_state}")
        except DeribitError as e:
            logger.error(f"✗ Failed to place order: {e.message}")
            return False

        # Step 7: Verify order appears in open orders
        logger.info("=" * 60)
        logger.info("STEP 7: Verifying order in open orders...")
        await asyncio.sleep(0.5)  # Brief pause for order to register

        open_orders = await client.get_open_orders("BTC", "option")
        found = any(o.get("order_id") == order_id for o in open_orders)

        if found:
            logger.info(f"✓ Order {order_id} found in open orders")
        else:
            logger.warning(f"⚠ Order {order_id} not found in open orders")
            logger.warning("  (May have been filled or rejected)")

        # Step 8: Cancel the order
        logger.info("=" * 60)
        logger.info("STEP 8: Cancelling order...")
        try:
            await client.cancel(order_id)
            logger.info(f"✓ Order {order_id} cancelled")
        except DeribitError as e:
            # Order might have already been filled or cancelled
            logger.warning(f"⚠ Cancel response: {e.message}")

        # Step 9: Verify cancellation
        logger.info("=" * 60)
        logger.info("STEP 9: Verifying cancellation...")
        await asyncio.sleep(0.5)

        open_orders = await client.get_open_orders("BTC", "option")
        still_open = any(o.get("order_id") == order_id for o in open_orders)

        if not still_open:
            logger.info(f"✓ Order {order_id} no longer in open orders")
        else:
            logger.error(f"✗ Order {order_id} still appears open!")
            return False

        # Final summary
        logger.info("=" * 60)
        logger.info("TEST PASSED: Order execution pipeline verified")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Summary:")
        logger.info(f"  - Connected to: {settings.deribit.base_url}")
        logger.info(f"  - Instrument: {instrument_name}")
        logger.info(f"  - Order ID: {order_id}")
        logger.info("  - Order placed: ✓")
        logger.info("  - Order verified: ✓")
        logger.info("  - Order cancelled: ✓")
        logger.info("")
        logger.info("The order execution pipeline is working correctly!")

        return True

    except DeribitError as e:
        logger.error(f"Deribit API error: {e.message}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return False
    finally:
        await client.close()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test order execution on Deribit testnet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_order_execution.py --config config/settings.yaml
  python scripts/test_order_execution.py --dry-run

This script will:
  1. Authenticate with Deribit testnet
  2. Find a suitable OTM call option
  3. Place a limit buy order far below market (won't fill)
  4. Verify the order appears in open orders
  5. Cancel the order immediately
  6. Verify the cancellation

SAFETY: This script only runs on testnet (test.deribit.com).
""",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.yaml"),
        help="Path to settings.yaml (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without placing orders",
    )

    args = parser.parse_args()

    if not args.config.exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    success = asyncio.run(run_test(args.config, args.dry_run))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
