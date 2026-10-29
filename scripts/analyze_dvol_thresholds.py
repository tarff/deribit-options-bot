"""Analyze DVOL historical data to determine optimal emergency thresholds.

This script helps validate the DVOL emergency threshold (currently 100)
by analyzing historical DVOL distribution and frequency of threshold breaches.

Usage:
    python scripts/analyze_dvol_thresholds.py
    python scripts/analyze_dvol_thresholds.py --thresholds 80,100,120,130
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository


def analyze_dvol_distribution(repository: HistoricalDataRepository) -> dict:
    """Analyze DVOL distribution statistics.

    Returns:
        Dict with distribution stats.
    """
    data = repository.get_range()

    if not data:
        return {"error": "No historical data available"}

    dvol_values = [d.dvol for d in data]

    # Basic stats
    dvol_sorted = sorted(dvol_values)
    n = len(dvol_sorted)

    stats = {
        "count": n,
        "min": min(dvol_values),
        "max": max(dvol_values),
        "mean": sum(dvol_values) / n,
        "median": dvol_sorted[n // 2],
        "p75": dvol_sorted[int(n * 0.75)],
        "p90": dvol_sorted[int(n * 0.90)],
        "p95": dvol_sorted[int(n * 0.95)],
        "p99": dvol_sorted[int(n * 0.99)],
        "start_date": data[0].timestamp.date(),
        "end_date": data[-1].timestamp.date(),
    }

    return stats


def analyze_threshold_breaches(
    repository: HistoricalDataRepository,
    thresholds: list[float],
) -> dict[float, dict]:
    """Analyze breach frequency for different threshold levels.

    Args:
        repository: Data repository.
        thresholds: List of threshold values to analyze.

    Returns:
        Dict mapping threshold to breach statistics.
    """
    data = repository.get_range()

    if not data:
        return {}

    total_days = len(data)
    results = {}

    for threshold in thresholds:
        breaches = [d for d in data if d.dvol > threshold]
        breach_count = len(breaches)

        # Find consecutive breach periods
        periods = []
        current_period_start = None
        current_period_days = 0

        for d in data:
            if d.dvol > threshold:
                if current_period_start is None:
                    current_period_start = d.timestamp
                current_period_days += 1
            else:
                if current_period_start is not None:
                    periods.append({
                        "start": current_period_start,
                        "days": current_period_days,
                    })
                    current_period_start = None
                    current_period_days = 0

        # Don't forget last period
        if current_period_start is not None:
            periods.append({
                "start": current_period_start,
                "days": current_period_days,
            })

        results[threshold] = {
            "breach_days": breach_count,
            "breach_pct": 100 * breach_count / total_days,
            "breach_periods": len(periods),
            "avg_period_days": sum(p["days"] for p in periods) / len(periods) if periods else 0,
            "max_period_days": max(p["days"] for p in periods) if periods else 0,
            "periods": periods[:5],  # Show first 5 periods
        }

    return results


def main() -> int:
    """Run DVOL threshold analysis."""
    parser = argparse.ArgumentParser(
        description="Analyze DVOL thresholds for emergency manager"
    )
    parser.add_argument(
        "--db",
        default="data/trading.db",
        help="Database path (default: data/trading.db)",
    )
    parser.add_argument(
        "--thresholds",
        default="60,80,100,120,130",
        help="Comma-separated threshold values to analyze",
    )
    args = parser.parse_args()

    # Parse thresholds
    thresholds = [float(t.strip()) for t in args.thresholds.split(",")]

    # Check database exists
    if not Path(args.db).exists():
        print(f"Error: Database not found at {args.db}")
        print("Run 'python scripts/fetch_historical_data.py --start 2023-01-01' first")
        return 1

    # Initialize
    db = Database(args.db)
    db.initialize()
    repository = HistoricalDataRepository(db)

    # Check for data
    count = repository.count()
    if count == 0:
        print("No historical data available.")
        print("Run 'python scripts/fetch_historical_data.py --start 2023-01-01' first")
        return 1

    print("=" * 60)
    print("DVOL THRESHOLD ANALYSIS")
    print("=" * 60)

    # Distribution stats
    print("\n## DVOL Distribution\n")
    stats = analyze_dvol_distribution(repository)

    print(f"Data range: {stats['start_date']} to {stats['end_date']}")
    print(f"Total days: {stats['count']}")
    print(f"Min DVOL:   {stats['min']:.1f}")
    print(f"Max DVOL:   {stats['max']:.1f}")
    print(f"Mean DVOL:  {stats['mean']:.1f}")
    print(f"Median:     {stats['median']:.1f}")
    print(f"75th pct:   {stats['p75']:.1f}")
    print(f"90th pct:   {stats['p90']:.1f}")
    print(f"95th pct:   {stats['p95']:.1f}")
    print(f"99th pct:   {stats['p99']:.1f}")

    # Threshold analysis
    print("\n## Threshold Breach Analysis\n")
    breach_results = analyze_threshold_breaches(repository, thresholds)

    print(f"{'Threshold':>10} {'Days':>8} {'Pct':>8} {'Periods':>8} {'Avg Days':>10} {'Max Days':>10}")
    print("-" * 60)

    for threshold, result in sorted(breach_results.items()):
        print(
            f"{threshold:>10.0f} "
            f"{result['breach_days']:>8d} "
            f"{result['breach_pct']:>7.1f}% "
            f"{result['breach_periods']:>8d} "
            f"{result['avg_period_days']:>10.1f} "
            f"{result['max_period_days']:>10d}"
        )

    # Recommendations
    print("\n## Recommendations\n")

    # Find threshold that triggers ~1-5% of the time
    for threshold, result in sorted(breach_results.items()):
        if 1.0 <= result['breach_pct'] <= 5.0:
            print(f"DVOL {threshold:.0f} triggers {result['breach_pct']:.1f}% of days")
            print(f"  - {result['breach_periods']} separate periods")
            print(f"  - Average {result['avg_period_days']:.1f} consecutive days per period")
            print()

    print("\nCurrent setting: DVOL 100 (in EmergencyConfig)")
    current = breach_results.get(100.0, {})
    if current:
        print(f"  - Triggers {current['breach_pct']:.1f}% of days ({current['breach_days']} days)")
        print(f"  - {current['breach_periods']} separate breach periods")

    # Show recent high DVOL periods
    print("\n## Recent DVOL Spikes (>80)\n")
    high_dvol = breach_results.get(80.0, {}).get("periods", [])
    for period in high_dvol[-5:]:  # Last 5 periods
        print(f"  {period['start'].date()}: {period['days']} days above 80")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
