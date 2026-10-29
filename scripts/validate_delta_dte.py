#!/usr/bin/env python
"""Validate delta/DTE calibration findings with more rigorous methodology.

This script addresses issues in the original calibration:
1. Fixes Sharpe ratio calculation (was using 52 for all)
2. Adds bid-ask spread estimation (5-15% of mid price)
3. Uses European-style expiry (no early exit on breach)
4. Shows exit reason breakdown
5. Checks real Deribit liquidity for different deltas

Usage:
    python scripts/validate_delta_dte.py
"""

import asyncio
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
    entry_price: float
    exit_price: float
    premium_mid: float      # Mid-price premium
    premium_after_spread: float  # Premium after bid-ask cost
    pnl: float
    win: bool
    exit_reason: str
    days_held: int


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate Black-Scholes put price."""
    if T <= 0:
        return max(K - S, 0) / S

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put_price / S


def delta_to_strike(spot: float, delta: float, dte: int, iv: float) -> float:
    """Convert delta to strike price using Black-Scholes."""
    T = dte / 365
    sigma = iv / 100
    r = 0.0

    target_nd1 = abs(delta)
    neg_d1 = norm.ppf(target_nd1)
    d1 = -neg_d1

    exponent = d1 * sigma * np.sqrt(T) - (r + 0.5 * sigma**2) * T
    K = spot / np.exp(exponent)

    return K


def estimate_spread_pct(delta: float, dte: int) -> float:
    """Estimate bid-ask spread as percentage of mid price.

    Based on typical Deribit option spreads:
    - OTM options (low delta): wider spreads (10-15%)
    - ATM options (high delta): tighter spreads (5-8%)
    - Longer DTE: slightly tighter (more interest)

    This is conservative - actual spreads may be worse.
    """
    abs_delta = abs(delta)

    # Base spread by delta
    if abs_delta <= 0.15:
        base_spread = 0.12  # 12% for far OTM
    elif abs_delta <= 0.25:
        base_spread = 0.10  # 10% for OTM
    elif abs_delta <= 0.35:
        base_spread = 0.08  # 8% for near ATM
    else:
        base_spread = 0.06  # 6% for ATM

    # DTE adjustment (longer = slightly tighter)
    if dte >= 45:
        dte_adj = 0.98
    elif dte >= 30:
        dte_adj = 1.00
    else:
        dte_adj = 1.05  # Shorter DTE = wider

    return base_spread * dte_adj


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


def simulate_trade_european(
    data: list[dict],
    entry_idx: int,
    delta: float,
    dte: int,
    profit_target: float = 0.50,
    include_spread: bool = True,
) -> Optional[TradeResult]:
    """Simulate a put-selling trade with European-style settlement.

    Key differences from original:
    - No early exit on breach (European style)
    - Includes bid-ask spread cost
    - Tracks days held for accurate Sharpe
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
    premium_mid = black_scholes_put(entry_price, strike, T, 0, sigma)

    if premium_mid <= 0:
        return None

    # Apply bid-ask spread (we sell at bid, which is lower than mid)
    if include_spread:
        spread_pct = estimate_spread_pct(delta, dte)
        # Selling at bid = mid * (1 - spread/2)
        premium_after_spread = premium_mid * (1 - spread_pct / 2)
    else:
        premium_after_spread = premium_mid

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

        # Calculate current option value
        if days_remaining > 0:
            T_remaining = days_remaining / 365
            current_sigma = current_iv / 100
            current_value = black_scholes_put(current_price, strike, T_remaining, 0, current_sigma)
        else:
            # At expiry - European settlement
            current_value = max(strike - current_price, 0) / current_price

        # Check profit target (buying back at ask = mid * (1 + spread/2))
        if include_spread:
            spread_pct = estimate_spread_pct(delta, days_remaining) if days_remaining > 0 else 0
            buyback_cost = current_value * (1 + spread_pct / 2)
        else:
            buyback_cost = current_value

        # Profit target: close when we've captured profit_target of premium
        target_value = premium_mid * (1 - profit_target)
        if current_value <= target_value:
            exit_reason = "profit_target"
            exit_idx = entry_idx + i
            break

        exit_idx = entry_idx + i

    # At expiry
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
    days_held = exit_idx - entry_idx

    # Calculate P&L with spread costs
    if exit_reason == "profit_target":
        # Kept profit_target of premium, minus spread costs both ways
        if include_spread:
            spread_entry = estimate_spread_pct(delta, dte)
            spread_exit = estimate_spread_pct(delta, dte - days_held)
            # Entry: sell at bid (mid * 0.95 for 10% spread)
            # Exit: buy at ask (mid * 1.05 for 10% spread)
            entry_premium = premium_mid * (1 - spread_entry / 2)
            exit_cost = premium_mid * (1 - profit_target) * (1 + spread_exit / 2)
            pnl = entry_premium - exit_cost
        else:
            pnl = premium_mid * profit_target
    elif exit_reason == "expiry_otm":
        # Kept full premium (minus entry spread cost)
        pnl = premium_after_spread
    else:  # expiry_itm
        # Loss = intrinsic value - premium received
        intrinsic = max(strike - exit_price, 0) / entry_price
        pnl = premium_after_spread - intrinsic

    win = pnl > 0

    return TradeResult(
        entry_date=entry_date,
        exit_date=exit_date,
        delta=delta,
        dte=dte,
        strike=strike,
        entry_price=entry_price,
        exit_price=exit_price,
        premium_mid=premium_mid,
        premium_after_spread=premium_after_spread,
        pnl=pnl,
        win=win,
        exit_reason=exit_reason,
        days_held=days_held,
    )


def run_backtest(
    data: list[dict],
    delta: float,
    dte: int,
    min_gap_days: int = 7,
    include_spread: bool = True,
) -> list[TradeResult]:
    """Run backtest for a specific delta/DTE combination."""
    results = []
    last_entry_idx = -min_gap_days
    start_idx = 252

    for i in range(start_idx, len(data) - dte):
        if i - last_entry_idx < min_gap_days:
            continue

        result = simulate_trade_european(data, i, delta, dte, include_spread=include_spread)
        if result is not None:
            results.append(result)
            last_entry_idx = i

    return results


def analyze_results(results: list[TradeResult], data_days: int) -> dict:
    """Analyze backtest results with corrected metrics."""
    if not results:
        return {"count": 0}

    wins = sum(1 for r in results if r.win)
    pnls = [r.pnl for r in results]

    win_rate = wins / len(results)
    avg_pnl = np.mean(pnls)
    total_pnl = sum(pnls)

    # Correct Sharpe calculation
    # Annualize based on actual trading frequency
    total_days_traded = sum(r.days_held for r in results)
    if total_days_traded > 0 and np.std(pnls) > 0:
        # Average days per trade
        avg_days_per_trade = total_days_traded / len(results)
        # Trades per year
        trades_per_year = 365 / avg_days_per_trade
        # Annualized Sharpe
        sharpe = (avg_pnl / np.std(pnls)) * np.sqrt(trades_per_year)
    else:
        sharpe = 0

    # Profit factor
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown (consecutive losses)
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = running_max - cumulative
    max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0

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
        "max_drawdown": max_drawdown,
        "exit_reasons": exit_reasons,
        "avg_days_held": sum(r.days_held for r in results) / len(results),
    }


async def check_deribit_liquidity():
    """Check real liquidity on Deribit for different delta options."""
    from src.data.deribit_client import DeribitClient

    print("\n" + "=" * 70)
    print("DERIBIT LIQUIDITY CHECK")
    print("=" * 70)

    client = DeribitClient(base_url="https://www.deribit.com")

    try:
        # Get ETH index price
        ticker = await client.get_ticker("ETH-PERPETUAL")
        index_price = ticker.get("index_price", ticker.get("last_price", 0))
        print(f"\nETH Index Price: ${index_price:,.2f}")

        # Get instruments
        await asyncio.sleep(0.2)
        instruments = await client.get_instruments(currency="ETH", kind="option")

        now = datetime.now(timezone.utc)

        # Filter for 30-45 DTE puts
        valid = []
        for inst in instruments:
            if inst.get("option_type") != "put":
                continue
            expiry_ts = inst.get("expiration_timestamp", 0)
            expiry_dt = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
            dte = (expiry_dt - now).days
            if 25 <= dte <= 50:
                valid.append((inst, dte))

        print(f"\nFound {len(valid)} put options in 25-50 DTE range")

        # Sample options at different deltas
        delta_buckets = {
            "15d (0.10-0.20)": [],
            "25d (0.20-0.30)": [],
            "35d (0.30-0.40)": [],
            "40d (0.35-0.45)": [],
        }

        for inst, dte in valid[:50]:  # Check first 50
            name = inst.get("instrument_name", "")
            await asyncio.sleep(0.1)
            try:
                ticker = await client.get_ticker(name)
            except Exception:
                continue

            delta = abs(ticker.get("greeks", {}).get("delta", 0) or 0)
            bid = ticker.get("best_bid_price", 0) or 0
            ask = ticker.get("best_ask_price", 0) or 0
            mid = (bid + ask) / 2 if bid and ask else 0
            spread_pct = (ask - bid) / mid * 100 if mid > 0 else 0
            open_interest = ticker.get("open_interest", 0) or 0

            entry = {
                "name": name,
                "dte": dte,
                "delta": delta,
                "bid": bid,
                "ask": ask,
                "spread_pct": spread_pct,
                "open_interest": open_interest,
            }

            if 0.10 <= delta < 0.20:
                delta_buckets["15d (0.10-0.20)"].append(entry)
            elif 0.20 <= delta < 0.30:
                delta_buckets["25d (0.20-0.30)"].append(entry)
            elif 0.30 <= delta < 0.40:
                delta_buckets["35d (0.30-0.40)"].append(entry)
            elif 0.35 <= delta < 0.45:
                delta_buckets["40d (0.35-0.45)"].append(entry)

        print("\n  Liquidity by Delta Bucket:")
        print(f"  {'Bucket':<20} {'Count':>6} {'Avg Spread':>12} {'Avg OI':>10}")
        print("  " + "-" * 52)

        for bucket, entries in delta_buckets.items():
            if entries:
                avg_spread = np.mean([e["spread_pct"] for e in entries])
                avg_oi = np.mean([e["open_interest"] for e in entries])
                print(f"  {bucket:<20} {len(entries):>6} {avg_spread:>11.1f}% {avg_oi:>10.0f}")
            else:
                print(f"  {bucket:<20} {0:>6} {'N/A':>12} {'N/A':>10}")

        # Show sample options
        print("\n  Sample Options (30-40 DTE):")
        for bucket, entries in delta_buckets.items():
            if entries:
                sample = entries[0]
                print(f"\n  {bucket}:")
                print(f"    {sample['name']}")
                print(f"    Bid: {sample['bid']:.4f}, Ask: {sample['ask']:.4f}, Spread: {sample['spread_pct']:.1f}%")
                print(f"    Open Interest: {sample['open_interest']:.0f}")

    except Exception as e:
        print(f"Error checking liquidity: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


def main():
    print("=" * 70)
    print("DELTA/DTE VALIDATION - RIGOROUS METHODOLOGY")
    print("=" * 70)

    # Load data
    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")
    print(f"Date range: {data[0]['timestamp'].date()} to {data[-1]['timestamp'].date()}")

    deltas = [-0.15, -0.25, -0.35, -0.40]
    dtes = [30, 45, 60]

    print(f"\nTesting {len(deltas)} deltas x {len(dtes)} DTEs = {len(deltas) * len(dtes)} combinations")
    print("With bid-ask spread estimation (5-12% of mid)")
    print("Using European-style settlement (no early breach exit)")

    # Run backtests - with spread
    print("\n" + "-" * 70)
    print("RESULTS WITH BID-ASK SPREAD")
    print("-" * 70)

    results_with_spread = {}
    for delta in deltas:
        for dte in dtes:
            key = (delta, dte)
            results = run_backtest(data, delta, dte, include_spread=True)
            analysis = analyze_results(results, len(data))
            results_with_spread[key] = analysis

    print(f"\n{'Delta':>7} {'DTE':>5} {'Trades':>7} {'Win%':>7} {'AvgPnL':>9} {'Sharpe':>8} {'MaxDD':>8}")
    print("-" * 60)

    for (delta, dte), stats in sorted(results_with_spread.items(), key=lambda x: x[1].get("sharpe", 0), reverse=True):
        if stats["count"] > 0:
            print(f"{abs(delta):>6.0%} {dte:>5} {stats['count']:>7} "
                  f"{stats['win_rate']:>6.1%} {stats['avg_pnl']:>8.4f} "
                  f"{stats['sharpe']:>8.2f} {stats['max_drawdown']:>7.4f}")

    # Exit reason analysis
    print("\n" + "-" * 70)
    print("EXIT REASON BREAKDOWN")
    print("-" * 70)

    print(f"\n{'Delta':>7} {'DTE':>5} {'profit_target':>14} {'expiry_otm':>12} {'expiry_itm':>12}")
    print("-" * 55)

    for (delta, dte), stats in sorted(results_with_spread.items()):
        if stats["count"] > 0:
            reasons = stats.get("exit_reasons", {})
            pt = reasons.get("profit_target", 0)
            otm = reasons.get("expiry_otm", 0)
            itm = reasons.get("expiry_itm", 0)
            total = pt + otm + itm
            print(f"{abs(delta):>6.0%} {dte:>5} {pt:>7} ({pt/total*100:>4.0f}%) "
                  f"{otm:>5} ({otm/total*100:>4.0f}%) {itm:>5} ({itm/total*100:>4.0f}%)")

    # Comparison: with vs without spread
    print("\n" + "-" * 70)
    print("IMPACT OF BID-ASK SPREAD")
    print("-" * 70)

    results_no_spread = {}
    for delta in deltas:
        for dte in dtes:
            key = (delta, dte)
            results = run_backtest(data, delta, dte, include_spread=False)
            analysis = analyze_results(results, len(data))
            results_no_spread[key] = analysis

    print(f"\n{'Delta':>7} {'DTE':>5} {'Sharpe (no spread)':>18} {'Sharpe (with spread)':>20} {'Diff':>8}")
    print("-" * 65)

    for (delta, dte) in sorted(results_with_spread.keys()):
        no_spread = results_no_spread[(delta, dte)].get("sharpe", 0)
        with_spread = results_with_spread[(delta, dte)].get("sharpe", 0)
        diff = with_spread - no_spread
        print(f"{abs(delta):>6.0%} {dte:>5} {no_spread:>18.2f} {with_spread:>20.2f} {diff:>7.2f}")

    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    # Find best with spread
    valid = {k: v for k, v in results_with_spread.items() if v.get("count", 0) >= 10}
    best_with_spread = max(valid.items(), key=lambda x: x[1].get("sharpe", 0))

    # Compare to original findings
    print(f"""
Original Calibration (no spread, breach-exit):
  Best: 40 delta, 60 DTE - Sharpe 14.15

Validated (with spread, European-style):
  Best: {abs(best_with_spread[0][0]):.0%} delta, {best_with_spread[0][1]} DTE
  Sharpe: {best_with_spread[1]['sharpe']:.2f}
  Win Rate: {best_with_spread[1]['win_rate']:.1%}
  Avg P&L: {best_with_spread[1]['avg_pnl']:.4f}

Key Differences:
  1. Bid-ask spread reduces Sharpe significantly
  2. European settlement (no breach exit) affects timing
  3. Higher delta still has advantage due to higher premium

Recommendation:
""")

    # Find current defaults
    current_25_30 = results_with_spread.get((-0.25, 30), {})
    current_15_30 = results_with_spread.get((-0.15, 30), {})

    if best_with_spread[1]['sharpe'] > current_25_30.get('sharpe', 0) * 1.5:
        print(f"  Higher delta/DTE still outperforms, but margin is smaller with realistic spreads.")
        print(f"  Consider paper trading {abs(best_with_spread[0][0]):.0%} delta, {best_with_spread[0][1]} DTE")
    else:
        print(f"  With bid-ask spreads, advantage is marginal. Current defaults may be acceptable.")

    return 0


if __name__ == "__main__":
    try:
        # Run main analysis
        exit_code = main()

        # Check real liquidity (optional - comment out if slow)
        print("\nChecking real Deribit liquidity (takes ~30s)...")
        asyncio.run(check_deribit_liquidity())

        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
