#!/usr/bin/env python
"""Calibrate optimal DTE range for Iron Condor strategy on ETH.

This script:
1. Uses historical ETH price/DVOL data
2. Simulates Iron Condor trades at various DTEs
3. Accounts for bid-ask spreads (realistic execution costs)
4. Calculates win rates, returns, and Sharpe ratios
5. Recommends optimal DTE range

Iron Condor Structure:
- Sell OTM put (short delta, e.g., -0.15)
- Buy further OTM put (wing, e.g., -0.05)
- Sell OTM call (short delta, e.g., +0.15)
- Buy further OTM call (wing, e.g., +0.05)

Win Conditions:
- Price stays between short strikes until expiry
- Or 50% profit target hit (spread value decays to 50% of entry)

Usage:
    python scripts/calibrate_iron_condor_dte.py
"""

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import numpy as np
from scipy.stats import norm

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class IronCondorResult:
    """Result of a simulated Iron Condor trade."""
    entry_date: datetime
    exit_date: datetime
    dte: int
    entry_price: float  # Underlying price at entry
    exit_price: float   # Underlying price at exit
    short_put_strike: float
    short_call_strike: float
    long_put_strike: float
    long_call_strike: float
    net_credit: float   # Premium received (as fraction of underlying)
    max_loss: float     # Maximum possible loss
    pnl: float          # Final P&L (as fraction of underlying)
    win: bool           # True if profitable
    exit_reason: str    # 'profit_target', 'expiry_win', 'breached_put', 'breached_call'


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate Black-Scholes put price as fraction of spot."""
    if T <= 0:
        return max(K - S, 0) / S
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put_price / S


def black_scholes_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate Black-Scholes call price as fraction of spot."""
    if T <= 0:
        return max(S - K, 0) / S
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    call_price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return call_price / S


def delta_to_strike(spot: float, delta: float, dte: int, iv: float, option_type: str) -> float:
    """Convert delta to strike price using Black-Scholes.

    Args:
        spot: Current spot price
        delta: Target delta (negative for puts, positive for calls)
        dte: Days to expiry
        iv: Implied volatility (as percentage, e.g., 60 for 60%)
        option_type: 'put' or 'call'

    Returns:
        Strike price corresponding to that delta
    """
    T = dte / 365
    sigma = iv / 100
    r = 0.0  # Crypto has no risk-free rate

    if option_type == 'put':
        # For put, delta = -N(-d1), so N(-d1) = |delta|
        target_nd1 = abs(delta)
        neg_d1 = norm.ppf(target_nd1)
        d1 = -neg_d1
    else:
        # For call, delta = N(d1)
        d1 = norm.ppf(delta)

    # Solve for K from d1 formula
    exponent = d1 * sigma * np.sqrt(T) - (r + 0.5 * sigma**2) * T
    K = spot / np.exp(exponent)

    return K


def load_data(db_path: str = "data/trading.db") -> list[dict]:
    """Load historical ETH data from database."""
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
        data.append({
            "timestamp": datetime.fromisoformat(row[0]),
            "price": row[1],
            "dvol": row[2],
        })

    conn.close()
    return data


def calculate_iv_rank(data: list[dict], idx: int, lookback: int = 252) -> Optional[float]:
    """Calculate IV rank at given index."""
    if idx < lookback:
        return None

    current_iv = data[idx]["dvol"]
    historical_ivs = [data[i]["dvol"] for i in range(idx - lookback, idx)]

    iv_min = min(historical_ivs)
    iv_max = max(historical_ivs)

    if iv_max == iv_min:
        return 0.5

    return (current_iv - iv_min) / (iv_max - iv_min)


def simulate_iron_condor(
    data: list[dict],
    entry_idx: int,
    dte: int,
    short_delta: float = 0.15,
    wing_delta: float = 0.05,
    profit_target: float = 0.50,
    bid_ask_spread_pct: float = 0.03,  # 3% round-trip spread cost per leg
) -> Optional[IronCondorResult]:
    """Simulate a single Iron Condor trade.

    Args:
        data: Historical price/vol data
        entry_idx: Index in data to enter trade
        dte: Days to expiry
        short_delta: Delta for short strikes (e.g., 0.15 for 15-delta)
        wing_delta: Delta for wing strikes (e.g., 0.05 for 5-delta)
        profit_target: Close at this fraction of max profit (e.g., 0.50)
        bid_ask_spread_pct: Bid-ask spread cost as fraction (per leg)

    Returns:
        IronCondorResult or None if not enough data
    """
    if entry_idx + dte >= len(data):
        return None

    entry = data[entry_idx]
    entry_price = entry["price"]
    entry_iv = entry["dvol"]
    entry_date = entry["timestamp"]

    # Calculate strikes from deltas
    short_put_strike = delta_to_strike(entry_price, -short_delta, dte, entry_iv, 'put')
    long_put_strike = delta_to_strike(entry_price, -wing_delta, dte, entry_iv, 'put')
    short_call_strike = delta_to_strike(entry_price, short_delta, dte, entry_iv, 'call')
    long_call_strike = delta_to_strike(entry_price, wing_delta, dte, entry_iv, 'call')

    # Calculate option prices using Black-Scholes
    T = dte / 365
    sigma = entry_iv / 100

    short_put_price = black_scholes_put(entry_price, short_put_strike, T, 0, sigma)
    long_put_price = black_scholes_put(entry_price, long_put_strike, T, 0, sigma)
    short_call_price = black_scholes_call(entry_price, short_call_strike, T, 0, sigma)
    long_call_price = black_scholes_call(entry_price, long_call_strike, T, 0, sigma)

    # Net credit = (sell short put + sell short call) - (buy long put + buy long call)
    gross_credit = (short_put_price + short_call_price) - (long_put_price + long_call_price)

    # Apply bid-ask spread cost (4 legs, entry = worse prices)
    spread_cost = 4 * bid_ask_spread_pct * gross_credit
    net_credit = gross_credit - spread_cost

    if net_credit <= 0:
        return None

    # Max loss = width of wider spread - net credit
    put_spread_width = (short_put_strike - long_put_strike) / entry_price
    call_spread_width = (long_call_strike - short_call_strike) / entry_price
    max_spread_width = max(put_spread_width, call_spread_width)
    max_loss = max_spread_width - net_credit

    # Simulate forward through time
    exit_reason = None
    exit_idx = entry_idx

    for i in range(1, dte + 1):
        if entry_idx + i >= len(data):
            break

        current = data[entry_idx + i]
        current_price = current["price"]
        current_iv = current["dvol"]
        days_remaining = dte - i

        # Check if breached (price outside short strikes)
        if current_price < short_put_strike:
            exit_reason = "breached_put"
            exit_idx = entry_idx + i
            break
        if current_price > short_call_strike:
            exit_reason = "breached_call"
            exit_idx = entry_idx + i
            break

        # Calculate current spread value
        if days_remaining > 0:
            T_remaining = days_remaining / 365
            current_sigma = current_iv / 100

            curr_short_put = black_scholes_put(current_price, short_put_strike, T_remaining, 0, current_sigma)
            curr_long_put = black_scholes_put(current_price, long_put_strike, T_remaining, 0, current_sigma)
            curr_short_call = black_scholes_call(current_price, short_call_strike, T_remaining, 0, current_sigma)
            curr_long_call = black_scholes_call(current_price, long_call_strike, T_remaining, 0, current_sigma)

            current_value = (curr_short_put + curr_short_call) - (curr_long_put + curr_long_call)
        else:
            # At expiry - calculate intrinsic values
            intrinsic_short_put = max(short_put_strike - current_price, 0) / current_price
            intrinsic_long_put = max(long_put_strike - current_price, 0) / current_price
            intrinsic_short_call = max(current_price - short_call_strike, 0) / current_price
            intrinsic_long_call = max(current_price - long_call_strike, 0) / current_price

            current_value = (intrinsic_short_put + intrinsic_short_call) - (intrinsic_long_put + intrinsic_long_call)

        # Check profit target (value decayed enough)
        profit_captured = gross_credit - current_value
        if profit_captured >= gross_credit * profit_target:
            exit_reason = "profit_target"
            exit_idx = entry_idx + i
            break

        exit_idx = entry_idx + i

    # If no exit reason, check expiry
    if exit_reason is None:
        exit_data = data[exit_idx]
        exit_price = exit_data["price"]

        if short_put_strike <= exit_price <= short_call_strike:
            exit_reason = "expiry_win"
        elif exit_price < short_put_strike:
            exit_reason = "breached_put"
        else:
            exit_reason = "breached_call"

    exit_data = data[exit_idx]
    exit_price = exit_data["price"]
    exit_date = exit_data["timestamp"]

    # Calculate P&L
    if exit_reason == "profit_target":
        # Account for exit spread costs
        exit_spread_cost = 4 * bid_ask_spread_pct * gross_credit * 0.5  # Smaller value at exit
        pnl = net_credit * profit_target - exit_spread_cost
    elif exit_reason == "expiry_win":
        pnl = net_credit  # Kept full premium
    elif exit_reason == "breached_put":
        # Loss on put spread (capped at spread width)
        intrinsic_loss = min((short_put_strike - exit_price) / entry_price, put_spread_width)
        pnl = net_credit - intrinsic_loss
    elif exit_reason == "breached_call":
        # Loss on call spread (capped at spread width)
        intrinsic_loss = min((exit_price - short_call_strike) / entry_price, call_spread_width)
        pnl = net_credit - intrinsic_loss
    else:
        pnl = 0

    win = pnl > 0

    return IronCondorResult(
        entry_date=entry_date,
        exit_date=exit_date,
        dte=dte,
        entry_price=entry_price,
        exit_price=exit_price,
        short_put_strike=short_put_strike,
        short_call_strike=short_call_strike,
        long_put_strike=long_put_strike,
        long_call_strike=long_call_strike,
        net_credit=net_credit,
        max_loss=max_loss,
        pnl=pnl,
        win=win,
        exit_reason=exit_reason,
    )


def run_backtest(
    data: list[dict],
    dte: int,
    min_iv_rank: float = 0.60,  # Only enter when IV Rank >= 60%
    min_gap_days: int = 7,  # Minimum days between trades
) -> list[IronCondorResult]:
    """Run backtest for a specific DTE.

    Args:
        data: Historical data
        dte: Days to expiry
        min_iv_rank: Minimum IV rank for entry (calibrated threshold)
        min_gap_days: Minimum days between trade entries

    Returns:
        List of trade results
    """
    results = []
    last_entry_idx = -min_gap_days

    # Need 252 days for IV rank calculation
    start_idx = 252

    for i in range(start_idx, len(data) - dte):
        # Enforce minimum gap
        if i - last_entry_idx < min_gap_days:
            continue

        # Check IV rank threshold
        iv_rank = calculate_iv_rank(data, i)
        if iv_rank is None or iv_rank < min_iv_rank:
            continue

        result = simulate_iron_condor(data, i, dte)
        if result is not None:
            results.append(result)
            last_entry_idx = i

    return results


def analyze_results(results: list[IronCondorResult]) -> dict:
    """Analyze backtest results."""
    if not results:
        return {"count": 0}

    wins = sum(1 for r in results if r.win)
    pnls = [r.pnl for r in results]

    win_rate = wins / len(results)
    avg_pnl = np.mean(pnls)
    total_pnl = sum(pnls)

    # Sharpe ratio (annualized)
    if np.std(pnls) > 0 and len(results) > 1:
        # Estimate trades per year based on data
        days_span = (results[-1].entry_date - results[0].entry_date).days
        if days_span > 0:
            trades_per_year = len(results) * 365 / days_span
        else:
            trades_per_year = 52
        sharpe = (avg_pnl / np.std(pnls)) * np.sqrt(min(trades_per_year, 52))
    else:
        sharpe = 0

    # Profit factor
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Exit reason breakdown
    exit_reasons = {}
    for r in results:
        exit_reasons[r.exit_reason] = exit_reasons.get(r.exit_reason, 0) + 1

    # Average credit and max loss
    avg_credit = np.mean([r.net_credit for r in results])
    avg_max_loss = np.mean([r.max_loss for r in results])

    return {
        "count": len(results),
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "exit_reasons": exit_reasons,
        "avg_credit": avg_credit,
        "avg_max_loss": avg_max_loss,
    }


def main():
    print("=" * 70)
    print("IRON CONDOR DTE CALIBRATION FOR ETH")
    print("=" * 70)

    # Load data
    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")
    print(f"Date range: {data[0]['timestamp'].date()} to {data[-1]['timestamp'].date()}")

    # Test DTE values - include Deribit's typical expiry cycles
    # Weekly: ~7, 14, 21 days
    # Monthly: ~25-30, 45-60 days
    # Quarterly: ~53, 81 days
    dtes = [14, 21, 25, 28, 30, 35, 42, 45, 53, 60]

    print(f"\nTesting {len(dtes)} DTE values with IV Rank >= 60% filter")
    print("Short delta: 15%, Wing delta: 5%, Bid-ask spread: 3%/leg")

    # Run backtests
    all_results = {}

    for dte in dtes:
        results = run_backtest(data, dte)
        analysis = analyze_results(results)
        all_results[dte] = analysis

        if analysis["count"] > 0:
            print(f"  DTE {dte:2d}: {analysis['count']:3d} trades, "
                  f"Win {analysis['win_rate']:.1%}, "
                  f"Sharpe {analysis['sharpe']:.2f}, "
                  f"PF {analysis['profit_factor']:.2f}")

    # Filter to combinations with enough trades
    valid = {k: v for k, v in all_results.items() if v.get("count", 0) >= 5}

    if not valid:
        print("\nNot enough trades for analysis")
        print("This may indicate IV Rank >= 60% occurs rarely in the data")
        return 1

    # Find best by different metrics
    print("\n" + "=" * 70)
    print("RESULTS RANKED BY SHARPE RATIO")
    print("=" * 70)

    print(f"\n{'DTE':>6} {'Trades':>8} {'Win%':>8} {'AvgPnL':>10} {'Sharpe':>8} {'PF':>8} {'Credit':>10}")
    print("-" * 70)

    sorted_results = sorted(valid.items(), key=lambda x: x[1].get("sharpe", 0), reverse=True)

    for dte, stats in sorted_results:
        pf = stats['profit_factor']
        pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
        print(f"{dte:>6} {stats['count']:>8} {stats['win_rate']:>7.1%} "
              f"{stats['avg_pnl']:>9.4f} {stats['sharpe']:>8.2f} "
              f"{pf_str:>8} {stats['avg_credit']:>9.4f}")

    # Best metrics
    best_sharpe = max(valid.items(), key=lambda x: x[1].get("sharpe", 0))
    best_wr = max(valid.items(), key=lambda x: x[1].get("win_rate", 0))
    best_pf = max(valid.items(), key=lambda x: x[1].get("profit_factor", 0)
                  if x[1].get("profit_factor", 0) != float('inf') else 0)

    print("\n" + "=" * 70)
    print("OPTIMAL DTE RECOMMENDATIONS")
    print("=" * 70)

    print(f"\nBest by Sharpe Ratio: {best_sharpe[0]} DTE")
    print(f"  Sharpe: {best_sharpe[1]['sharpe']:.2f}")
    print(f"  Win Rate: {best_sharpe[1]['win_rate']:.1%}")
    print(f"  Trades: {best_sharpe[1]['count']}")

    print(f"\nBest by Win Rate: {best_wr[0]} DTE")
    print(f"  Win Rate: {best_wr[1]['win_rate']:.1%}")
    print(f"  Sharpe: {best_wr[1]['sharpe']:.2f}")

    print(f"\nBest by Profit Factor: {best_pf[0]} DTE")
    print(f"  Profit Factor: {best_pf[1]['profit_factor']:.2f}")
    print(f"  Win Rate: {best_pf[1]['win_rate']:.1%}")

    # Exit reason analysis for best DTE
    print("\n" + "=" * 70)
    print(f"EXIT REASON BREAKDOWN (Best DTE = {best_sharpe[0]})")
    print("=" * 70)

    reasons = best_sharpe[1].get('exit_reasons', {})
    total = sum(reasons.values())
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count} ({count/total:.1%})")

    # Practical recommendation
    print("\n" + "=" * 70)
    print("PRACTICAL RECOMMENDATION")
    print("=" * 70)

    # Find DTE range that performs well
    good_dtes = [dte for dte, stats in valid.items()
                 if stats.get('sharpe', 0) >= best_sharpe[1]['sharpe'] * 0.8]

    if good_dtes:
        min_good_dte = min(good_dtes)
        max_good_dte = max(good_dtes)

        print(f"""
Based on {len(data)} days of ETH historical data with realistic assumptions:
- 15-delta short strikes, 5-delta wing strikes
- 3% bid-ask spread per leg (12% total round-trip)
- IV Rank >= 60% entry filter
- 50% profit target

RECOMMENDED DTE RANGE: {min_good_dte} - {max_good_dte} days

Current config uses 30-45 DTE.

DTEs within 80% of best Sharpe: {sorted(good_dtes)}

Top 3 by Sharpe:
""")
        for i, (dte, stats) in enumerate(sorted_results[:3]):
            print(f"  {i+1}. {dte} DTE: Sharpe {stats['sharpe']:.2f}, Win {stats['win_rate']:.1%}")

    # Check Deribit available expiries
    print(f"""
NOTE: Deribit ETH options typically have these expiry cycles:
- Daily: 1-7 days (too short for IC)
- Weekly: ~14, 21 days
- Monthly: ~25-30, 53 days (end of month)
- Quarterly: 81+ days

Current testnet availability gap: 25 DTE to 53 DTE
Adjust target_dte_min and target_dte_max to match available expiries.
""")

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
