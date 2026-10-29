#!/usr/bin/env python
"""Analyze historical data to derive empirically-backed strategy thresholds.

This script analyzes:
1. IV Rank distribution and optimal entry thresholds
2. IV-RV spread distribution for vol arb
3. Forward return analysis to validate threshold choices

Usage:
    python scripts/analyze_strategy_thresholds.py --db data/trading.db
"""

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class DailyData:
    """Single day of market data."""
    timestamp: datetime
    btc_price: float
    dvol: float
    iv_rank: Optional[float] = None
    rv_7d: Optional[float] = None
    rv_30d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    fwd_return_7d: Optional[float] = None


def load_historical_data(db_path: str) -> list[DailyData]:
    """Load historical data from database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT timestamp, btc_price, dvol
        FROM historical_data
        WHERE dvol IS NOT NULL
        ORDER BY timestamp
    """)

    data = []
    for row in cursor.fetchall():
        data.append(DailyData(
            timestamp=datetime.fromisoformat(row[0]),
            btc_price=row[1],
            dvol=row[2],
        ))

    conn.close()
    return data


def calculate_rv(prices: list[float], periods_per_year: int = 365) -> Optional[float]:
    """Calculate annualized realized volatility from prices."""
    if len(prices) < 2:
        return None

    prices_arr = np.array(prices)
    log_returns = np.diff(np.log(prices_arr))
    daily_vol = float(np.std(log_returns, ddof=1))

    return daily_vol * np.sqrt(periods_per_year) * 100


def calculate_iv_rank(current_dvol: float, historical_dvol: list[float]) -> Optional[float]:
    """Calculate IV Rank (position in 52-week range)."""
    if len(historical_dvol) < 2:
        return None

    iv_min = min(historical_dvol)
    iv_max = max(historical_dvol)

    if iv_max == iv_min:
        return 0.5

    return (current_dvol - iv_min) / (iv_max - iv_min)


def enrich_data(data: list[DailyData]) -> list[DailyData]:
    """Calculate IV Rank, RV, and IV-RV spread for each day."""
    prices = [d.btc_price for d in data]
    dvols = [d.dvol for d in data]

    for i, day in enumerate(data):
        # IV Rank - 252 trading days lookback
        if i >= 252:
            historical_dvol = dvols[i-252:i]
            day.iv_rank = calculate_iv_rank(day.dvol, historical_dvol)

        # 7-day RV
        if i >= 7:
            day.rv_7d = calculate_rv(prices[i-7:i+1])

        # 30-day RV
        if i >= 30:
            day.rv_30d = calculate_rv(prices[i-30:i+1])

        # IV-RV spread (using 7-day RV)
        if day.rv_7d is not None:
            day.iv_rv_spread = day.dvol - day.rv_7d

        # 7-day forward return
        if i + 7 < len(data):
            day.fwd_return_7d = (data[i+7].btc_price - day.btc_price) / day.btc_price * 100

    return data


def analyze_distribution(values: list[float], name: str) -> dict:
    """Analyze distribution of values."""
    arr = np.array(values)

    percentiles = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]
    pct_values = {p: np.percentile(arr, p) for p in percentiles}

    return {
        "name": name,
        "count": len(values),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "percentiles": pct_values,
    }


def analyze_threshold_frequency(data: list[DailyData], thresholds: list[float], metric: str) -> dict:
    """Analyze how often we'd be above various thresholds."""
    results = {}

    for thresh in thresholds:
        if metric == "iv_rank":
            days_above = sum(1 for d in data if d.iv_rank is not None and d.iv_rank >= thresh)
            total_days = sum(1 for d in data if d.iv_rank is not None)
        elif metric == "iv_rv_spread":
            # For IV-RV spread, we look at days BELOW threshold (IV < RV = negative spread)
            days_above = sum(1 for d in data if d.iv_rv_spread is not None and d.iv_rv_spread <= thresh)
            total_days = sum(1 for d in data if d.iv_rv_spread is not None)
        else:
            continue

        pct = days_above / total_days * 100 if total_days > 0 else 0
        results[thresh] = {
            "days": days_above,
            "total": total_days,
            "pct": pct,
            "trades_per_year": days_above / (total_days / 365) if total_days > 0 else 0,
        }

    return results


def analyze_forward_returns(data: list[DailyData], threshold: float, metric: str) -> dict:
    """Analyze forward returns when threshold is met."""
    returns_above = []
    returns_below = []

    for d in data:
        if d.fwd_return_7d is None:
            continue

        if metric == "iv_rank" and d.iv_rank is not None:
            if d.iv_rank >= threshold:
                returns_above.append(d.fwd_return_7d)
            else:
                returns_below.append(d.fwd_return_7d)
        elif metric == "iv_rv_spread" and d.iv_rv_spread is not None:
            # Vol arb buys when IV < RV (negative spread)
            if d.iv_rv_spread <= threshold:
                returns_above.append(d.fwd_return_7d)
            else:
                returns_below.append(d.fwd_return_7d)

    def calc_stats(returns: list[float]) -> dict:
        if not returns:
            return {"count": 0}
        arr = np.array(returns)
        return {
            "count": len(returns),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "positive_pct": sum(1 for r in returns if r > 0) / len(returns) * 100,
            "median": float(np.median(arr)),
        }

    return {
        "above_threshold": calc_stats(returns_above),
        "below_threshold": calc_stats(returns_below),
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze strategy thresholds")
    parser.add_argument("--db", type=Path, default=Path("data/trading.db"))
    args = parser.parse_args()

    print("=" * 70)
    print("STRATEGY THRESHOLD ANALYSIS")
    print("=" * 70)

    # Load data
    print(f"\nLoading data from {args.db}...")
    data = load_historical_data(str(args.db))
    print(f"Loaded {len(data)} days of data")
    print(f"Date range: {data[0].timestamp.date()} to {data[-1].timestamp.date()}")

    # Enrich with calculated fields
    print("\nCalculating IV Rank, RV, and spreads...")
    data = enrich_data(data)

    # Filter to data with IV Rank (need 252 days warmup)
    data_with_ivr = [d for d in data if d.iv_rank is not None]
    print(f"Days with IV Rank calculated: {len(data_with_ivr)}")

    # ========== IV RANK ANALYSIS ==========
    print("\n" + "=" * 70)
    print("1. IV RANK ANALYSIS (for Wheel and Iron Condor entry)")
    print("=" * 70)

    iv_ranks = [d.iv_rank for d in data_with_ivr if d.iv_rank is not None]
    dist = analyze_distribution(iv_ranks, "IV Rank")

    print(f"\nIV Rank Distribution:")
    print(f"  Min: {dist['min']:.2%}  Max: {dist['max']:.2%}")
    print(f"  Mean: {dist['mean']:.2%}  Std: {dist['std']:.2%}")
    print(f"\n  Percentiles:")
    for p in [10, 25, 30, 40, 50, 60, 70, 75, 90]:
        print(f"    {p}th: {dist['percentiles'][p]:.2%}")

    # Frequency analysis for IV Rank
    print(f"\nThreshold Frequency (days above threshold / entry opportunities):")
    thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70]
    freq = analyze_threshold_frequency(data_with_ivr, thresholds, "iv_rank")

    print(f"  {'Threshold':<12} {'Days':<8} {'% of Days':<12} {'~Entries/Year':<15}")
    print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*15}")
    for thresh in thresholds:
        f = freq[thresh]
        print(f"  >= {thresh:.0%}       {f['days']:<8} {f['pct']:.1f}%        ~{f['trades_per_year']:.0f}")

    # Forward return analysis for select thresholds
    print(f"\n7-Day Forward Return Analysis:")
    for thresh in [0.30, 0.40, 0.50]:
        fwd = analyze_forward_returns(data_with_ivr, thresh, "iv_rank")
        above = fwd["above_threshold"]
        below = fwd["below_threshold"]

        print(f"\n  IV Rank >= {thresh:.0%}:")
        if above["count"] > 0:
            print(f"    N={above['count']}, Mean={above['mean']:+.2f}%, Median={above['median']:+.2f}%, Positive={above['positive_pct']:.1f}%")
        print(f"  IV Rank < {thresh:.0%}:")
        if below["count"] > 0:
            print(f"    N={below['count']}, Mean={below['mean']:+.2f}%, Median={below['median']:+.2f}%, Positive={below['positive_pct']:.1f}%")

    # ========== IV-RV SPREAD ANALYSIS ==========
    print("\n" + "=" * 70)
    print("2. IV-RV SPREAD ANALYSIS (for Vol Arb entry)")
    print("=" * 70)

    iv_rv_spreads = [d.iv_rv_spread for d in data_with_ivr if d.iv_rv_spread is not None]
    dist = analyze_distribution(iv_rv_spreads, "IV-RV Spread")

    print(f"\nIV-RV Spread Distribution (DVOL - 7d RV):")
    print(f"  Min: {dist['min']:.1f}  Max: {dist['max']:.1f}")
    print(f"  Mean: {dist['mean']:.1f}  Std: {dist['std']:.1f}")
    print(f"\n  Percentiles:")
    for p in [5, 10, 25, 50, 75, 90, 95]:
        print(f"    {p}th: {dist['percentiles'][p]:.1f}")

    # Frequency analysis for IV-RV spread
    print(f"\nThreshold Frequency (days with IV-RV spread <= threshold):")
    print(f"  (Vol Arb buys vol when IV < RV, i.e., negative spread)")
    thresholds = [-20, -15, -10, -5, 0, 5, 10]
    freq = analyze_threshold_frequency(data_with_ivr, thresholds, "iv_rv_spread")

    print(f"  {'Threshold':<12} {'Days':<8} {'% of Days':<12} {'~Entries/Year':<15}")
    print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*15}")
    for thresh in thresholds:
        f = freq[thresh]
        print(f"  <= {thresh:+.0f}       {f['days']:<8} {f['pct']:.1f}%        ~{f['trades_per_year']:.0f}")

    # Forward return analysis
    print(f"\n7-Day Forward Return Analysis (looking for mean reversion):")
    for thresh in [-10, -5, 0]:
        fwd = analyze_forward_returns(data_with_ivr, thresh, "iv_rv_spread")
        above = fwd["above_threshold"]

        print(f"\n  IV-RV Spread <= {thresh:+.0f} (IV underpriced by {abs(thresh)} pts):")
        if above["count"] > 0:
            print(f"    N={above['count']}, Mean={above['mean']:+.2f}%, Median={above['median']:+.2f}%, Positive={above['positive_pct']:.1f}%")

    # ========== DVOL ANALYSIS ==========
    print("\n" + "=" * 70)
    print("3. DVOL LEVEL ANALYSIS (for regime detection)")
    print("=" * 70)

    dvols = [d.dvol for d in data]
    dist = analyze_distribution(dvols, "DVOL")

    print(f"\nDVOL Distribution:")
    print(f"  Min: {dist['min']:.1f}  Max: {dist['max']:.1f}")
    print(f"  Mean: {dist['mean']:.1f}  Std: {dist['std']:.1f}")
    print(f"\n  Percentiles:")
    for p in [5, 10, 25, 50, 75, 90, 95]:
        print(f"    {p}th: {dist['percentiles'][p]:.1f}")

    # Days above DVOL thresholds
    print(f"\nDays above DVOL thresholds:")
    for thresh in [50, 60, 70, 80, 90, 100]:
        days_above = sum(1 for d in data if d.dvol >= thresh)
        pct = days_above / len(data) * 100
        print(f"  >= {thresh}: {days_above} days ({pct:.1f}%)")

    # ========== RECOMMENDATIONS ==========
    print("\n" + "=" * 70)
    print("4. RECOMMENDATIONS")
    print("=" * 70)

    print("""
Based on the analysis above, here are data-driven recommendations:

WHEEL STRATEGY (MIN_IV_RANK):
  - Current: 0.30 (30%)
  - At 30%: ~{wheel_30_freq:.0f} entry days/year
  - At 40%: ~{wheel_40_freq:.0f} entry days/year
  - RECOMMENDATION: {wheel_rec}

IRON CONDOR STRATEGY (MIN_IV_RANK):
  - Current: 0.50 (50%)
  - At 50%: ~{ic_50_freq:.0f} entry days/year
  - At 40%: ~{ic_40_freq:.0f} entry days/year
  - RECOMMENDATION: {ic_rec}

VOL ARB STRATEGY (iv_rv_threshold_buy):
  - Current: -10.0 (buy when IV < RV by 10 pts)
  - At -10: ~{va_10_freq:.0f} entry days/year
  - At -5:  ~{va_5_freq:.0f} entry days/year
  - RECOMMENDATION: {va_rec}

DVOL THRESHOLDS:
  - DVOL reduce threshold (60): {dvol_60} days ({dvol_60_pct:.1f}%)
  - DVOL halt threshold (80): {dvol_80} days ({dvol_80_pct:.1f}%)
  - RECOMMENDATION: {dvol_rec}
""".format(
        wheel_30_freq=freq_iv[0.30]["trades_per_year"] if 0.30 in freq_iv else 0,
        wheel_40_freq=freq_iv[0.40]["trades_per_year"] if 0.40 in freq_iv else 0,
        wheel_rec="Consider 40% for more selective entries" if freq_iv.get(0.30, {}).get("trades_per_year", 0) > 200 else "30% is reasonable",
        ic_50_freq=freq_iv[0.50]["trades_per_year"] if 0.50 in freq_iv else 0,
        ic_40_freq=freq_iv[0.40]["trades_per_year"] if 0.40 in freq_iv else 0,
        ic_rec="50% provides ~{:.0f} opportunities/year".format(freq_iv.get(0.50, {}).get("trades_per_year", 0)),
        va_10_freq=freq_ivrv.get(-10, {}).get("trades_per_year", 0),
        va_5_freq=freq_ivrv.get(-5, {}).get("trades_per_year", 0),
        va_rec="Current -10 threshold is selective ({:.0f} days/year)".format(freq_ivrv.get(-10, {}).get("trades_per_year", 0)),
        dvol_60=sum(1 for d in data if d.dvol >= 60),
        dvol_60_pct=sum(1 for d in data if d.dvol >= 60) / len(data) * 100,
        dvol_80=sum(1 for d in data if d.dvol >= 80),
        dvol_80_pct=sum(1 for d in data if d.dvol >= 80) / len(data) * 100,
        dvol_rec="Current thresholds are reasonable based on historical distribution",
    ))


# Store for recommendations section
freq_iv = {}
freq_ivrv = {}

if __name__ == "__main__":
    # Pre-calculate frequencies for recommendations
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Load and process
    args_db = Path("data/trading.db")
    if len(sys.argv) > 1 and sys.argv[1] == "--db":
        args_db = Path(sys.argv[2])

    data = load_historical_data(str(args_db))
    data = enrich_data(data)
    data_with_ivr = [d for d in data if d.iv_rank is not None]

    # Calculate frequencies before main
    thresholds_iv = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70]
    freq_iv = analyze_threshold_frequency(data_with_ivr, thresholds_iv, "iv_rank")

    thresholds_ivrv = [-20, -15, -10, -5, 0, 5, 10]
    freq_ivrv = analyze_threshold_frequency(data_with_ivr, thresholds_ivrv, "iv_rv_spread")

    main()
