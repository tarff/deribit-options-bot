"""Analyze ETH DVOL distribution to determine appropriate regime thresholds.

Compares ETH DVOL distribution to BTC to find equivalent threshold values.
Uses percentile-based mapping to recommend ETH-specific thresholds.

Usage:
    python scripts/analyze_eth_dvol.py
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.data_fetcher import HistoricalDataFetcher
from src.data.deribit_client import DeribitClient


def calculate_percentiles(values: list[float]) -> dict[str, float]:
    """Calculate distribution statistics."""
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    return {
        "count": n,
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / n,
        "median": sorted_vals[n // 2],
        "p10": sorted_vals[int(n * 0.10)],
        "p25": sorted_vals[int(n * 0.25)],
        "p50": sorted_vals[int(n * 0.50)],
        "p75": sorted_vals[int(n * 0.75)],
        "p85": sorted_vals[int(n * 0.85)],
        "p90": sorted_vals[int(n * 0.90)],
        "p95": sorted_vals[int(n * 0.95)],
        "p99": sorted_vals[int(n * 0.99)],
    }


def find_percentile_of_value(values: list[float], target: float) -> float:
    """Find what percentile a given value represents."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v < target)
    return below / len(values)


def find_value_at_percentile(values: list[float], percentile: float) -> float:
    """Find the value at a given percentile."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * percentile)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def count_days_above(values: list[float], threshold: float) -> tuple[int, float]:
    """Count days above threshold and return count and percentage."""
    if not values:
        return 0, 0.0
    above = sum(1 for v in values if v > threshold)
    return above, 100 * above / len(values)


async def run(args: argparse.Namespace) -> int:
    """Run the analysis."""
    client = DeribitClient()

    try:
        # Fetch both BTC and ETH DVOL from the API for consistent data
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=args.days)

        print(f"Fetching DVOL from Deribit API ({args.days} days)...")
        fetcher = HistoricalDataFetcher(client)

        btc_bars = await fetcher.fetch_dvol_history(start_date, end_date, "BTC", 86400)
        btc_dvol = [bar.close for bar in btc_bars]

        eth_bars = await fetcher.fetch_dvol_history(start_date, end_date, "ETH", 86400)
        eth_dvol = [bar.close for bar in eth_bars]

        print(f"  BTC: {len(btc_dvol)} days")
        print(f"  ETH: {len(eth_dvol)} days")

        if not btc_dvol or not eth_dvol:
            print("Error: No DVOL data returned")
            return 1

        # Calculate statistics
        print("\n" + "=" * 70)
        print("  DVOL DISTRIBUTION COMPARISON")
        print("=" * 70)

        btc_stats = calculate_percentiles(btc_dvol)
        eth_stats = calculate_percentiles(eth_dvol)

        print(f"\n{'Statistic':<15} {'BTC':>12} {'ETH':>12} {'Diff':>12}")
        print("-" * 55)

        for key in ["min", "max", "mean", "median", "p75", "p85", "p90", "p95", "p99"]:
            btc_val = btc_stats.get(key, 0)
            eth_val = eth_stats.get(key, 0)
            diff = eth_val - btc_val
            print(f"{key:<15} {btc_val:>12.1f} {eth_val:>12.1f} {diff:>+12.1f}")

        # Analyze BTC thresholds
        print("\n" + "=" * 70)
        print("  BTC THRESHOLD ANALYSIS (Current Settings)")
        print("=" * 70)

        btc_thresholds = [60, 80]
        print(f"\n{'Threshold':<15} {'Days Above':>12} {'Pct':>10} {'Percentile':>12}")
        print("-" * 55)

        for thresh in btc_thresholds:
            days, pct = count_days_above(btc_dvol, thresh)
            percentile = find_percentile_of_value(btc_dvol, thresh)
            print(f"DVOL > {thresh:<8} {days:>12} {pct:>9.1f}% {percentile:>11.1%}")

        # Find equivalent ETH thresholds
        print("\n" + "=" * 70)
        print("  ETH EQUIVALENT THRESHOLDS (Percentile-Matched)")
        print("=" * 70)

        print("\nFinding ETH thresholds that match BTC's percentile behavior:")
        print(f"\n{'BTC Threshold':<15} {'BTC %ile':>10} {'ETH Equiv':>12} {'ETH Days Above':>15}")
        print("-" * 55)

        eth_recommendations = {}
        for thresh in btc_thresholds:
            btc_percentile = find_percentile_of_value(btc_dvol, thresh)
            eth_equiv = find_value_at_percentile(eth_dvol, btc_percentile)
            eth_days, eth_pct = count_days_above(eth_dvol, eth_equiv)

            regime = "HIGH_STRESS" if thresh == 60 else "EXTREME_FEAR"
            eth_recommendations[regime] = eth_equiv

            print(f"DVOL > {thresh:<8} {btc_percentile:>9.1%} {eth_equiv:>12.1f} {eth_days:>8} ({eth_pct:.1f}%)")

        # Verify: what happens with current BTC thresholds on ETH?
        print("\n" + "=" * 70)
        print("  ETH WITH CURRENT BTC THRESHOLDS (Problem)")
        print("=" * 70)

        print(f"\n{'Threshold':<15} {'ETH Days':>12} {'Pct':>10} {'Issue':>25}")
        print("-" * 65)

        for thresh in btc_thresholds:
            days, pct = count_days_above(eth_dvol, thresh)
            regime = "HIGH_STRESS" if thresh == 60 else "EXTREME_FEAR"
            issue = "Too frequent!" if pct > 30 else "OK" if pct < 20 else "High"
            print(f"DVOL > {thresh:<8} {days:>12} {pct:>9.1f}% {issue:>25}")

        # Summary recommendations
        print("\n" + "=" * 70)
        print("  RECOMMENDATIONS")
        print("=" * 70)

        print("\nFor ETH trading, use these regime thresholds:")
        print(f"  - dvol_reduce_threshold (HIGH_STRESS): {eth_recommendations['HIGH_STRESS']:.0f}")
        print(f"  - dvol_halt_threshold (EXTREME_FEAR):  {eth_recommendations['EXTREME_FEAR']:.0f}")

        print("\nThese values maintain the same percentile behavior as BTC thresholds,")
        print("meaning they'll trigger at the same frequency relative to each asset's")
        print("historical volatility distribution.")

        # Show regime distribution with recommended thresholds
        print("\n" + "=" * 70)
        print("  EXPECTED REGIME DISTRIBUTION WITH RECOMMENDATIONS")
        print("=" * 70)

        btc_neutral = sum(1 for v in btc_dvol if v <= 60)
        btc_stress = sum(1 for v in btc_dvol if 60 < v <= 80)
        btc_fear = sum(1 for v in btc_dvol if v > 80)

        eth_reduce = eth_recommendations['HIGH_STRESS']
        eth_halt = eth_recommendations['EXTREME_FEAR']
        eth_neutral = sum(1 for v in eth_dvol if v <= eth_reduce)
        eth_stress = sum(1 for v in eth_dvol if eth_reduce < v <= eth_halt)
        eth_fear = sum(1 for v in eth_dvol if v > eth_halt)

        print(f"\n{'Regime':<20} {'BTC (60/80)':>15} {'ETH (rec)':>15}")
        print("-" * 55)
        print(f"{'NEUTRAL/Other':<20} {100*btc_neutral/len(btc_dvol):>14.1f}% {100*eth_neutral/len(eth_dvol):>14.1f}%")
        print(f"{'HIGH_STRESS':<20} {100*btc_stress/len(btc_dvol):>14.1f}% {100*eth_stress/len(eth_dvol):>14.1f}%")
        print(f"{'EXTREME_FEAR':<20} {100*btc_fear/len(btc_dvol):>14.1f}% {100*eth_fear/len(eth_dvol):>14.1f}%")

        return 0

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await client.close()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze ETH DVOL for regime threshold calibration"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1000,
        help="Number of days of history to fetch (default: 1000)",
    )

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
