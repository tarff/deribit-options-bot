#!/usr/bin/env python
"""Debug script to show available deltas on ETH option chain."""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient
from src.config import load_settings


async def main():
    print("=" * 70)
    print("AVAILABLE ETH OPTION DELTAS ON DERIBIT")
    print("=" * 70)

    # Load settings
    settings = load_settings()

    # Initialize client
    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Get current price
    ticker = await client.get_ticker("ETH-PERPETUAL")
    current_price = ticker.get("last_price", 0)
    print(f"\nCurrent ETH price: ${current_price:,.0f}")

    now = datetime.now(timezone.utc)

    # Get all ETH options
    instruments = await client.get_instruments("ETH", "option")
    print(f"Total instruments: {len(instruments)}")

    # Filter to relevant DTE range and fetch tickers
    by_expiry = {}
    min_strike = current_price * 0.7
    max_strike = current_price * 1.3

    for inst in instruments:
        try:
            parts = inst["instrument_name"].split("-")
            expiry_str = parts[1]
            strike = float(parts[2])

            # Parse expiry
            expiry = datetime.strptime(expiry_str, "%d%b%y")
            expiry = expiry.replace(hour=8, tzinfo=timezone.utc)
            dte = (expiry - now).days

            # Only include 20-60 DTE range
            if dte < 20 or dte > 60:
                continue

            # Only include strikes within range
            if strike < min_strike or strike > max_strike:
                continue

            if dte not in by_expiry:
                by_expiry[dte] = {"puts": [], "calls": []}

            # Fetch ticker to get greeks
            ticker_data = await client.get_ticker(inst["instrument_name"])
            delta = ticker_data.get("greeks", {}).get("delta")

            if delta is None:
                continue

            opt_type = "puts" if inst["instrument_name"].endswith("-P") else "calls"

            by_expiry[dte][opt_type].append({
                "instrument": inst["instrument_name"],
                "strike": strike,
                "delta": delta,
                "bid": ticker_data.get("best_bid_price"),
                "ask": ticker_data.get("best_ask_price"),
            })

        except Exception as e:
            continue

    await client.close()

    # Show DTEs in calibrated range (25-55)
    print("\nDTEs in calibrated range (25-55):")
    relevant_dtes = sorted([d for d in by_expiry.keys() if 25 <= d <= 55])

    if not relevant_dtes:
        print("  No expiries in 25-55 DTE range!")
        print(f"  Available DTEs: {sorted(by_expiry.keys())}")
        return

    for dte in relevant_dtes:
        data = by_expiry[dte]
        puts = sorted(data["puts"], key=lambda x: abs(x["delta"]))
        calls = sorted(data["calls"], key=lambda x: x["delta"], reverse=True)

        print(f"\n{'='*70}")
        print(f"DTE: {dte}")
        print("=" * 70)

        # Show puts sorted by delta (most OTM to ATM)
        print(f"\nPUTS (target: -0.15 short, -0.05 wing)")
        print(f"{'Delta':>8} {'Strike':>10} {'Instrument':<30}")
        print("-" * 50)

        for p in puts[:10]:  # Show 10 most OTM
            delta_str = f"{p['delta']:.3f}"
            match = ""
            if abs(p["delta"] + 0.15) <= 0.05:
                match = " <- SHORT (-0.15)"
            elif abs(p["delta"] + 0.05) <= 0.05:
                match = " <- WING (-0.05)"
            print(f"{delta_str:>8} {p['strike']:>10,.0f} {p['instrument']:<30}{match}")

        # Show calls sorted by delta (most OTM to ATM)
        print(f"\nCALLS (target: +0.15 short, +0.05 wing)")
        print(f"{'Delta':>8} {'Strike':>10} {'Instrument':<30}")
        print("-" * 50)

        for c in calls[:10]:  # Show 10 most OTM
            delta_str = f"{c['delta']:.3f}"
            match = ""
            if abs(c["delta"] - 0.15) <= 0.05:
                match = " <- SHORT (+0.15)"
            elif abs(c["delta"] - 0.05) <= 0.05:
                match = " <- WING (+0.05)"
            print(f"{delta_str:>8} {c['strike']:>10,.0f} {c['instrument']:<30}{match}")

    # Check if wing options exist
    print("\n" + "=" * 70)
    print("WING DELTA ANALYSIS")
    print("=" * 70)

    for dte in relevant_dtes:
        data = by_expiry[dte]
        puts = data["puts"]
        calls = data["calls"]

        # Find closest to 5-delta
        put_5d = min(puts, key=lambda x: abs(x["delta"] + 0.05)) if puts else None
        call_5d = min(calls, key=lambda x: abs(x["delta"] - 0.05)) if calls else None

        # Find closest to 10-delta
        put_10d = min(puts, key=lambda x: abs(x["delta"] + 0.10)) if puts else None
        call_10d = min(calls, key=lambda x: abs(x["delta"] - 0.10)) if calls else None

        print(f"\nDTE {dte}:")

        if put_5d:
            diff = abs(put_5d["delta"] + 0.05)
            within = "YES" if diff <= 0.05 else "NO"
            print(f"  Put  5-delta: closest is {put_5d['delta']:.3f} (diff={diff:.3f}, within 0.05: {within})")

        if call_5d:
            diff = abs(call_5d["delta"] - 0.05)
            within = "YES" if diff <= 0.05 else "NO"
            print(f"  Call 5-delta: closest is {call_5d['delta']:.3f} (diff={diff:.3f}, within 0.05: {within})")

        if put_10d:
            diff = abs(put_10d["delta"] + 0.10)
            within = "YES" if diff <= 0.05 else "NO"
            print(f"  Put 10-delta: closest is {put_10d['delta']:.3f} (diff={diff:.3f}, within 0.05: {within})")

        if call_10d:
            diff = abs(call_10d["delta"] - 0.10)
            within = "YES" if diff <= 0.05 else "NO"
            print(f"  Call 10-delta: closest is {call_10d['delta']:.3f} (diff={diff:.3f}, within 0.05: {within})")


if __name__ == "__main__":
    asyncio.run(main())
