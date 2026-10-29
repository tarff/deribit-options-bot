#!/usr/bin/env python
"""Analyze STRIKE_RANGE_PCT coverage using historical data.

IMPORTANT LIMITATION:
This is a data-driven SIMULATION, not a true backtest.
We use Black-Scholes to ESTIMATE where 5-delta options would have been
based on historical price/DVOL data. We do NOT have actual historical
option chain snapshots.

The accuracy depends on:
1. Black-Scholes being a reasonable approximation
2. Deribit's strike spacing patterns being consistent
3. Time-to-expiration assumptions (we use 45 DTE as typical)

Despite limitations, this provides an empirical basis for STRIKE_RANGE_PCT
using 999 days of actual market data rather than arbitrary guesses.
"""

import sqlite3
import sys
from datetime import datetime, timezone
from math import exp, log, sqrt
from pathlib import Path
from statistics import median, stdev

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))


def black_scholes_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Calculate Black-Scholes delta.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'

    Returns:
        Delta value
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))

    if option_type == 'call':
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1


def find_strike_for_delta(
    spot: float,
    target_delta: float,
    T: float,
    sigma: float,
    option_type: str,
    r: float = 0.0,
) -> float:
    """Binary search for strike that gives target delta.

    Args:
        spot: Current spot price
        target_delta: Target delta (negative for puts)
        T: Time to expiry in years
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'
        r: Risk-free rate

    Returns:
        Strike price that produces target delta
    """
    # Search bounds - wide enough to capture extreme cases
    if option_type == 'put':
        # 5-delta put is far OTM (below spot)
        # With high IV, could be very far below
        low, high = spot * 0.05, spot * 1.0
    else:
        # 5-delta call is far OTM (above spot)
        low, high = spot * 1.0, spot * 5.0

    for _ in range(100):  # Binary search iterations
        mid = (low + high) / 2
        delta = black_scholes_delta(spot, mid, T, r, sigma, option_type)

        if option_type == 'put':
            # Put delta is negative. -0.05 > -0.50
            # Higher strike = more negative delta (closer to -1)
            # Lower strike = delta closer to 0
            # We want -0.05, so if delta is more negative, strike is too high
            if delta < target_delta:  # delta more negative than target
                high = mid  # Lower the strike
            else:
                low = mid  # Raise the strike
        else:
            # Call delta is positive. 0.05 < 0.50
            # Lower strike = higher delta (closer to 1)
            # Higher strike = delta closer to 0
            # We want 0.05, so if delta is too high, strike is too low
            if delta > target_delta:
                low = mid  # Raise the strike to lower delta
            else:
                high = mid  # Lower the strike to raise delta

        if abs(delta - target_delta) < 0.0001:
            break

    return mid


def main():
    print("=" * 70)
    print("STRIKE_RANGE_PCT COVERAGE ANALYSIS")
    print("=" * 70)
    print("\nNOTE: This uses Black-Scholes estimates, not actual option chain data.")
    print("Results are approximations based on 999 days of historical price/DVOL.\n")

    # Load historical data
    db_path = Path("data/trading.db")
    if not db_path.exists():
        print("ERROR: Database not found at data/trading.db")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT timestamp, btc_price, dvol
        FROM historical_data
        WHERE btc_price IS NOT NULL AND dvol IS NOT NULL
        ORDER BY timestamp
    """)
    rows = cursor.fetchall()
    conn.close()

    print(f"Loaded {len(rows)} days of data")
    print(f"Date range: {rows[0][0][:10]} to {rows[-1][0][:10]}")

    # Target parameters
    TARGET_DELTA_PUT = -0.05  # 5-delta put
    TARGET_DELTA_CALL = 0.05  # 5-delta call
    DTE = 45  # Days to expiration (typical target)
    T = DTE / 365  # Time in years

    print(f"\nParameters:")
    print(f"  Target delta: ±0.05 (5-delta)")
    print(f"  DTE assumed: {DTE}")

    # Calculate strike distances for each day
    put_distances = []  # (spot - put_strike) / spot
    call_distances = []  # (call_strike - spot) / spot

    for timestamp, spot, dvol in rows:
        sigma = dvol / 100  # Convert DVOL percentage to decimal

        # Find theoretical 5-delta strikes
        put_strike = find_strike_for_delta(spot, TARGET_DELTA_PUT, T, sigma, 'put')
        call_strike = find_strike_for_delta(spot, TARGET_DELTA_CALL, T, sigma, 'call')

        put_dist = (spot - put_strike) / spot
        call_dist = (call_strike - spot) / spot

        put_distances.append(put_dist)
        call_distances.append(call_dist)

    # Statistics
    all_distances = put_distances + call_distances

    print(f"\n{'='*70}")
    print("STRIKE DISTANCE STATISTICS (distance from spot to 5-delta strike)")
    print("=" * 70)
    print(f"\nPut side (how far below spot):")
    print(f"  Min:    {min(put_distances):.2%}")
    print(f"  Max:    {max(put_distances):.2%}")
    print(f"  Median: {median(put_distances):.2%}")
    print(f"  Stdev:  {stdev(put_distances):.2%}")

    print(f"\nCall side (how far above spot):")
    print(f"  Min:    {min(call_distances):.2%}")
    print(f"  Max:    {max(call_distances):.2%}")
    print(f"  Median: {median(call_distances):.2%}")
    print(f"  Stdev:  {stdev(call_distances):.2%}")

    print(f"\nCombined (max of put/call distance each day):")
    max_daily = [max(p, c) for p, c in zip(put_distances, call_distances)]
    print(f"  Min:    {min(max_daily):.2%}")
    print(f"  Max:    {max(max_daily):.2%}")
    print(f"  Median: {median(max_daily):.2%}")
    print(f"  Stdev:  {stdev(max_daily):.2%}")

    # Test different STRIKE_RANGE_PCT values
    print(f"\n{'='*70}")
    print("STRIKE_RANGE_PCT COVERAGE ANALYSIS")
    print("=" * 70)
    print("\nSTRIKE_RANGE_PCT | Capture Rate | Missed Days | Notes")
    print("-" * 70)

    test_values = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    results = []

    for pct in test_values:
        captured = 0
        missed_days = []

        for i, (timestamp, spot, dvol) in enumerate(rows):
            # Check if both put and call 5-delta are within range
            put_in_range = put_distances[i] <= pct
            call_in_range = call_distances[i] <= pct

            if put_in_range and call_in_range:
                captured += 1
            else:
                missed_days.append((timestamp[:10], dvol, put_distances[i], call_distances[i]))

        capture_rate = captured / len(rows)
        results.append((pct, capture_rate, len(rows) - captured))

        notes = ""
        if capture_rate < 0.90:
            notes = "< 90%"
        elif capture_rate < 0.95:
            notes = "< 95%"
        elif capture_rate >= 0.99:
            notes = ">= 99%"

        print(f"     {pct:.2f}       |    {capture_rate:.1%}     |     {len(rows)-captured:3d}     | {notes}")

    # Find optimal values
    print(f"\n{'='*70}")
    print("RECOMMENDATIONS")
    print("=" * 70)

    for target_rate, label in [(0.90, "90%"), (0.95, "95%"), (0.99, "99%")]:
        for pct, rate, _ in results:
            if rate >= target_rate:
                print(f"  {label} capture: STRIKE_RANGE_PCT >= {pct:.2f}")
                break

    # Percentile analysis
    print(f"\n{'='*70}")
    print("PERCENTILE ANALYSIS (max daily distance needed)")
    print("=" * 70)

    sorted_max = sorted(max_daily)
    for p in [90, 95, 99]:
        idx = int(len(sorted_max) * p / 100)
        val = sorted_max[idx]
        print(f"  {p}th percentile: {val:.2%}")

    # Show worst days
    print(f"\n{'='*70}")
    print("WORST 10 DAYS (highest distance needed)")
    print("=" * 70)

    combined = list(zip(rows, max_daily))
    combined.sort(key=lambda x: x[1], reverse=True)

    print("\nDate       | DVOL  | Max Distance | Put Dist | Call Dist")
    print("-" * 60)
    for (timestamp, spot, dvol), max_dist in combined[:10]:
        i = rows.index((timestamp, spot, dvol))
        print(f"{timestamp[:10]} | {dvol:5.1f} | {max_dist:11.2%} | {put_distances[i]:.2%}   | {call_distances[i]:.2%}")

    # Final recommendation
    print(f"\n{'='*70}")
    print("FINAL ANALYSIS")
    print("=" * 70)

    # Find the minimum value that achieves 95% capture
    optimal_95 = None
    for pct, rate, _ in results:
        if rate >= 0.95:
            optimal_95 = pct
            break

    optimal_99 = None
    for pct, rate, _ in results:
        if rate >= 0.99:
            optimal_99 = pct
            break

    print(f"""
Based on 999 days of historical ETH price/DVOL data (Black-Scholes estimates):

Current value: STRIKE_RANGE_PCT = 0.35
  - Capture rate: {results[1][1]:.1%}
  - Would miss {results[1][2]} days

Recommended value for 95% capture: STRIKE_RANGE_PCT = {optimal_95 or 'N/A'}
  - Provides buffer for high volatility periods

Recommended value for 99% capture: STRIKE_RANGE_PCT = {optimal_99 or 'N/A'}
  - Maximum safety margin

Trade-off consideration:
  - Wider range = more API calls to fetch option data
  - Narrower range = risk of missing valid trades during high IV

LIMITATION: These are Black-Scholes estimates, not actual option data.
Actual 5-delta strikes depend on Deribit's pricing and available strikes.
Consider adding a small buffer (e.g., +0.05) to the recommended values.
""")


if __name__ == "__main__":
    main()
