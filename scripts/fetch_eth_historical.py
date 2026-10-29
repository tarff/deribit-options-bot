#!/usr/bin/env python
"""Fetch ETH historical DVOL from production Deribit and store locally.

This provides realistic IV Rank data for paper trading on testnet,
since testnet DVOL history is unreliable.

Usage:
    python scripts/fetch_eth_historical.py
"""

import asyncio
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient


async def fetch_and_store():
    """Fetch ETH historical data and store in trading.db."""

    # Use production Deribit (not testnet)
    client = DeribitClient(base_url="https://www.deribit.com")

    try:
        print("Fetching ETH historical data from production Deribit...")

        # Fetch ETH price history (perpetual)
        print("  Fetching ETH price history...")
        price_data = await client.get_tradingview_chart_data(
            instrument_name="ETH-PERPETUAL",
            resolution="1D",
        )

        # Fetch ETH DVOL history
        print("  Fetching ETH DVOL history...")
        dvol_data = await client.get_volatility_index(
            currency="ETH",
            resolution=86400,  # Daily
        )

        if not price_data or not dvol_data:
            print("Error: Failed to fetch data")
            return 1

        print(f"  Got {len(price_data.get('close', []))} price bars")
        print(f"  Got {len(dvol_data)} DVOL bars")

        # Parse price data
        prices = {}
        timestamps = price_data.get("ticks", [])
        opens = price_data.get("open", [])
        highs = price_data.get("high", [])
        lows = price_data.get("low", [])
        closes = price_data.get("close", [])
        volumes = price_data.get("volume", [])

        for i, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            date_key = dt.strftime("%Y-%m-%d")
            prices[date_key] = {
                "timestamp": dt.isoformat(),
                "open": opens[i] if i < len(opens) else 0,
                "high": highs[i] if i < len(highs) else 0,
                "low": lows[i] if i < len(lows) else 0,
                "close": closes[i] if i < len(closes) else 0,
                "volume": volumes[i] if i < len(volumes) else 0,
            }

        # Parse DVOL data - format: [timestamp, open, high, low, close]
        dvols = {}
        for bar in dvol_data:
            ts = bar[0]
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            date_key = dt.strftime("%Y-%m-%d")
            dvols[date_key] = {
                "open": bar[1],
                "high": bar[2],
                "low": bar[3],
                "close": bar[4] if len(bar) > 4 else bar[1],
            }

        # Merge and prepare records
        records = []
        for date_key in sorted(prices.keys()):
            if date_key not in dvols:
                continue

            p = prices[date_key]
            d = dvols[date_key]

            records.append((
                p["timestamp"],
                p["close"],  # btc_price (actually ETH price)
                p["open"],
                p["high"],
                p["low"],
                p["volume"],
                d["close"],  # dvol
                d["open"],
                d["high"],
                d["low"],
            ))

        print(f"  Prepared {len(records)} merged records")

        # Store in database
        db_path = Path("data/trading.db")
        db_path.parent.mkdir(exist_ok=True)

        print(f"\nStoring in {db_path}...")

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT UNIQUE NOT NULL,
                btc_price REAL NOT NULL,
                btc_open REAL NOT NULL,
                btc_high REAL NOT NULL,
                btc_low REAL NOT NULL,
                btc_volume REAL NOT NULL,
                dvol REAL NOT NULL,
                dvol_open REAL NOT NULL,
                dvol_high REAL NOT NULL,
                dvol_low REAL NOT NULL
            )
        """)

        # Clear existing data
        cursor.execute("DELETE FROM historical_data")

        # Insert new data
        cursor.executemany("""
            INSERT INTO historical_data
            (timestamp, btc_price, btc_open, btc_high, btc_low, btc_volume,
             dvol, dvol_open, dvol_high, dvol_low)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

        conn.commit()

        # Verify
        cursor.execute("SELECT COUNT(*) FROM historical_data")
        count = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM historical_data")
        min_ts, max_ts = cursor.fetchone()

        cursor.execute("SELECT MIN(dvol), MAX(dvol), AVG(dvol) FROM historical_data")
        min_dvol, max_dvol, avg_dvol = cursor.fetchone()

        conn.close()

        print(f"\nStored {count} records")
        print(f"  Date range: {min_ts[:10]} to {max_ts[:10]}")
        print(f"  DVOL range: {min_dvol:.1f} - {max_dvol:.1f} (avg: {avg_dvol:.1f})")

        # Calculate current IV Rank
        dvol_values = [d["close"] for d in dvols.values()]
        current_dvol = dvol_values[-1]
        iv_rank = (current_dvol - min_dvol) / (max_dvol - min_dvol)
        print(f"  Current DVOL: {current_dvol:.1f} (IV Rank: {iv_rank:.1%})")

        print("\nDone! The paper trader will now use this data for IV Rank calculation.")
        return 0

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await client.close()


def main():
    """Main entry point."""
    try:
        exit_code = asyncio.run(fetch_and_store())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
