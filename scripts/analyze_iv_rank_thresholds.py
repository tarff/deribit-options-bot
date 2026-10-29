#!/usr/bin/env python
"""Analyze IV Rank thresholds for premium selling and vol buying strategies.

This script analyzes:
1. WHEEL/IRON CONDOR: When to sell premium (need IV to decrease after entry)
2. LOW_IV_UNDERPRICED: When to buy vol (need IV to increase after entry)

Usage:
    python scripts/analyze_iv_rank_thresholds.py
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
    # Forward changes
    dvol_change_7d: Optional[float] = None
    dvol_change_14d: Optional[float] = None
    price_change_7d_pct: Optional[float] = None


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

        # DVOL change over next 7 days
        if i + 7 < len(data):
            day.dvol_change_7d = data[i+7].dvol - day.dvol

        # DVOL change over next 14 days
        if i + 14 < len(data):
            day.dvol_change_14d = data[i+14].dvol - day.dvol

        # Price change over next 7 days (for premium selling - want low movement)
        if i + 7 < len(data):
            day.price_change_7d_pct = abs(data[i+7].price - day.price) / day.price * 100

    return data


def analyze_premium_selling(data: list[DailyData], iv_rank_threshold: float) -> dict:
    """Analyze premium selling profitability at given IV Rank threshold.

    For premium selling (Wheel, Iron Condor) to be profitable:
    - IV should decrease (theta decay captured)
    - Price should stay range-bound (no big moves)
    """
    qualifying = [d for d in data
                  if d.iv_rank is not None
                  and d.iv_rank >= iv_rank_threshold
                  and d.dvol_change_7d is not None
                  and d.price_change_7d_pct is not None]

    if not qualifying:
        return {"count": 0, "threshold": iv_rank_threshold}

    dvol_changes = [d.dvol_change_7d for d in qualifying]
    price_moves = [d.price_change_7d_pct for d in qualifying]

    # Premium selling wins when IV drops AND price stays calm
    dvol_decreased_pct = sum(1 for c in dvol_changes if c < 0) / len(dvol_changes) * 100
    price_calm_pct = sum(1 for p in price_moves if p < 5) / len(price_moves) * 100  # <5% move

    return {
        "threshold": iv_rank_threshold,
        "count": len(qualifying),
        "days_per_year": len(qualifying) / (len(data) / 365),
        "dvol_decreased_pct": dvol_decreased_pct,
        "dvol_change_mean": float(np.mean(dvol_changes)),
        "price_move_mean": float(np.mean(price_moves)),
        "price_calm_pct": price_calm_pct,
        # Combined score: IV drops AND price calm
        "combined_win_pct": sum(1 for i, d in enumerate(qualifying)
                                if dvol_changes[i] < 0 and price_moves[i] < 5) / len(qualifying) * 100,
    }


def analyze_vol_buying(data: list[DailyData], iv_rank_threshold: float, spread_threshold: float) -> dict:
    """Analyze vol buying profitability (gamma scalping, long straddles).

    For vol buying to be profitable:
    - IV should increase (vega profit)
    - OR price should move significantly (gamma profit)
    """
    qualifying = [d for d in data
                  if d.iv_rank is not None
                  and d.iv_rv_spread is not None
                  and d.iv_rank <= iv_rank_threshold
                  and d.iv_rv_spread <= spread_threshold
                  and d.dvol_change_7d is not None
                  and d.price_change_7d_pct is not None]

    if not qualifying:
        return {"count": 0, "iv_rank_thresh": iv_rank_threshold, "spread_thresh": spread_threshold}

    dvol_changes = [d.dvol_change_7d for d in qualifying]
    price_moves = [d.price_change_7d_pct for d in qualifying]

    # Vol buying wins when IV increases OR price moves big
    dvol_increased_pct = sum(1 for c in dvol_changes if c > 0) / len(dvol_changes) * 100
    price_moved_pct = sum(1 for p in price_moves if p > 5) / len(price_moves) * 100

    return {
        "iv_rank_thresh": iv_rank_threshold,
        "spread_thresh": spread_threshold,
        "count": len(qualifying),
        "days_per_year": len(qualifying) / (len(data) / 365),
        "dvol_increased_pct": dvol_increased_pct,
        "dvol_change_mean": float(np.mean(dvol_changes)),
        "price_move_mean": float(np.mean(price_moves)),
        "price_moved_pct": price_moved_pct,
        # Combined: IV up OR big price move
        "combined_win_pct": sum(1 for i, d in enumerate(qualifying)
                                if dvol_changes[i] > 2 or price_moves[i] > 5) / len(qualifying) * 100,
    }


def main():
    print("=" * 80)
    print("IV RANK THRESHOLD ANALYSIS")
    print("For Wheel, Iron Condor, and Gamma Scalping strategies")
    print("=" * 80)

    # Load and enrich data
    data = load_data()
    print(f"\nLoaded {len(data)} days of data")
    print(f"Date range: {data[0].timestamp.date()} to {data[-1].timestamp.date()}")

    data = enrich_data(data)
    valid_data = [d for d in data if d.iv_rank is not None]
    print(f"Days with valid IV Rank: {len(valid_data)}")

    # ========== PREMIUM SELLING ANALYSIS ==========
    print("\n" + "=" * 80)
    print("1. PREMIUM SELLING ANALYSIS (Wheel, Iron Condor)")
    print("=" * 80)
    print("\nPremium selling profits when: IV decreases AND price stays calm (<5% move)")
    print("Testing minimum IV Rank thresholds for entry...")

    thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]

    print(f"\n{'IV Rank >=':>12} {'Days':>8} {'Days/Yr':>10} {'IV Down%':>10} {'Calm%':>10} {'Win%':>10}")
    print("-" * 70)

    results = []
    for thresh in thresholds:
        r = analyze_premium_selling(valid_data, thresh)
        results.append(r)
        if r["count"] > 0:
            print(f"{thresh:>11.0%} {r['count']:>8} {r['days_per_year']:>10.1f} "
                  f"{r['dvol_decreased_pct']:>9.1f}% {r['price_calm_pct']:>9.1f}% "
                  f"{r['combined_win_pct']:>9.1f}%")

    # Find best threshold for each strategy
    print("\n" + "-" * 70)
    print("ANALYSIS:")

    # Wheel - needs more opportunities, can tolerate lower win rate
    wheel_candidates = [r for r in results if r["count"] >= 50 and r.get("combined_win_pct", 0) >= 35]
    if wheel_candidates:
        # Pick one with most opportunities above 35% win rate
        wheel_best = max(wheel_candidates, key=lambda x: x["days_per_year"])
        print(f"\nWHEEL (current: 30%):")
        print(f"  Best threshold: {wheel_best['threshold']:.0%}")
        print(f"  Opportunities: {wheel_best['days_per_year']:.0f}/year")
        print(f"  Combined win rate: {wheel_best['combined_win_pct']:.1f}%")

    # Iron Condor - needs higher win rate (defined risk)
    ic_candidates = [r for r in results if r["count"] >= 30 and r.get("combined_win_pct", 0) >= 40]
    if ic_candidates:
        # Pick one with highest win rate
        ic_best = max(ic_candidates, key=lambda x: x.get("combined_win_pct", 0))
        print(f"\nIRON CONDOR (current: 50%):")
        print(f"  Best threshold: {ic_best['threshold']:.0%}")
        print(f"  Opportunities: {ic_best['days_per_year']:.0f}/year")
        print(f"  Combined win rate: {ic_best['combined_win_pct']:.1f}%")

    # ========== VOL BUYING ANALYSIS ==========
    print("\n" + "=" * 80)
    print("2. VOL BUYING ANALYSIS (Gamma Scalping, Long Straddles)")
    print("=" * 80)
    print("\nVol buying profits when: IV increases OR price moves big (>5%)")
    print("Testing IV Rank + Spread combinations for LOW_IV_UNDERPRICED regime...")

    iv_thresholds = [0.20, 0.25, 0.30, 0.35, 0.40]
    spread_thresholds = [-15, -10, -5, 0]

    print(f"\n{'IV Rank <=':>12} {'Spread <=':>12} {'Days':>8} {'Days/Yr':>10} {'IV Up%':>10} {'Move%':>10} {'Win%':>10}")
    print("-" * 85)

    vol_results = []
    for iv_thresh in iv_thresholds:
        for spread_thresh in spread_thresholds:
            r = analyze_vol_buying(valid_data, iv_thresh, spread_thresh)
            vol_results.append(r)
            if r["count"] > 0:
                print(f"{iv_thresh:>11.0%} {spread_thresh:>+11.0f} {r['count']:>8} "
                      f"{r['days_per_year']:>10.1f} {r['dvol_increased_pct']:>9.1f}% "
                      f"{r['price_moved_pct']:>9.1f}% {r['combined_win_pct']:>9.1f}%")

    # Find best for gamma scalping
    print("\n" + "-" * 85)
    print("ANALYSIS:")

    gamma_candidates = [r for r in vol_results if r["count"] >= 20 and r.get("combined_win_pct", 0) >= 40]
    if gamma_candidates:
        gamma_best = max(gamma_candidates, key=lambda x: x.get("combined_win_pct", 0))
        print(f"\nLOW_IV_UNDERPRICED / GAMMA SCALP (current: IV Rank < 30%, Spread < -10):")
        print(f"  Best thresholds: IV Rank <= {gamma_best['iv_rank_thresh']:.0%}, Spread <= {gamma_best['spread_thresh']:.0f}")
        print(f"  Opportunities: {gamma_best['days_per_year']:.0f}/year")
        print(f"  Combined win rate: {gamma_best['combined_win_pct']:.1f}%")

    # ========== SUMMARY ==========
    print("\n" + "=" * 80)
    print("3. RECOMMENDATIONS SUMMARY")
    print("=" * 80)

    # Find best thresholds
    best_wheel = None
    best_ic = None
    best_gamma = None

    for r in results:
        if r["count"] >= 50 and r.get("combined_win_pct", 0) >= 35:
            if best_wheel is None or r["days_per_year"] > best_wheel["days_per_year"]:
                best_wheel = r
        if r["count"] >= 30 and r.get("combined_win_pct", 0) >= 40:
            if best_ic is None or r.get("combined_win_pct", 0) > best_ic.get("combined_win_pct", 0):
                best_ic = r

    for r in vol_results:
        if r["count"] >= 20 and r.get("combined_win_pct", 0) >= 40:
            if best_gamma is None or r.get("combined_win_pct", 0) > best_gamma.get("combined_win_pct", 0):
                best_gamma = r

    print("\nCURRENT vs RECOMMENDED:\n")

    if best_wheel:
        print(f"WHEEL STRATEGY (min_iv_rank):")
        print(f"  Current:     30%")
        print(f"  Recommended: {best_wheel['threshold']:.0%}")
        print(f"  Rationale:   {best_wheel['days_per_year']:.0f}/yr opportunities, {best_wheel['combined_win_pct']:.1f}% win rate")
    else:
        print("WHEEL: Insufficient data for recommendation")

    if best_ic:
        print(f"\nIRON CONDOR (MIN_IV_RANK):")
        print(f"  Current:     50%")
        print(f"  Recommended: {best_ic['threshold']:.0%}")
        print(f"  Rationale:   {best_ic['days_per_year']:.0f}/yr opportunities, {best_ic['combined_win_pct']:.1f}% win rate")
    else:
        print("\nIRON CONDOR: Insufficient data for recommendation")

    if best_gamma:
        print(f"\nLOW_IV_UNDERPRICED REGIME (for gamma scalp):")
        print(f"  Current:     IV Rank < 30%, Spread < -10")
        print(f"  Recommended: IV Rank <= {best_gamma['iv_rank_thresh']:.0%}, Spread <= {best_gamma['spread_thresh']:.0f}")
        print(f"  Rationale:   {best_gamma['days_per_year']:.0f}/yr opportunities, {best_gamma['combined_win_pct']:.1f}% win rate")
    else:
        print("\nLOW_IV_UNDERPRICED: Insufficient data for recommendation")


if __name__ == "__main__":
    main()
