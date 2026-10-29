#!/usr/bin/env python
"""Calibrate optimal delta and DTE for premium selling strategies.

This script:
1. Uses historical ETH price/DVOL data
2. Simulates selling puts at various deltas and DTEs
3. Calculates win rates, returns, and Sharpe ratios
4. Recommends optimal parameters

Methodology:
- For each (delta, DTE) combination:
  - Simulate selling a put at that delta
  - Track if price breached strike by expiry
  - Calculate theoretical P&L based on premium decay
  - Win = expired OTM or closed at 50% profit

Usage:
    python scripts/calibrate_delta_dte.py
"""

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import numpy as np
from scipy.stats import norm

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class TradeResult:
    """Result of a simulated trade."""
    entry_date: datetime
    exit_date: datetime
    delta: float
    dte: int
    strike: float
    entry_price: float  # Underlying price at entry
    exit_price: float   # Underlying price at exit
    premium: float      # Premium received (as fraction of underlying)
    pnl: float          # Final P&L (as fraction of underlying)
    win: bool           # True if profitable
    exit_reason: str    # 'profit_target', 'expiry_otm', 'expiry_itm', 'breached'


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate Black-Scholes put price.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Volatility (annualized, as decimal e.g., 0.60 for 60%)

    Returns:
        Put price as fraction of spot (in underlying terms)
    """
    if T <= 0:
        return max(K - S, 0) / S

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put_price / S  # Return as fraction of spot


def delta_to_strike(spot: float, delta: float, dte: int, iv: float) -> float:
    """Convert delta to strike price using Black-Scholes.

    For puts, delta is negative (e.g., -0.25 for 25-delta put).

    Args:
        spot: Current spot price
        delta: Target delta (negative for puts)
        dte: Days to expiry
        iv: Implied volatility (as percentage, e.g., 60 for 60%)

    Returns:
        Strike price corresponding to that delta
    """
    T = dte / 365
    sigma = iv / 100
    r = 0.0  # Crypto has no risk-free rate benefit

    # For a put, delta = -N(-d1)
    # So N(-d1) = -delta = |delta|
    # -d1 = norm.ppf(|delta|)
    # d1 = -norm.ppf(|delta|)

    target_nd1 = abs(delta)
    neg_d1 = norm.ppf(target_nd1)
    d1 = -neg_d1

    # d1 = (ln(S/K) + (r + 0.5*sigma^2)*T) / (sigma*sqrt(T))
    # Solve for K:
    # ln(S/K) = d1 * sigma * sqrt(T) - (r + 0.5*sigma^2)*T
    # S/K = exp(d1 * sigma * sqrt(T) - (r + 0.5*sigma^2)*T)
    # K = S / exp(...)

    exponent = d1 * sigma * np.sqrt(T) - (r + 0.5 * sigma**2) * T
    K = spot / np.exp(exponent)

    return K


def load_data(db_path: str = "data/trading.db") -> list[dict]:
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
        data.append({
            "timestamp": datetime.fromisoformat(row[0]),
            "price": row[1],
            "dvol": row[2],
        })

    conn.close()
    return data


def simulate_trade(
    data: list[dict],
    entry_idx: int,
    delta: float,
    dte: int,
    profit_target: float = 0.50,
) -> Optional[TradeResult]:
    """Simulate a single put-selling trade.

    Args:
        data: Historical price/vol data
        entry_idx: Index in data to enter trade
        delta: Target delta for put (negative, e.g., -0.25)
        dte: Days to expiry
        profit_target: Close at this fraction of premium (e.g., 0.50)

    Returns:
        TradeResult or None if not enough data
    """
    if entry_idx + dte >= len(data):
        return None

    entry = data[entry_idx]
    entry_price = entry["price"]
    entry_iv = entry["dvol"]
    entry_date = entry["timestamp"]

    # Calculate strike from delta
    strike = delta_to_strike(entry_price, delta, dte, entry_iv)

    # Calculate initial premium using Black-Scholes
    T = dte / 365
    sigma = entry_iv / 100
    premium = black_scholes_put(entry_price, strike, T, 0, sigma)

    if premium <= 0:
        return None

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

        # Check if breached (price below strike)
        if current_price < strike:
            # For simplicity, if breached we assume loss = strike - price
            # In reality, might recover, but this is conservative
            exit_reason = "breached"
            exit_idx = entry_idx + i
            break

        # Calculate current option value
        if days_remaining > 0:
            T_remaining = days_remaining / 365
            current_sigma = current_iv / 100
            current_value = black_scholes_put(current_price, strike, T_remaining, 0, current_sigma)
        else:
            # At expiry
            current_value = max(strike - current_price, 0) / current_price

        # Check profit target (premium decayed by profit_target)
        if current_value <= premium * (1 - profit_target):
            exit_reason = "profit_target"
            exit_idx = entry_idx + i
            break

        exit_idx = entry_idx + i

    # If we reached here without exit, check expiry
    if exit_reason is None:
        exit_data = data[exit_idx]
        exit_price = exit_data["price"]

        if exit_price >= strike:
            exit_reason = "expiry_otm"
        else:
            exit_reason = "expiry_itm"

    exit_data = data[exit_idx]
    exit_price = exit_data["price"]
    exit_date = exit_data["timestamp"]

    # Calculate P&L
    if exit_reason == "profit_target":
        pnl = premium * profit_target  # Captured profit_target of premium
    elif exit_reason == "expiry_otm":
        pnl = premium  # Kept full premium
    elif exit_reason in ("expiry_itm", "breached"):
        # Loss = intrinsic value at exit - premium received
        intrinsic = max(strike - exit_price, 0) / entry_price
        pnl = premium - intrinsic
    else:
        pnl = 0

    win = pnl > 0

    return TradeResult(
        entry_date=entry_date,
        exit_date=exit_date,
        delta=delta,
        dte=dte,
        strike=strike,
        entry_price=entry_price,
        exit_price=exit_price,
        premium=premium,
        pnl=pnl,
        win=win,
        exit_reason=exit_reason,
    )


def run_backtest(
    data: list[dict],
    delta: float,
    dte: int,
    min_gap_days: int = 7,  # Minimum days between trades
) -> list[TradeResult]:
    """Run backtest for a specific delta/DTE combination.

    Args:
        data: Historical data
        delta: Target delta
        dte: Days to expiry
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

        result = simulate_trade(data, i, delta, dte)
        if result is not None:
            results.append(result)
            last_entry_idx = i

    return results


def analyze_results(results: list[TradeResult]) -> dict:
    """Analyze backtest results."""
    if not results:
        return {"count": 0}

    wins = sum(1 for r in results if r.win)
    pnls = [r.pnl for r in results]

    win_rate = wins / len(results)
    avg_pnl = np.mean(pnls)
    total_pnl = sum(pnls)

    # Sharpe ratio (annualized, assuming ~50 trades/year)
    if np.std(pnls) > 0:
        trades_per_year = len(results) / (len(results) * 7 / 365)  # Approximate
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

    return {
        "count": len(results),
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "exit_reasons": exit_reasons,
    }


def main():
    print("=" * 70)
    print("DELTA & DTE CALIBRATION FOR PREMIUM SELLING")
    print("=" * 70)

    # Load data
    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")
    print(f"Date range: {data[0]['timestamp'].date()} to {data[-1]['timestamp'].date()}")

    # Test parameters
    deltas = [-0.15, -0.20, -0.25, -0.30, -0.35, -0.40]
    dtes = [14, 21, 30, 45, 60]

    print(f"\nTesting {len(deltas)} deltas x {len(dtes)} DTEs = {len(deltas) * len(dtes)} combinations")

    # Run backtests
    all_results = {}

    for delta in deltas:
        for dte in dtes:
            key = (delta, dte)
            results = run_backtest(data, delta, dte)
            analysis = analyze_results(results)
            all_results[key] = analysis

            if analysis["count"] > 0:
                print(f"  Delta {abs(delta):.0%}, DTE {dte:2d}: "
                      f"{analysis['count']:3d} trades, "
                      f"Win {analysis['win_rate']:.1%}, "
                      f"Sharpe {analysis['sharpe']:.2f}")

    # Find best by different metrics
    print("\n" + "=" * 70)
    print("RESULTS BY METRIC")
    print("=" * 70)

    # Filter to combinations with enough trades
    valid = {k: v for k, v in all_results.items() if v.get("count", 0) >= 10}

    if not valid:
        print("\nNot enough trades for analysis")
        return 1

    # Best by win rate
    best_wr = max(valid.items(), key=lambda x: x[1].get("win_rate", 0))
    print(f"\nBest Win Rate: Delta {abs(best_wr[0][0]):.0%}, DTE {best_wr[0][1]}")
    print(f"  Win Rate: {best_wr[1]['win_rate']:.1%}")
    print(f"  Trades: {best_wr[1]['count']}")

    # Best by Sharpe
    best_sharpe = max(valid.items(), key=lambda x: x[1].get("sharpe", 0))
    print(f"\nBest Sharpe Ratio: Delta {abs(best_sharpe[0][0]):.0%}, DTE {best_sharpe[0][1]}")
    print(f"  Sharpe: {best_sharpe[1]['sharpe']:.2f}")
    print(f"  Win Rate: {best_sharpe[1]['win_rate']:.1%}")

    # Best by profit factor
    best_pf = max(valid.items(), key=lambda x: x[1].get("profit_factor", 0) if x[1].get("profit_factor", 0) != float('inf') else 0)
    print(f"\nBest Profit Factor: Delta {abs(best_pf[0][0]):.0%}, DTE {best_pf[0][1]}")
    print(f"  Profit Factor: {best_pf[1]['profit_factor']:.2f}")
    print(f"  Win Rate: {best_pf[1]['win_rate']:.1%}")

    # Detailed table
    print("\n" + "=" * 70)
    print("FULL RESULTS TABLE")
    print("=" * 70)

    print(f"\n{'Delta':>8} {'DTE':>6} {'Trades':>8} {'Win%':>8} {'AvgPnL':>10} {'Sharpe':>8} {'PF':>8}")
    print("-" * 70)

    # Sort by Sharpe
    sorted_results = sorted(valid.items(), key=lambda x: x[1].get("sharpe", 0), reverse=True)

    for (delta, dte), stats in sorted_results:
        pf = stats['profit_factor']
        pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
        print(f"{abs(delta):>7.0%} {dte:>6} {stats['count']:>8} "
              f"{stats['win_rate']:>7.1%} {stats['avg_pnl']:>9.4f} "
              f"{stats['sharpe']:>8.2f} {pf_str:>8}")

    # Comparison with current defaults
    print("\n" + "=" * 70)
    print("COMPARISON WITH CURRENT DEFAULTS")
    print("=" * 70)

    current_wheel = (-0.25, 30)  # Current: 25 delta, 30-45 DTE (using 30)
    current_ic = (-0.15, 30)     # Current: 15 delta for IC

    print("\nWHEEL STRATEGY (current: 25 delta, 30-45 DTE)")
    if current_wheel in valid:
        curr = valid[current_wheel]
        print(f"  Current (25d, 30 DTE): Win {curr['win_rate']:.1%}, Sharpe {curr['sharpe']:.2f}")

    print(f"  Best by Sharpe: {abs(best_sharpe[0][0]):.0%} delta, {best_sharpe[0][1]} DTE")
    print(f"    -> Win {best_sharpe[1]['win_rate']:.1%}, Sharpe {best_sharpe[1]['sharpe']:.2f}")

    print("\nIRON CONDOR (current: 15 delta)")
    if current_ic in valid:
        curr = valid[current_ic]
        print(f"  Current (15d, 30 DTE): Win {curr['win_rate']:.1%}, Sharpe {curr['sharpe']:.2f}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"""
Analysis based on {len(data)} days of ETH historical data.

Key Findings:
1. Best Sharpe Ratio: {abs(best_sharpe[0][0]):.0%} delta, {best_sharpe[0][1]} DTE
   - Sharpe: {best_sharpe[1]['sharpe']:.2f}, Win Rate: {best_sharpe[1]['win_rate']:.1%}

2. Best Win Rate: {abs(best_wr[0][0]):.0%} delta, {best_wr[0][1]} DTE
   - Win Rate: {best_wr[1]['win_rate']:.1%}

3. Current Defaults:
   - Wheel: 25 delta, 30-45 DTE
   - Iron Condor: 15 delta

Note: These results are based on historical simulation.
Actual results may vary due to:
- Bid-ask spreads not modeled
- Liquidity constraints
- Execution slippage
- IV smile/skew effects
""")

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
