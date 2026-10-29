#!/usr/bin/env python
"""Analyze Iron Condor performance segmented by DVOL at entry.

Key questions this script answers:
1. How does IC performance (win rate, Sharpe, premium) vary by DVOL at entry?
2. Is there a DVOL level where IC entries become unprofitable despite higher premiums?
3. What's the optimal approach: halt, reduce size, or trade normally at high DVOL?
4. How long do high-DVOL periods last and what happens to entries during them?

Uses the same IC simulation methodology as calibrate_iron_condor_dte.py
(Black-Scholes pricing, 15-delta shorts, 5-delta wings, 3% bid-ask spread).

Usage:
    python scripts/analyze_ic_dvol_performance.py
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
class ICTradeResult:
    """Result of a simulated Iron Condor trade."""
    entry_date: datetime
    exit_date: datetime
    dte: int
    entry_dvol: float
    entry_iv_rank: float
    entry_price: float
    exit_price: float
    short_put_strike: float
    short_call_strike: float
    long_put_strike: float
    long_call_strike: float
    net_credit: float
    max_loss: float
    pnl: float
    win: bool
    exit_reason: str
    days_held: int
    price_move_pct: float  # abs % move from entry to exit


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
    """Convert delta to strike price using Black-Scholes."""
    T = dte / 365
    sigma = iv / 100
    r = 0.0

    if option_type == 'put':
        target_nd1 = abs(delta)
        neg_d1 = norm.ppf(target_nd1)
        d1 = -neg_d1
    else:
        d1 = norm.ppf(delta)

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

    if (iv_max - iv_min) < 1e-6:
        return 0.5

    return (current_iv - iv_min) / (iv_max - iv_min)


def simulate_iron_condor(
    data: list[dict],
    entry_idx: int,
    dte: int = 35,
    short_delta: float = 0.15,
    wing_delta: float = 0.05,
    profit_target: float = 0.50,
    loss_limit: float = 1.0,
    bid_ask_spread_pct: float = 0.03,
    iv_rank: float = 0.0,
) -> Optional[ICTradeResult]:
    """Simulate a single Iron Condor trade."""
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

    gross_credit = (short_put_price + short_call_price) - (long_put_price + long_call_price)
    spread_cost = 4 * bid_ask_spread_pct * gross_credit
    net_credit = gross_credit - spread_cost

    if net_credit <= 0:
        return None

    put_spread_width = (short_put_strike - long_put_strike) / entry_price
    call_spread_width = (long_call_strike - short_call_strike) / entry_price
    max_spread_width = max(put_spread_width, call_spread_width)
    max_loss = max_spread_width - net_credit

    # Simulate forward - European settlement (no early exit on breach)
    # Deribit options are European-style: price can breach short strikes
    # and come back. Only exit on profit target, loss limit, or expiry.
    exit_reason = None
    exit_idx = entry_idx
    current_value = gross_credit  # Track for loss_limit exit PnL

    for i in range(1, dte + 1):
        if entry_idx + i >= len(data):
            break

        current = data[entry_idx + i]
        current_price = current["price"]
        current_iv = current["dvol"]
        days_remaining = dte - i

        if days_remaining > 0:
            T_remaining = days_remaining / 365
            current_sigma = current_iv / 100

            curr_short_put = black_scholes_put(current_price, short_put_strike, T_remaining, 0, current_sigma)
            curr_long_put = black_scholes_put(current_price, long_put_strike, T_remaining, 0, current_sigma)
            curr_short_call = black_scholes_call(current_price, short_call_strike, T_remaining, 0, current_sigma)
            curr_long_call = black_scholes_call(current_price, long_call_strike, T_remaining, 0, current_sigma)

            current_value = (curr_short_put + curr_short_call) - (curr_long_put + curr_long_call)
        else:
            intrinsic_short_put = max(short_put_strike - current_price, 0) / current_price
            intrinsic_long_put = max(long_put_strike - current_price, 0) / current_price
            intrinsic_short_call = max(current_price - short_call_strike, 0) / current_price
            intrinsic_long_call = max(current_price - long_call_strike, 0) / current_price
            current_value = (intrinsic_short_put + intrinsic_short_call) - (intrinsic_long_put + intrinsic_long_call)

        profit_captured = gross_credit - current_value

        # Check profit target
        if profit_captured >= gross_credit * profit_target:
            exit_reason = "profit_target"
            exit_idx = entry_idx + i
            break

        # Check loss limit (default 1.0 = 100% of premium lost)
        profit_pct = profit_captured / gross_credit
        if profit_pct <= -loss_limit:
            exit_reason = "loss_limit"
            exit_idx = entry_idx + i
            break

        exit_idx = entry_idx + i

    if exit_reason is None:
        # Expiry settlement - use intrinsic value
        exit_data = data[exit_idx]
        exit_price = exit_data["price"]
        if short_put_strike <= exit_price <= short_call_strike:
            exit_reason = "expiry_win"
        elif exit_price < short_put_strike:
            exit_reason = "expiry_put_itm"
        else:
            exit_reason = "expiry_call_itm"

    exit_data = data[exit_idx]
    exit_price = exit_data["price"]
    exit_date = exit_data["timestamp"]

    if exit_reason == "profit_target":
        exit_spread_cost = 4 * bid_ask_spread_pct * gross_credit * 0.5
        pnl = net_credit * profit_target - exit_spread_cost
    elif exit_reason == "expiry_win":
        pnl = net_credit
    elif exit_reason == "expiry_put_itm":
        intrinsic_loss = min((short_put_strike - exit_price) / entry_price, put_spread_width)
        pnl = net_credit - intrinsic_loss
    elif exit_reason == "expiry_call_itm":
        intrinsic_loss = min((exit_price - short_call_strike) / entry_price, call_spread_width)
        pnl = net_credit - intrinsic_loss
    elif exit_reason == "loss_limit":
        # Close at current BS value + spread cost
        exit_spread_cost = 4 * bid_ask_spread_pct * current_value
        pnl = net_credit - current_value - exit_spread_cost
    else:
        pnl = 0

    days_held = (exit_date - entry_date).days
    price_move_pct = abs(exit_price - entry_price) / entry_price

    return ICTradeResult(
        entry_date=entry_date,
        exit_date=exit_date,
        dte=dte,
        entry_dvol=entry_iv,
        entry_iv_rank=iv_rank,
        entry_price=entry_price,
        exit_price=exit_price,
        short_put_strike=short_put_strike,
        short_call_strike=short_call_strike,
        long_put_strike=long_put_strike,
        long_call_strike=long_call_strike,
        net_credit=net_credit,
        max_loss=max_loss,
        pnl=pnl,
        win=pnl > 0,
        exit_reason=exit_reason,
        days_held=days_held,
        price_move_pct=price_move_pct,
    )


def bucket_stats(trades: list[ICTradeResult]) -> dict:
    """Calculate stats for a bucket of trades."""
    if not trades:
        return {"count": 0}

    pnls = [t.pnl for t in trades]
    wins = sum(1 for t in trades if t.win)
    credits = [t.net_credit for t in trades]
    max_losses = [t.max_loss for t in trades]

    # Sharpe
    if np.std(pnls) > 0 and len(trades) > 1:
        days_span = (trades[-1].entry_date - trades[0].entry_date).days
        if days_span > 0:
            trades_per_year = len(trades) * 365 / days_span
        else:
            trades_per_year = 12
        sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(min(trades_per_year, 52))
    else:
        sharpe = 0

    # Profit factor
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Exit reasons
    exit_reasons = {}
    for t in trades:
        exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

    # Risk/reward
    avg_win = np.mean([t.pnl for t in trades if t.win]) if wins > 0 else 0
    avg_loss = np.mean([t.pnl for t in trades if not t.win]) if wins < len(trades) else 0

    return {
        "count": len(trades),
        "wins": wins,
        "win_rate": wins / len(trades),
        "avg_pnl": np.mean(pnls),
        "total_pnl": sum(pnls),
        "sharpe": sharpe,
        "profit_factor": pf,
        "avg_credit": np.mean(credits),
        "avg_max_loss": np.mean(max_losses),
        "avg_win_pnl": avg_win,
        "avg_loss_pnl": avg_loss,
        "exit_reasons": exit_reasons,
        "avg_days_held": np.mean([t.days_held for t in trades]),
        "avg_price_move": np.mean([t.price_move_pct for t in trades]),
        "median_pnl": np.median(pnls),
        "worst_pnl": min(pnls),
        "best_pnl": max(pnls),
    }


def main():
    print("=" * 80)
    print("IRON CONDOR PERFORMANCE BY DVOL AT ENTRY")
    print("Should high-DVOL entries be halted, reduced, or traded normally?")
    print("=" * 80)

    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")
    print(f"Date range: {data[0]['timestamp'].date()} to {data[-1]['timestamp'].date()}")

    # DVOL distribution overview
    dvols = [d["dvol"] for d in data]
    print(f"\nDVOL Distribution:")
    print(f"  Min: {min(dvols):.1f}  Mean: {np.mean(dvols):.1f}  "
          f"Median: {np.median(dvols):.1f}  Max: {max(dvols):.1f}")
    for pct in [75, 85, 90, 95, 99]:
        print(f"  P{pct}: {np.percentile(dvols, pct):.1f}")

    # =========================================================================
    # SECTION 1: Run ALL IC trades (IV Rank >= 60%, any DVOL)
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 1: ALL IC-ELIGIBLE ENTRIES (IV Rank >= 60%, no DVOL filter)")
    print("=" * 80)

    all_trades = []
    last_entry_idx = -7
    start_idx = 252  # Need 252 days for IV rank

    for i in range(start_idx, len(data)):
        if i - last_entry_idx < 7:
            continue

        iv_rank = calculate_iv_rank(data, i)
        if iv_rank is None or iv_rank < 0.60:
            continue

        # Try DTE 35 (near optimal per calibration)
        result = simulate_iron_condor(data, i, dte=35, iv_rank=iv_rank)
        if result is not None:
            all_trades.append(result)
            last_entry_idx = i

    print(f"\nTotal IC-eligible entries: {len(all_trades)}")
    if not all_trades:
        print("No trades found - check data")
        return 1

    overall = bucket_stats(all_trades)
    print(f"Overall: Win {overall['win_rate']:.1%}, Sharpe {overall['sharpe']:.2f}, "
          f"Avg PnL {overall['avg_pnl']:.5f}, PF {overall['profit_factor']:.2f}")

    # =========================================================================
    # SECTION 2: PERFORMANCE BY DVOL BUCKET
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 2: IC PERFORMANCE BY DVOL AT ENTRY")
    print("=" * 80)

    # Define DVOL buckets
    dvol_buckets = [
        ("< 50", 0, 50),
        ("50-60", 50, 60),
        ("60-70", 60, 70),
        ("70-80", 70, 80),
        ("80-90", 80, 90),
        ("90-100", 90, 100),
        (">= 100", 100, 999),
    ]

    print(f"\n{'DVOL Bucket':>12} {'Trades':>7} {'Win%':>7} {'AvgPnL':>10} {'Sharpe':>8} "
          f"{'PF':>7} {'Credit':>9} {'MaxLoss':>9} {'AvgMove':>8}")
    print("-" * 95)

    bucket_results = {}
    for label, low, high in dvol_buckets:
        trades = [t for t in all_trades if low <= t.entry_dvol < high]
        stats = bucket_stats(trades)
        bucket_results[label] = stats

        if stats["count"] > 0:
            pf = stats['profit_factor']
            pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
            print(f"{label:>12} {stats['count']:>7} {stats['win_rate']:>6.1%} "
                  f"{stats['avg_pnl']:>9.5f} {stats['sharpe']:>8.2f} "
                  f"{pf_str:>7} {stats['avg_credit']:>8.5f} "
                  f"{stats['avg_max_loss']:>8.5f} {stats['avg_price_move']:>7.1%}")
        else:
            print(f"{label:>12} {0:>7} {'N/A':>7} {'N/A':>10} {'N/A':>8} "
                  f"{'N/A':>7} {'N/A':>9} {'N/A':>9} {'N/A':>8}")

    # =========================================================================
    # SECTION 3: EXIT REASON BREAKDOWN BY DVOL
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 3: EXIT REASONS BY DVOL BUCKET")
    print("=" * 80)

    print(f"\n{'DVOL Bucket':>12} {'Trades':>7} {'ProfitTgt':>10} {'ExpWin':>8} "
          f"{'ExpPutITM':>10} {'ExpCallITM':>11} {'LossLmt':>8}")
    print("-" * 75)

    for label, _, _ in dvol_buckets:
        stats = bucket_results[label]
        if stats["count"] == 0:
            continue
        exits = stats["exit_reasons"]
        total = stats["count"]
        pt = exits.get("profit_target", 0)
        ew = exits.get("expiry_win", 0)
        ep = exits.get("expiry_put_itm", 0)
        ec = exits.get("expiry_call_itm", 0)
        ll = exits.get("loss_limit", 0)
        print(f"{label:>12} {total:>7} {pt:>5} ({pt/total:>4.0%}) "
              f"{ew:>4} ({ew/total:>4.0%}) "
              f"{ep:>5} ({ep/total:>4.0%}) "
              f"{ec:>6} ({ec/total:>4.0%}) "
              f"{ll:>4} ({ll/total:>4.0%})")

    # =========================================================================
    # SECTION 4: HIGH-DVOL DEEP DIVE (>= 70)
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 4: HIGH-DVOL DEEP DIVE (Individual trades where DVOL >= 70)")
    print("=" * 80)

    high_dvol_trades = [t for t in all_trades if t.entry_dvol >= 70]
    if high_dvol_trades:
        print(f"\n{'Date':>12} {'DVOL':>6} {'IVRank':>7} {'Price':>8} {'Credit':>8} "
              f"{'PnL':>9} {'Win':>5} {'Exit':>14} {'Days':>5} {'Move%':>7}")
        print("-" * 100)
        for t in sorted(high_dvol_trades, key=lambda x: x.entry_date):
            print(f"{t.entry_date.strftime('%Y-%m-%d'):>12} {t.entry_dvol:>6.1f} "
                  f"{t.entry_iv_rank:>6.1%} ${t.entry_price:>7.0f} "
                  f"{t.net_credit:>7.5f} {t.pnl:>8.5f} "
                  f"{'YES' if t.win else 'NO':>5} {t.exit_reason:>14} "
                  f"{t.days_held:>5} {t.price_move_pct:>6.1%}")

        high_stats = bucket_stats(high_dvol_trades)
        print(f"\nSummary (DVOL >= 70): {high_stats['count']} trades, "
              f"Win {high_stats['win_rate']:.1%}, "
              f"Sharpe {high_stats['sharpe']:.2f}, "
              f"Avg credit {high_stats['avg_credit']:.5f}")
    else:
        print("\nNo trades with entry DVOL >= 70")

    # =========================================================================
    # SECTION 5: SCENARIO COMPARISON
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 5: STRATEGY COMPARISON - WHAT HAPPENS WITH DIFFERENT DVOL POLICIES?")
    print("=" * 80)

    # Scenario A: Current (halt at DVOL >= 80)
    trades_a = [t for t in all_trades if t.entry_dvol < 80]
    stats_a = bucket_stats(trades_a)

    # Scenario B: Halt at 90
    trades_b = [t for t in all_trades if t.entry_dvol < 90]
    stats_b = bucket_stats(trades_b)

    # Scenario C: Halt at 100
    trades_c = [t for t in all_trades if t.entry_dvol < 100]
    stats_c = bucket_stats(trades_c)

    # Scenario D: No halt (trade at any DVOL)
    stats_d = bucket_stats(all_trades)

    # Scenario E: Only reduce size (0.5x) above 73, no halt
    # Simulate by halving PnL for high-DVOL trades
    trades_e_pnls = []
    for t in all_trades:
        if t.entry_dvol >= 73:
            trades_e_pnls.append(t.pnl * 0.5)
        else:
            trades_e_pnls.append(t.pnl)
    total_e = sum(trades_e_pnls)

    # Scenario F: Calibrated ETH halt (82), reduce at 73
    trades_f = [t for t in all_trades if t.entry_dvol < 82]
    stats_f = bucket_stats(trades_f)

    print(f"\n{'Scenario':>45} {'Trades':>7} {'Win%':>7} {'TotalPnL':>10} "
          f"{'Sharpe':>8} {'PF':>7}")
    print("-" * 95)

    scenarios = [
        ("A: Current (halt >= 80, BTC default)", stats_a),
        ("B: Halt >= 90", stats_b),
        ("C: Halt >= 100", stats_c),
        ("D: No DVOL halt (trade everything)", stats_d),
        ("F: Calibrated ETH halt (>= 82)", stats_f),
    ]

    for name, stats in scenarios:
        if stats["count"] > 0:
            pf = stats['profit_factor']
            pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
            print(f"{name:>45} {stats['count']:>7} {stats['win_rate']:>6.1%} "
                  f"{stats['total_pnl']:>9.5f} {stats['sharpe']:>8.2f} {pf_str:>7}")

    # Scenario E separately (modified PnLs)
    print(f"{'E: No halt, 0.5x size above DVOL 73':>45} {len(all_trades):>7} "
          f"{'N/A':>7} {total_e:>9.5f} {'N/A':>8} {'N/A':>7}")

    # =========================================================================
    # SECTION 6: PREMIUM ANALYSIS - Credit received vs DVOL
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 6: PREMIUM RICHNESS BY DVOL")
    print("How much more credit do you collect at high DVOL?")
    print("=" * 80)

    finer_buckets = [
        ("40-50", 40, 50),
        ("50-55", 50, 55),
        ("55-60", 55, 60),
        ("60-65", 60, 65),
        ("65-70", 65, 70),
        ("70-75", 70, 75),
        ("75-80", 75, 80),
        ("80-85", 80, 85),
        ("85-90", 85, 90),
        ("90+", 90, 999),
    ]

    print(f"\n{'DVOL':>8} {'Trades':>7} {'AvgCredit':>10} {'CreditRatio':>12} "
          f"{'AvgMaxLoss':>11} {'Credit/Loss':>12} {'Win%':>7}")
    print("-" * 75)

    # Find baseline credit (DVOL 50-60 bucket)
    baseline_trades = [t for t in all_trades if 50 <= t.entry_dvol < 60]
    baseline_credit = np.mean([t.net_credit for t in baseline_trades]) if baseline_trades else 1

    for label, low, high in finer_buckets:
        trades = [t for t in all_trades if low <= t.entry_dvol < high]
        if not trades:
            continue
        avg_credit = np.mean([t.net_credit for t in trades])
        avg_max_loss = np.mean([t.max_loss for t in trades])
        credit_ratio = avg_credit / baseline_credit if baseline_credit > 0 else 0
        credit_loss_ratio = avg_credit / avg_max_loss if avg_max_loss > 0 else 0
        wins = sum(1 for t in trades if t.win)
        wr = wins / len(trades)
        print(f"{label:>8} {len(trades):>7} {avg_credit:>9.5f} {credit_ratio:>11.2f}x "
              f"{avg_max_loss:>10.5f} {credit_loss_ratio:>11.1%} {wr:>6.1%}")

    # =========================================================================
    # SECTION 7: DVOL MEAN REVERSION ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 7: DVOL MEAN REVERSION AFTER SPIKES")
    print("When DVOL spikes above 80, how quickly does it come back?")
    print("=" * 80)

    for threshold in [70, 80, 90]:
        dvol_above = [(i, d["dvol"]) for i, d in enumerate(data) if d["dvol"] >= threshold]
        if not dvol_above:
            continue

        # Find start of each spike period
        spike_starts = []
        prev_idx = -2
        for idx, dvol in dvol_above:
            if idx != prev_idx + 1:
                spike_starts.append(idx)
            prev_idx = idx

        # For each spike, measure DVOL 7/14/30 days later
        changes_7d = []
        changes_14d = []
        changes_30d = []

        for start_idx in spike_starts:
            start_dvol = data[start_idx]["dvol"]
            if start_idx + 7 < len(data):
                changes_7d.append(data[start_idx + 7]["dvol"] - start_dvol)
            if start_idx + 14 < len(data):
                changes_14d.append(data[start_idx + 14]["dvol"] - start_dvol)
            if start_idx + 30 < len(data):
                changes_30d.append(data[start_idx + 30]["dvol"] - start_dvol)

        print(f"\nDVOL >= {threshold}: {len(spike_starts)} spike periods")
        if changes_7d:
            pct_down_7 = sum(1 for c in changes_7d if c < 0) / len(changes_7d)
            print(f"  7 days later:  avg change {np.mean(changes_7d):+.1f}, "
                  f"median {np.median(changes_7d):+.1f}, "
                  f"DVOL lower {pct_down_7:.0%} of time")
        if changes_14d:
            pct_down_14 = sum(1 for c in changes_14d if c < 0) / len(changes_14d)
            print(f"  14 days later: avg change {np.mean(changes_14d):+.1f}, "
                  f"median {np.median(changes_14d):+.1f}, "
                  f"DVOL lower {pct_down_14:.0%} of time")
        if changes_30d:
            pct_down_30 = sum(1 for c in changes_30d if c < 0) / len(changes_30d)
            print(f"  30 days later: avg change {np.mean(changes_30d):+.1f}, "
                  f"median {np.median(changes_30d):+.1f}, "
                  f"DVOL lower {pct_down_30:.0%} of time")

    # =========================================================================
    # SECTION 8: OPPORTUNITY COST
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 8: OPPORTUNITY COST OF HALTING")
    print("How much PnL is left on the table by halting at various thresholds?")
    print("=" * 80)

    for threshold in [70, 73, 80, 82, 90, 100]:
        blocked = [t for t in all_trades if t.entry_dvol >= threshold]
        allowed = [t for t in all_trades if t.entry_dvol < threshold]

        if not blocked:
            print(f"\n  Halt >= {threshold}: No trades blocked")
            continue

        blocked_pnl = sum(t.pnl for t in blocked)
        blocked_wins = sum(1 for t in blocked if t.win)
        blocked_wr = blocked_wins / len(blocked) if blocked else 0
        allowed_pnl = sum(t.pnl for t in allowed) if allowed else 0

        print(f"\n  Halt >= {threshold}: Blocks {len(blocked)} trades "
              f"({len(blocked)}/{len(all_trades)} = {len(blocked)/len(all_trades):.0%})")
        print(f"    Blocked trades: Win {blocked_wr:.1%}, Total PnL {blocked_pnl:+.5f}")
        print(f"    Allowed trades: Total PnL {allowed_pnl:+.5f}")
        print(f"    Opportunity cost: {blocked_pnl:+.5f} "
              f"({'LEAVING MONEY ON TABLE' if blocked_pnl > 0 else 'Avoiding losses'})")

    # =========================================================================
    # SECTION 9: CONCLUSION
    # =========================================================================
    print("\n" + "=" * 80)
    print("SECTION 9: DATA-DRIVEN CONCLUSION")
    print("=" * 80)

    # Find the DVOL level where win rate drops below a meaningful threshold
    print("\nWin rate by DVOL (cumulative, trades WITH DVOL >= threshold):")
    for threshold in [50, 60, 65, 70, 75, 80, 85, 90, 95, 100]:
        above = [t for t in all_trades if t.entry_dvol >= threshold]
        if len(above) >= 3:
            wr = sum(1 for t in above if t.win) / len(above)
            avg_pnl = np.mean([t.pnl for t in above])
            avg_credit = np.mean([t.net_credit for t in above])
            print(f"  DVOL >= {threshold:>3}: {len(above):>3} trades, "
                  f"Win {wr:>5.1%}, AvgPnL {avg_pnl:>+.5f}, "
                  f"AvgCredit {avg_credit:.5f}")
        elif above:
            print(f"  DVOL >= {threshold:>3}: {len(above):>3} trades (too few for stats)")

    print(f"""
INTERPRETATION GUIDE:
- If high-DVOL entries have HIGHER win rates and PnL -> halt is costing money
- If high-DVOL entries have LOWER win rates despite higher credit -> halt is justified
- If risk/reward (credit/max_loss) improves with DVOL -> position sizer is sufficient
- DVOL mean reversion supports selling premium: if DVOL drops after spikes,
  the spread value decays faster (double tailwind: theta + vega)
""")

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
