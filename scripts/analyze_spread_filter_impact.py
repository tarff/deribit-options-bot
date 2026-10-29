#!/usr/bin/env python
"""Analyze why the IV-RV spread > 16 filter hurts IC performance.

Compares trades that pass vs fail the spread filter to understand
whether the spread filter is adding or destroying value.

Usage:
    python scripts/analyze_spread_filter_impact.py
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))

# Reuse functions from calibrate_kelly_params
from scripts.calibrate_kelly_params import (
    load_data, calc_iv_rank, calc_rv30, simulate_ic,
    IV_RANK_LOOKBACK, RV_LOOKBACK, MIN_GAP_DAYS, TEST_DTES, DTE_MIN, DTE_MAX,
)


def run_all_trades(data, min_iv_rank=0.60, profit_target=0.50):
    """Run IC backtest with just IV Rank filter, tag each trade with spread info."""
    trades = []
    last_entry_idx = -MIN_GAP_DAYS
    start_idx = max(IV_RANK_LOOKBACK, RV_LOOKBACK)

    for i in range(start_idx, len(data)):
        if i - last_entry_idx < MIN_GAP_DAYS:
            continue

        iv_rank = calc_iv_rank(data, i)
        if iv_rank is None or iv_rank < min_iv_rank:
            continue

        rv30 = calc_rv30(data, i)
        if rv30 is None:
            continue

        dvol = data[i]["dvol"]
        spread = dvol - rv30

        for dte in TEST_DTES:
            if dte < DTE_MIN or dte > DTE_MAX:
                continue
            result = simulate_ic(data, i, dte, iv_rank, spread, profit_target)
            if result is not None:
                trades.append(result)
                last_entry_idx = i
                break

    return trades


def main():
    print("=" * 75)
    print("SPREAD FILTER IMPACT ANALYSIS")
    print("=" * 75)

    data = load_data()
    print(f"\nLoaded {len(data)} days of ETH data")

    trades = run_all_trades(data)
    print(f"Total trades (IVR>60%): {len(trades)}")

    # Split by spread threshold
    thresholds = [0, 5, 10, 16, 20]

    print(f"\n{'=' * 75}")
    print("PERFORMANCE BY IV-RV SPREAD BUCKET")
    print(f"{'=' * 75}")

    buckets = [
        ("Spread < 0",        lambda t: t.iv_rv_spread < 0),
        ("Spread 0-10",       lambda t: 0 <= t.iv_rv_spread < 10),
        ("Spread 10-16",      lambda t: 10 <= t.iv_rv_spread < 16),
        ("Spread >= 16",      lambda t: t.iv_rv_spread >= 16),
    ]

    print(f"\n  {'Bucket':<20} {'N':>4} {'Win%':>6} {'AvgPnL':>10} {'AvgWin':>8} {'AvgLoss':>8} {'PF':>6}")
    print(f"  {'-' * 65}")

    for label, filt in buckets:
        bt = [t for t in trades if filt(t)]
        if not bt:
            print(f"  {label:<20} {0:>4}   --")
            continue

        wins = [t for t in bt if t.win]
        losses = [t for t in bt if not t.win]
        wr = len(wins) / len(bt)
        avg_pnl = np.mean([t.pnl for t in bt])
        aw = np.mean([t.pnl for t in wins]) if wins else 0
        al = np.mean([abs(t.pnl) for t in losses]) if losses else 0
        gp = sum(t.pnl for t in wins) if wins else 0
        gl = abs(sum(t.pnl for t in losses)) if losses else 0
        pf = gp / gl if gl > 0 else float("inf")
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"

        print(f"  {label:<20} {len(bt):>4} {wr:>5.1%} {avg_pnl:>+9.5f} "
              f"{aw:>7.5f} {al:>7.5f} {pf_str:>6}")

    # ---- What the spread filter actually removes ----
    print(f"\n{'=' * 75}")
    print("WHAT THE SPREAD > 16 FILTER REMOVES")
    print(f"{'=' * 75}")

    passed = [t for t in trades if t.iv_rv_spread >= 16]
    removed = [t for t in trades if t.iv_rv_spread < 16]

    print(f"\n  Passed filter (spread >= 16): {len(passed)} trades")
    if passed:
        pw = [t for t in passed if t.win]
        pl = [t for t in passed if not t.win]
        print(f"    Win rate: {len(pw)/len(passed):.1%}")
        print(f"    Avg P&L: {np.mean([t.pnl for t in passed]):+.5f}")
        print(f"    Losses: {[f'{t.entry_date.date()} pnl={t.pnl:+.5f} spread={t.iv_rv_spread:.1f}' for t in pl]}")

    print(f"\n  Removed by filter (spread < 16): {len(removed)} trades")
    if removed:
        rw = [t for t in removed if t.win]
        rl = [t for t in removed if not t.win]
        print(f"    Win rate: {len(rw)/len(removed):.1%}")
        print(f"    Avg P&L: {np.mean([t.pnl for t in removed]):+.5f}")
        print(f"    Losses: {[f'{t.entry_date.date()} pnl={t.pnl:+.5f} spread={t.iv_rv_spread:.1f}' for t in rl]}")

    # ---- Scatter: spread vs P&L ----
    print(f"\n{'=' * 75}")
    print("SPREAD vs P&L CORRELATION")
    print(f"{'=' * 75}")

    spreads = [t.iv_rv_spread for t in trades]
    pnls = [t.pnl for t in trades]
    corr = np.corrcoef(spreads, pnls)[0, 1]
    print(f"\n  Correlation(spread, pnl): {corr:+.3f}")
    print(f"  {'Positive' if corr > 0 else 'Negative'} = higher spread {'helps' if corr > 0 else 'hurts'} IC P&L")

    # ---- Cumulative filter thresholds ----
    print(f"\n{'=' * 75}")
    print("CUMULATIVE FILTER THRESHOLD SWEEP")
    print(f"{'=' * 75}")
    print(f"\n  {'Min Spread':>12} {'N':>4} {'Win%':>6} {'AvgPnL':>10} {'TotalPnL':>10} {'Sharpe':>7}")
    print(f"  {'-' * 52}")

    for thresh in [-30, -20, -10, 0, 5, 10, 12, 14, 16, 18, 20, 25, 30]:
        ft = [t for t in trades if t.iv_rv_spread >= thresh]
        if len(ft) < 3:
            continue
        wr = sum(1 for t in ft if t.win) / len(ft)
        pnls_f = [t.pnl for t in ft]
        avg = np.mean(pnls_f)
        total = sum(pnls_f)
        std = np.std(pnls_f)
        days = (ft[-1].entry_date - ft[0].entry_date).days
        tpy = len(ft) * 365 / days if days > 0 else 12
        sharpe = (avg / std) * np.sqrt(min(tpy, 52)) if std > 0 else 0

        print(f"  {thresh:>+10.0f} {len(ft):>4} {wr:>5.1%} {avg:>+9.5f} "
              f"{total:>+9.5f} {sharpe:>6.2f}")

    # ---- Recommendation ----
    print(f"\n{'=' * 75}")
    print("RECOMMENDATION")
    print(f"{'=' * 75}")

    # Find threshold that maximizes Sharpe with >= 10 trades
    best_thresh = None
    best_sharpe = -999
    for thresh in range(-30, 35, 2):
        ft = [t for t in trades if t.iv_rv_spread >= thresh]
        if len(ft) < 10:
            continue
        pnls_f = [t.pnl for t in ft]
        avg = np.mean(pnls_f)
        std = np.std(pnls_f)
        days = (ft[-1].entry_date - ft[0].entry_date).days
        tpy = len(ft) * 365 / days if days > 0 else 12
        sharpe = (avg / std) * np.sqrt(min(tpy, 52)) if std > 0 else 0
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_thresh = thresh

    if best_thresh is not None:
        print(f"\n  Best min_spread threshold (by Sharpe, N>=10): {best_thresh}")
        print(f"  Sharpe at that threshold: {best_sharpe:.2f}")
        if best_thresh < 16:
            print(f"\n  Current ETH high_iv_spread_threshold = 16.0")
            print(f"  Data suggests lowering to {best_thresh} or removing spread requirement")
            print(f"  for IC entries would improve performance.")
    else:
        print("\n  Insufficient data for threshold optimization.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
