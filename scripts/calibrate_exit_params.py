#!/usr/bin/env python
"""Calibrate exit parameters (profit target, loss limit) and entry deltas for IC and Wheel.

Tests parameter combinations over historical ETH data using Black-Scholes
option pricing to find optimal values for:

Iron Condor:
- profit_target (25%, 50%, 75%)
- loss_limit (100%, 150%, 200%, 300%)
- short_delta (0.10, 0.15, 0.20, 0.25)

Wheel (CSP):
- profit_target (25%, 50%, 75%)
- loss_limit (100%, 150%, 200%, 300%)
- target_delta (0.15, 0.20, 0.25, 0.30)
- DTE range (21-35, 30-45, 35-50, 40-55)

Methodology:
1. For each historical day, simulate strategy entry if IV Rank conditions met
2. Track position through exit conditions using BS-priced options
3. Measure P&L, win rate, Sharpe ratio for each parameter combination
4. Recommend parameters with best risk-adjusted returns

Usage:
    python scripts/calibrate_exit_params.py
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient


# =============================================================================
# BLACK-SCHOLES OPTION PRICING
# =============================================================================


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put price."""
    if T <= 0:
        return max(K - S, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return max(0, K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes call price."""
    if T <= 0:
        return max(S - K, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return max(0, S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes delta."""
    if T <= 0:
        if option_type == "put":
            return -1.0 if K > S else 0.0
        return 1.0 if S > K else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    if option_type == "put":
        return norm.cdf(d1) - 1
    return norm.cdf(d1)


def find_strike_by_delta(
    S: float, T: float, r: float, sigma: float, target_delta: float, option_type: str,
) -> float:
    """Find strike price that gives target delta using bisection."""
    if option_type == "put":
        # Put delta is negative; search OTM puts (K < S)
        # As K increases toward S: delta goes from ~0 to ~-0.5
        low, high = S * 0.3, S * 1.0
        for _ in range(60):
            mid = (low + high) / 2
            d = bs_delta(S, mid, T, r, sigma, "put")
            if d < target_delta:  # Too close to ATM, lower the strike
                high = mid
            else:  # Too far OTM, raise the strike
                low = mid
        return (low + high) / 2
    else:
        # Call delta is positive; search OTM calls (K > S)
        # As K increases from S: delta goes from ~0.5 to ~0
        low, high = S * 1.0, S * 2.0
        for _ in range(60):
            mid = (low + high) / 2
            d = bs_delta(S, mid, T, r, sigma, "call")
            if d > target_delta:  # Too close to ATM, raise the strike
                low = mid
            else:  # Too far OTM, lower the strike
                high = mid
        return (low + high) / 2


def get_iv_with_term_structure(base_dvol: float, dte: int) -> float:
    """Apply term structure adjustment to DVOL."""
    anchor_dte = 30
    if base_dvol > 60:
        slope = -0.002
    elif base_dvol < 40:
        slope = 0.0015
    else:
        slope = 0.0005
    days_from_anchor = dte - anchor_dte
    adjustment = 1 + np.clip(slope * days_from_anchor, -0.05, 0.05)
    return base_dvol * adjustment


# =============================================================================
# IRON CONDOR SIMULATION
# =============================================================================


@dataclass
class ICParams:
    """Iron Condor parameters to test."""
    profit_target: float
    loss_limit: float
    short_delta: float
    wing_delta: float = 0.05
    dte: int = 39  # Middle of calibrated 23-55 range
    min_iv_rank: float = 0.60


@dataclass
class Trade:
    """Generic trade result."""
    entry_date: datetime
    exit_date: Optional[datetime] = None
    pnl: Optional[float] = None
    exit_reason: Optional[str] = None


@dataclass
class SimResult:
    """Simulation result."""
    label: str
    params: dict
    trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    sharpe: float
    profit_factor: float
    trades_per_year: float
    avg_hold_days: float
    max_drawdown: float


def simulate_iron_condor(
    prices: list[float],
    dvols: list[float],
    iv_ranks: list[float],
    timestamps: list[datetime],
    params: ICParams,
) -> SimResult:
    """Simulate iron condor strategy."""
    trades: list[Trade] = []
    in_position = False
    entry_idx = 0
    entry_premium = 0.0
    entry_price = 0.0
    short_put_k = 0.0
    long_put_k = 0.0
    short_call_k = 0.0
    long_call_k = 0.0
    entry_dte = 0
    r = 0.0

    start_idx = 252

    for i in range(start_idx, len(prices)):
        price = prices[i]
        dvol = dvols[i]
        iv_rank = iv_ranks[i]
        sigma = dvol / 100

        if in_position:
            days_held = (timestamps[i] - timestamps[entry_idx]).days
            dte_remaining = max(0, entry_dte - days_held)

            # Calculate current spread value
            iv_adj = get_iv_with_term_structure(dvol, dte_remaining) / 100
            T = dte_remaining / 365

            sp = bs_put_price(price, short_put_k, T, r, iv_adj)
            lp = bs_put_price(price, long_put_k, T, r, iv_adj)
            sc = bs_call_price(price, short_call_k, T, r, iv_adj)
            lc = bs_call_price(price, long_call_k, T, r, iv_adj)

            # Cost to close (buy back shorts, sell longs)
            close_cost = (sp - lp + sc - lc) / price  # Normalize
            current_pnl = entry_premium - close_cost

            exit_reason = None

            # DTE exit
            if dte_remaining <= 7:
                exit_reason = "dte"

            # Profit target
            if entry_premium > 0:
                profit_pct = current_pnl / entry_premium
                if profit_pct >= params.profit_target:
                    exit_reason = "profit"

            # Loss limit
            if entry_premium > 0:
                loss_pct = -current_pnl / entry_premium
                if loss_pct >= params.loss_limit:
                    exit_reason = "loss"

            if exit_reason:
                trades.append(Trade(
                    entry_date=timestamps[entry_idx],
                    exit_date=timestamps[i],
                    pnl=current_pnl,
                    exit_reason=exit_reason,
                ))
                in_position = False

        if not in_position and iv_rank >= params.min_iv_rank:
            T = params.dte / 365
            iv_adj = get_iv_with_term_structure(dvol, params.dte) / 100

            # Find strikes by delta
            short_put_k = find_strike_by_delta(price, T, r, iv_adj, -params.short_delta, "put")
            long_put_k = find_strike_by_delta(price, T, r, iv_adj, -params.wing_delta, "put")
            short_call_k = find_strike_by_delta(price, T, r, iv_adj, params.short_delta, "call")
            long_call_k = find_strike_by_delta(price, T, r, iv_adj, params.wing_delta, "call")

            # Calculate premium
            sp = bs_put_price(price, short_put_k, T, r, iv_adj)
            lp = bs_put_price(price, long_put_k, T, r, iv_adj)
            sc = bs_call_price(price, short_call_k, T, r, iv_adj)
            lc = bs_call_price(price, long_call_k, T, r, iv_adj)

            entry_premium = (sp - lp + sc - lc) / price
            if entry_premium > 0:
                in_position = True
                entry_idx = i
                entry_price = price
                entry_dte = params.dte

    return _calculate_result(
        f"IC sd={params.short_delta} pt={params.profit_target} ll={params.loss_limit}",
        {"short_delta": params.short_delta, "profit_target": params.profit_target,
         "loss_limit": params.loss_limit},
        trades, timestamps,
    )


# =============================================================================
# WHEEL (CSP) SIMULATION
# =============================================================================


@dataclass
class WheelParams:
    """Wheel CSP parameters to test."""
    profit_target: float
    loss_limit: float
    target_delta: float
    dte_min: int
    dte_max: int
    min_iv_rank: float = 0.46  # ETH calibrated


def simulate_wheel(
    prices: list[float],
    dvols: list[float],
    iv_ranks: list[float],
    timestamps: list[datetime],
    params: WheelParams,
) -> SimResult:
    """Simulate wheel (CSP) strategy."""
    trades: list[Trade] = []
    in_position = False
    entry_idx = 0
    entry_premium = 0.0
    strike = 0.0
    entry_dte = 0
    r = 0.0

    target_dte = (params.dte_min + params.dte_max) // 2
    start_idx = 252

    for i in range(start_idx, len(prices)):
        price = prices[i]
        dvol = dvols[i]
        iv_rank = iv_ranks[i]

        if in_position:
            days_held = (timestamps[i] - timestamps[entry_idx]).days
            dte_remaining = max(0, entry_dte - days_held)

            iv_adj = get_iv_with_term_structure(dvol, dte_remaining) / 100
            T = dte_remaining / 365

            # Current put value (what we'd pay to buy back)
            current_value = bs_put_price(price, strike, T, r, iv_adj) / price
            current_pnl = entry_premium - current_value

            exit_reason = None

            # DTE exit
            if dte_remaining <= 7:
                exit_reason = "dte"

            # Profit target
            if entry_premium > 0:
                profit_pct = current_pnl / entry_premium
                if profit_pct >= params.profit_target:
                    exit_reason = "profit"

            # Loss limit
            if entry_premium > 0:
                loss_pct = -current_pnl / entry_premium
                if loss_pct >= params.loss_limit:
                    exit_reason = "loss"

            if exit_reason:
                trades.append(Trade(
                    entry_date=timestamps[entry_idx],
                    exit_date=timestamps[i],
                    pnl=current_pnl,
                    exit_reason=exit_reason,
                ))
                in_position = False

        if not in_position and iv_rank >= params.min_iv_rank:
            iv_adj = get_iv_with_term_structure(dvol, target_dte) / 100
            T = target_dte / 365

            strike = find_strike_by_delta(price, T, r, iv_adj, -params.target_delta, "put")
            entry_premium = bs_put_price(price, strike, T, r, iv_adj) / price

            if entry_premium > 0.001:  # Minimum premium threshold
                in_position = True
                entry_idx = i
                entry_dte = target_dte

    return _calculate_result(
        f"Wheel d={params.target_delta} dte={params.dte_min}-{params.dte_max} pt={params.profit_target} ll={params.loss_limit}",
        {"target_delta": params.target_delta, "dte_min": params.dte_min,
         "dte_max": params.dte_max, "profit_target": params.profit_target,
         "loss_limit": params.loss_limit},
        trades, timestamps,
    )


# =============================================================================
# METRICS
# =============================================================================


def _calculate_result(
    label: str,
    params: dict,
    trades: list[Trade],
    timestamps: list[datetime],
) -> SimResult:
    """Calculate performance metrics."""
    completed = [t for t in trades if t.pnl is not None]

    if len(completed) < 5:
        return SimResult(
            label=label, params=params, trades=len(completed),
            win_rate=0, avg_pnl=0, total_pnl=0, sharpe=0,
            profit_factor=0, trades_per_year=0, avg_hold_days=0,
            max_drawdown=0,
        )

    pnls = [t.pnl for t in completed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls)
    avg_pnl = float(np.mean(pnls))

    # Sharpe
    if np.std(pnls) > 0:
        sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(len(completed)))
    else:
        sharpe = 0

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.0001
    profit_factor = gross_profit / gross_loss

    # Trades per year
    years = (timestamps[-1] - timestamps[0]).days / 365
    trades_per_year = len(completed) / years if years > 0 else 0

    # Average hold days
    hold_days = [(t.exit_date - t.entry_date).days for t in completed if t.exit_date]
    avg_hold_days = float(np.mean(hold_days)) if hold_days else 0

    # Max drawdown
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    max_drawdown = float(np.max(peak - cumulative))

    return SimResult(
        label=label, params=params, trades=len(completed),
        win_rate=win_rate, avg_pnl=avg_pnl, total_pnl=total_pnl,
        sharpe=sharpe, profit_factor=profit_factor,
        trades_per_year=trades_per_year, avg_hold_days=avg_hold_days,
        max_drawdown=max_drawdown,
    )


# =============================================================================
# DATA FETCHING
# =============================================================================


async def fetch_historical_data(client: DeribitClient, currency: str = "ETH"):
    """Fetch historical price and DVOL data."""
    print(f"Fetching {currency} historical data...")

    dvol_raw = await client.get_volatility_index(currency=currency, resolution=86400)
    dvol_values = [c[4] if len(c) > 4 else c[1] for c in dvol_raw]
    dvol_timestamps = [datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc) for c in dvol_raw]

    price_raw = await client.get_tradingview_chart_data(
        instrument_name=f"{currency}-PERPETUAL", resolution="1D"
    )
    prices = price_raw.get("close", [])
    price_timestamps = [
        datetime.fromtimestamp(t / 1000, tz=timezone.utc) for t in price_raw.get("ticks", [])
    ]

    print(f"  DVOL: {len(dvol_values)} days, Prices: {len(prices)} days")

    dvol_by_date = {ts.date(): v for ts, v in zip(dvol_timestamps, dvol_values)}
    price_by_date = {ts.date(): v for ts, v in zip(price_timestamps, prices)}

    common_dates = sorted(set(dvol_by_date.keys()) & set(price_by_date.keys()))
    print(f"  Common dates: {len(common_dates)} ({common_dates[0]} to {common_dates[-1]})")

    aligned_prices = [price_by_date[d] for d in common_dates]
    aligned_dvols = [dvol_by_date[d] for d in common_dates]
    aligned_timestamps = [
        datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
        for d in common_dates
    ]

    # IV Rank (252-day lookback)
    iv_ranks = []
    for i, dvol in enumerate(aligned_dvols):
        if i < 252:
            iv_ranks.append(0.5)
        else:
            hist = aligned_dvols[i - 252 : i]
            iv_min, iv_max = min(hist), max(hist)
            if iv_max == iv_min:
                iv_ranks.append(0.5)
            else:
                iv_ranks.append((dvol - iv_min) / (iv_max - iv_min))

    return aligned_prices, aligned_dvols, iv_ranks, aligned_timestamps


# =============================================================================
# MAIN
# =============================================================================


def print_results_table(title: str, results: list[SimResult], top_n: int = 15):
    """Print sorted results table."""
    # Filter to results with enough trades
    valid = [r for r in results if r.trades >= 10]
    valid.sort(key=lambda r: r.sharpe, reverse=True)

    print(f"\n{'=' * 90}")
    print(f"{title} (sorted by Sharpe, min 10 trades)")
    print(f"{'=' * 90}")
    print(f"{'Rank':<5} {'Sharpe':>7} {'WinR':>6} {'PF':>6} {'Trades':>7} "
          f"{'Tr/Yr':>6} {'AvgPnL':>9} {'HoldD':>6} {'MaxDD':>9} {'Params'}")
    print("-" * 90)

    for i, r in enumerate(valid[:top_n], 1):
        params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
        print(f"#{i:<4} {r.sharpe:>7.2f} {r.win_rate:>5.1%} {r.profit_factor:>6.2f} "
              f"{r.trades:>7} {r.trades_per_year:>6.1f} {r.avg_pnl*100:>8.3f}% "
              f"{r.avg_hold_days:>6.1f} {r.max_drawdown*100:>8.3f}% {params_str}")

    # Parameter frequency in top results
    top_results = valid[:min(20, len(valid))]
    if not top_results:
        print("  No valid results")
        return valid

    print(f"\nParameter frequency in top {len(top_results)} results:")
    param_keys = list(top_results[0].params.keys())
    for key in param_keys:
        counts: dict = {}
        for r in top_results:
            v = r.params[key]
            counts[v] = counts.get(v, 0) + 1
        print(f"\n  {key}:")
        for v, c in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {v}: {c}/{len(top_results)} ({c/len(top_results)*100:.0f}%)")

    return valid


async def main():
    print("=" * 90)
    print("EXIT PARAMETER CALIBRATION — Iron Condor & Wheel")
    print("=" * 90)

    client = DeribitClient()

    try:
        prices, dvols, iv_ranks, timestamps = await fetch_historical_data(client, "ETH")

        # =====================================================================
        # IRON CONDOR CALIBRATION
        # =====================================================================

        print(f"\n{'=' * 90}")
        print("IRON CONDOR: Testing profit_target × loss_limit × short_delta")
        print(f"{'=' * 90}")

        ic_results: list[SimResult] = []
        ic_params_list = []

        for pt in [0.25, 0.40, 0.50, 0.60, 0.75]:
            for ll in [1.0, 1.5, 2.0, 3.0]:
                for sd in [0.10, 0.15, 0.20, 0.25]:
                    ic_params_list.append(ICParams(
                        profit_target=pt, loss_limit=ll, short_delta=sd,
                    ))

        print(f"Testing {len(ic_params_list)} combinations...")
        for i, params in enumerate(ic_params_list):
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(ic_params_list)}")
            ic_results.append(simulate_iron_condor(prices, dvols, iv_ranks, timestamps, params))

        ic_valid = print_results_table("IRON CONDOR RESULTS", ic_results)

        # =====================================================================
        # WHEEL (CSP) CALIBRATION
        # =====================================================================

        print(f"\n{'=' * 90}")
        print("WHEEL CSP: Testing profit_target × loss_limit × target_delta × DTE")
        print(f"{'=' * 90}")

        wheel_results: list[SimResult] = []
        wheel_params_list = []

        dte_ranges = [(21, 35), (30, 45), (35, 50), (40, 55)]

        for pt in [0.25, 0.40, 0.50, 0.60, 0.75]:
            for ll in [1.0, 1.5, 2.0, 3.0]:
                for td in [0.15, 0.20, 0.25, 0.30]:
                    for dte_min, dte_max in dte_ranges:
                        wheel_params_list.append(WheelParams(
                            profit_target=pt, loss_limit=ll,
                            target_delta=td, dte_min=dte_min, dte_max=dte_max,
                        ))

        print(f"Testing {len(wheel_params_list)} combinations...")
        for i, params in enumerate(wheel_params_list):
            if i % 50 == 0:
                print(f"  Progress: {i}/{len(wheel_params_list)}")
            wheel_results.append(simulate_wheel(prices, dvols, iv_ranks, timestamps, params))

        wheel_valid = print_results_table("WHEEL CSP RESULTS", wheel_results)

        # =====================================================================
        # SUMMARY
        # =====================================================================

        print(f"\n{'=' * 90}")
        print("SUMMARY — RECOMMENDED PARAMETERS")
        print(f"{'=' * 90}")

        if ic_valid:
            best_ic = ic_valid[0]
            print(f"\nIRON CONDOR (best Sharpe={best_ic.sharpe:.2f}):")
            for k, v in best_ic.params.items():
                print(f"  {k}: {v}")
            print(f"  Win Rate: {best_ic.win_rate:.1%}, PF: {best_ic.profit_factor:.2f}, "
                  f"Trades/Yr: {best_ic.trades_per_year:.1f}")

        if wheel_valid:
            best_wh = wheel_valid[0]
            print(f"\nWHEEL CSP (best Sharpe={best_wh.sharpe:.2f}):")
            for k, v in best_wh.params.items():
                print(f"  {k}: {v}")
            print(f"  Win Rate: {best_wh.win_rate:.1%}, PF: {best_wh.profit_factor:.2f}, "
                  f"Trades/Yr: {best_wh.trades_per_year:.1f}")

    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
