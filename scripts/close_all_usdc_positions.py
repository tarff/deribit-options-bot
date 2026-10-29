#!/usr/bin/env python
"""Close all USDC option positions on Deribit testnet.

Usage:
    python scripts/close_all_usdc_positions.py
    python scripts/close_all_usdc_positions.py --dry-run
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_settings
from src.data.deribit_client import DeribitClient


async def main(dry_run: bool = False) -> None:
    settings = load_settings()
    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )
    await client.authenticate()

    # Get all USDC option positions
    positions = await client.get_positions(currency="USDC", kind="option")

    if not positions:
        print("No USDC option positions found.")
        await client.close()
        return

    print(f"Found {len(positions)} USDC option positions:\n")
    for p in positions:
        name = p.get("instrument_name", "?")
        direction = p.get("direction", "?")
        size = p.get("size", 0)
        avg_price = p.get("average_price", 0)
        pnl = p.get("floating_profit_loss", 0)
        print(f"  {direction:5} {abs(size):6.1f} {name:40} avg=${avg_price:.2f}  pnl=${pnl:.2f}")

    if dry_run:
        print("\n[DRY RUN] Would close all positions above. Run without --dry-run to execute.")
        await client.close()
        return

    print("\nClosing all positions with market orders...\n")

    for p in positions:
        name = p.get("instrument_name", "?")
        direction = p.get("direction", "?")
        size = abs(p.get("size", 0))

        if size <= 0:
            continue

        # To close: sell if long, buy if short
        close_direction = "sell" if direction == "buy" else "buy"

        try:
            if close_direction == "buy":
                result = await client.buy(
                    instrument_name=name,
                    amount=size,
                    order_type="market",
                )
            else:
                result = await client.sell(
                    instrument_name=name,
                    amount=size,
                    order_type="market",
                )

            order = result.get("order", {})
            trades = result.get("trades", [])
            filled = sum(t.get("amount", 0) for t in trades)
            state = order.get("order_state", "?")

            print(f"  {close_direction.upper():5} {size} {name}: state={state} filled={filled}")

            if filled <= 0:
                print(f"    WARNING: Zero fill - order may be sitting on book")

        except Exception as e:
            print(f"  ERROR closing {name}: {e}")

        # Rate limit
        await asyncio.sleep(0.15)

    # Verify
    print("\nVerifying remaining positions...")
    remaining = await client.get_positions(currency="USDC", kind="option")
    open_remaining = [p for p in remaining if abs(p.get("size", 0)) > 0]

    if open_remaining:
        print(f"  WARNING: {len(open_remaining)} positions still open:")
        for p in open_remaining:
            print(f"    {p.get('direction')} {abs(p.get('size', 0))} {p.get('instrument_name')}")
    else:
        print("  All positions closed successfully.")

    await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Close all USDC option positions")
    parser.add_argument("--dry-run", action="store_true", help="Show positions without closing")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
