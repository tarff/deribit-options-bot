#!/usr/bin/env python
"""Analyze HIGH_IV_OVERPRICED regime thresholds for selling volatility.

This script specifically tests combinations of:
- IV Rank thresholds (when is IV "high"?)
- IV-RV spread thresholds (when is IV "overpriced"?)

The goal is to find when selling vol (short straddle/strangle) is profitable,
which requires IV to mean-revert down after entry.

Usage:
    python scripts/analyze_high_iv_overpriced.py
"""

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
    price: float
    dvol: float
    iv_rank: Optional[float] = None
    rv_7d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    # Forward changes for measuring mean reversion
    dvol_change_7d: Optional[float] = None
    dvol_change_14d: Optional[float] = None
    spread_change_7d: Optional[float] = None


def load_data(db_path: str = "data/trading.db") -> list[DailyData]:
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
            price=row[1],
            dvol=row[2],
        ))

    conn.close()
    return data


def calculate_rv(prices: list[float], periods_per_year: int = 365) -> Optional[float]:
    """Calculate annualized realized volatility."""
    if len(prices) < 2:
        return None
    arr = np.array(prices)
    log_returns = np.diff(np.log(arr))
    daily_vol = float(np.std(log_returns, ddof=1))
    return daily_vol * np.sqrt(periods_per_year) * 100


def calculate_iv_rank(current_dvol: float, historical_dvol: list[float]) -> Optional[float]:
    """Calculate IV Rank (percentile in 252-day range)."""
    if len(historical_dvol) < 2:
        return None
    iv_min = min(historical_dvol)
    iv_max = max(historical_dvol)
    if iv_max == iv_min:
        return 0.5
    return (current_dvol - iv_min) / (iv_max - iv_min)


def enrich_data(data: list[DailyData]) -> list[DailyData]:
    """Calculate derived metrics for each day."""
    prices = [d.price for d in data]
    dvols = [d.dvol for d in data]

    for i, day in enumerate(data):
        # IV Rank - 252 trading days lookback
        if i >= 252:
            historical_dvol = dvols[i-252:i]
            day.iv_rank = calculate_iv_rank(day.dvol, historical_dvol)

        # 7-day RV
        if i >= 7:
            day.rv_7d = calculate_rv(prices[i-7:i+1])

        # IV-RV spread
        if day.rv_7d is not None:
            day.iv_rv_spread = day.dvol - day.rv_7d

        # DVOL change over next 7 days (for mean reversion analysis)
        if i + 7 < len(data):
            day.dvol_change_7d = data[i+7].dvol - day.dvol

        # DVOL change over next 14 days
        if i + 14 < len(data):
            day.dvol_change_14d = data[i+14].dvol - day.dvol

        # IV-RV spread change (did spread compress?)
        if i + 7 < len(data) and day.iv_rv_spread is not None:
            future_rv = calculate_rv(prices[i:i+8])
            if future_rv is not None:
                future_spread = data[i+7].dvol - future_rv
                day.spread_change_7d = future_spread - day.iv_rv_spread

    return data


def analyze_regime_combination(
    data: list[DailyData],
    iv_rank_threshold: float,
    spread_threshold: float,
) -> dict:
    """Analyze outcomes when both IV Rank and spread thresholds are met.

    For selling vol to be profitable:
    - IV should decrease (dvol_change negative)
    - Spread should compress (spread_change negative)
    """
    qualifying_days = []

    for d in data:
        if d.iv_rank is None or d.iv_rv_spread is None:
            continue
        if d.dvol_change_7d is None:
            continue

        # Check if conditions met
        if d.iv_rank >= iv_rank_threshold and d.iv_rv_spread >= spread_threshold:
            qualifying_days.append(d)

    if not qualifying_days:
        return {
            "count": 0,
            "iv_rank_thresh": iv_rank_threshold,
            "spread_thresh": spread_threshold,
        }

    dvol_changes = [d.dvol_change_7d for d in qualifying_days]
    spread_changes = [d.spread_change_7d for d in qualifying_days if d.spread_change_7d is not None]

    # For selling vol: negative change = profitable
    dvol_decreased_pct = sum(1 for c in dvol_changes if c < 0) / len(dvol_changes) * 100

    return {
        "count": len(qualifying_days),
        "iv_rank_thresh": iv_rank_threshold,
        "spread_thresh": spread_threshold,
        "days_per_year": len(qualifying_days) / (len(data) / 365),
        "dvol_change_mean": float(np.mean(dvol_changes)),
        "dvol_change_median": float(np.median(dvol_changes)),
        "dvol_decreased_pct": dvol_decreased_pct,
        "spread_change_mean": float(np.mean(spread_changes)) if spread_changes else None,
    }


def main():
    print("=" * 80)
    print("HIGH_IV_OVERPRICED REGIME ANALYSIS")
    print("Finding optimal thresholds for selling volatility")
    print("=" * 80)

    # Load and enrich data
    data = load_data()
    print(f"\nLoaded {len(data)} days of data")
    print(f"Date range: {data[0].timestamp.date()} to {data[-1].timestamp.date()}")

    data = enrich_data(data)
    valid_data = [d for d in data if d.iv_rank is not None and d.iv_rv_spread is not None]
    print(f"Days with valid metrics: {len(valid_data)}")

    # ========== INDIVIDUAL METRIC ANALYSIS ==========
    print("\n" + "=" * 80)
    print("1. INDIVIDUAL METRIC DISTRIBUTIONS")
    print("=" * 80)

    iv_ranks = [d.iv_rank for d in valid_data]
    spreads = [d.iv_rv_spread for d in valid_data]

    print(f"\nIV Rank:")
    print(f"  Mean: {np.mean(iv_ranks):.1%}, Median: {np.median(iv_ranks):.1%}")
    print(f"  25th: {np.percentile(iv_ranks, 25):.1%}, 75th: {np.percentile(iv_ranks, 75):.1%}")

    print(f"\nIV-RV Spread:")
    print(f"  Mean: {np.mean(spreads):.1f}, Median: {np.median(spreads):.1f}")
    print(f"  25th: {np.percentile(spreads, 25):.1f}, 75th: {np.percentile(spreads, 75):.1f}")

    # ========== COMBINATION ANALYSIS ==========
    print("\n" + "=" * 80)
    print("2. COMBINATION ANALYSIS: IV Rank + Spread Thresholds")
    print("=" * 80)
    print("\nTesting when BOTH conditions are met (selling vol opportunity)")
    print("Success = DVOL decreased over next 7 days (mean reversion)")

    iv_rank_thresholds = [0.30, 0.40, 0.50, 0.60, 0.70]
    spread_thresholds = [5, 10, 15, 20]

    results = []

    for iv_thresh in iv_rank_thresholds:
        for spread_thresh in spread_thresholds:
            result = analyze_regime_combination(valid_data, iv_thresh, spread_thresh)
            if result["count"] > 0:
                results.append(result)

    # Sort by mean reversion success rate
    results.sort(key=lambda x: x.get("dvol_decreased_pct", 0), reverse=True)

    print(f"\n{'IV Rank':>10} {'Spread':>10} {'Days':>8} {'Days/Yr':>10} {'DVOL Down':>10} {'Mean Chg':>10}")
    print("-" * 70)

    for r in results:
        print(f"{r['iv_rank_thresh']:>9.0%} {r['spread_thresh']:>9.0f} {r['count']:>8} "
              f"{r.get('days_per_year', 0):>10.1f} {r.get('dvol_decreased_pct', 0):>9.1f}% "
              f"{r.get('dvol_change_mean', 0):>+9.1f}")

    # ========== BEST COMBINATIONS ==========
    print("\n" + "=" * 80)
    print("3. BEST COMBINATIONS (sorted by mean reversion success)")
    print("=" * 80)

    # Filter for meaningful sample sizes (at least 20 occurrences)
    significant = [r for r in results if r["count"] >= 20]
    significant.sort(key=lambda x: x.get("dvol_decreased_pct", 0), reverse=True)

    print("\nTop combinations with N >= 20:")
    for i, r in enumerate(significant[:5], 1):
        print(f"\n  {i}. IV Rank >= {r['iv_rank_thresh']:.0%} AND Spread >= {r['spread_thresh']}")
        print(f"     Occurrences: {r['count']} ({r.get('days_per_year', 0):.1f}/year)")
        print(f"     DVOL decreased: {r.get('dvol_decreased_pct', 0):.1f}% of the time")
        print(f"     Mean DVOL change: {r.get('dvol_change_mean', 0):+.1f} pts")

    # ========== SPREAD-ONLY ANALYSIS ==========
    print("\n" + "=" * 80)
    print("4. SPREAD-ONLY ANALYSIS (ignoring IV Rank)")
    print("=" * 80)
    print("\nTesting if IV-RV spread alone is a sufficient signal")

    for spread_thresh in [10, 15, 20, 25]:
        qualifying = [d for d in valid_data
                     if d.iv_rv_spread >= spread_thresh and d.dvol_change_7d is not None]
        if qualifying:
            changes = [d.dvol_change_7d for d in qualifying]
            decreased_pct = sum(1 for c in changes if c < 0) / len(changes) * 100
            print(f"\n  Spread >= {spread_thresh}:")
            print(f"    N={len(qualifying)} ({len(qualifying)/(len(valid_data)/365):.1f}/year)")
            print(f"    DVOL decreased: {decreased_pct:.1f}%")
            print(f"    Mean change: {np.mean(changes):+.1f}")

    # ========== RECOMMENDATION ==========
    print("\n" + "=" * 80)
    print("5. RECOMMENDATION")
    print("=" * 80)

    # Find best trade-off
    best = None
    for r in significant:
        if r.get("dvol_decreased_pct", 0) >= 55 and r.get("days_per_year", 0) >= 30:
            best = r
            break

    if best:
        print(f"""
Based on analysis of {len(valid_data)} days of data:

RECOMMENDED THRESHOLDS for HIGH_IV_OVERPRICED regime:
  - IV Rank threshold: {best['iv_rank_thresh']:.0%}
  - IV-RV Spread threshold: {best['spread_thresh']:.0f}

EXPECTED OUTCOMES:
  - Entry opportunities: ~{best.get('days_per_year', 0):.0f} days/year
  - Mean reversion success: {best.get('dvol_decreased_pct', 0):.1f}% (DVOL decreases)
  - Average DVOL change: {best.get('dvol_change_mean', 0):+.1f} points over 7 days

CURRENT vs RECOMMENDED:
  - Current IV Rank: 50% -> Recommended: {best['iv_rank_thresh']:.0%}
  - Current Spread: 15 -> Recommended: {best['spread_thresh']:.0f}
""")
    else:
        print("\nNo combination met the criteria (>55% success, >30 days/year)")
        print("Consider using spread-only threshold or adjusting criteria.")


if __name__ == "__main__":
    main()
