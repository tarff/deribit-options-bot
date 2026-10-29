#!/usr/bin/env python
"""Calibrate Calendar Spread strategy parameters using historical simulation.

This script simulates calendar spread performance over historical ETH data to find
optimal parameters for:
- Short leg DTE range
- Long leg DTE range
- Exit price move threshold
- Profit target
- IV Rank entry threshold

Since we don't have historical option chain data, we use Black-Scholes to estimate
option prices from underlying price + DVOL, with a term structure model for
front vs back month IV.

Methodology:
1. For each historical day, simulate calendar spread entry if conditions met
2. Track position through expiry or exit conditions
3. Measure P&L, win rate, Sharpe ratio for each parameter combination
4. Recommend parameters with best risk-adjusted returns

Usage:
    python scripts/calibrate_calendar_spread.py
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    """Calculate Black-Scholes put option price.

    Args:
        S: Underlying price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Implied volatility (annualized, as decimal)

    Returns:
        Put option price
    """
    if T <= 0:
        return max(K - S, 0)  # Intrinsic value at expiry

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return max(0, put_price)


def bs_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "put") -> float:
    """Calculate option theta (time decay per day).

    Args:
        S: Underlying price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Implied volatility (annualized, as decimal)
        option_type: 'put' or 'call'

    Returns:
        Theta (negative = losing value per day)
    """
    if T <= 0:
        return 0

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    # Theta per year
    theta_year = (
        -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        - r * K * np.exp(-r * T) * norm.cdf(-d2)
    )

    # Convert to per day
    return theta_year / 365


# =============================================================================
# TERM STRUCTURE MODEL
# =============================================================================


def get_iv_with_term_structure(base_dvol: float, dte: int) -> float:
    """Apply term structure adjustment to DVOL.

    Crypto options typically show:
    - Backwardation in high vol: front month IV > back month IV
    - Contango in low vol: front month IV < back month IV

    This is a simplified model based on typical crypto vol term structure.
    The adjustment is small (within 5%) as crypto term structure is often flat.

    Args:
        base_dvol: Current DVOL level
        dte: Days to expiry

    Returns:
        Adjusted IV for the given DTE
    """
    # Anchor around 30-day (DVOL is roughly 30-day IV)
    anchor_dte = 30

    # Term structure slope depends on DVOL level
    # High DVOL (>60): slight backwardation, front month higher
    # Low DVOL (<40): slight contango, back month higher
    # Medium: relatively flat

    if base_dvol > 60:
        # Backwardation: -0.2% per 10 days from anchor
        slope = -0.002
    elif base_dvol < 40:
        # Contango: +0.15% per 10 days from anchor
        slope = 0.0015
    else:
        # Relatively flat
        slope = 0.0005

    # Apply adjustment (capped at +/- 5%)
    days_from_anchor = dte - anchor_dte
    adjustment = 1 + np.clip(slope * days_from_anchor, -0.05, 0.05)

    return base_dvol * adjustment


# =============================================================================
# CALENDAR SPREAD SIMULATION
# =============================================================================


@dataclass
class CalendarSpreadTrade:
    """Single calendar spread trade for simulation."""

    entry_date: datetime
    entry_price: float  # Underlying price at entry
    strike: float
    short_dte: int
    long_dte: int
    entry_debit: float  # Net debit paid (in underlying terms, e.g., ETH)
    entry_dvol: float
    entry_iv_rank: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_value: Optional[float] = None
    pnl: Optional[float] = None
    exit_reason: Optional[str] = None


@dataclass
class CalendarSpreadParams:
    """Parameters to test for calendar spread."""

    short_dte_min: int
    short_dte_max: int
    long_dte_min: int
    long_dte_max: int
    exit_price_move_pct: float
    profit_target: float
    max_iv_rank: float  # Entry when IV Rank below this


@dataclass
class SimulationResult:
    """Results from a single parameter combination."""

    params: CalendarSpreadParams
    trades: list[CalendarSpreadTrade]
    total_pnl: float
    win_rate: float
    avg_pnl: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    sharpe_ratio: float
    trades_per_year: float
    profit_factor: float


def simulate_calendar_spread(
    prices: list[float],
    dvols: list[float],
    iv_ranks: list[float],
    timestamps: list[datetime],
    params: CalendarSpreadParams,
) -> SimulationResult:
    """Simulate calendar spread strategy over historical data.

    Args:
        prices: Daily underlying prices
        dvols: Daily DVOL values
        iv_ranks: Daily IV Rank values
        timestamps: Daily timestamps
        params: Strategy parameters to test

    Returns:
        SimulationResult with all trades and metrics
    """
    trades: list[CalendarSpreadTrade] = []
    active_trade: Optional[CalendarSpreadTrade] = None
    r = 0.0  # Risk-free rate (simplified for crypto)

    # Need enough data for IV Rank calculation
    start_idx = 252  # Skip first year for IV Rank warmup

    for i in range(start_idx, len(prices)):
        price = prices[i]
        dvol = dvols[i]
        iv_rank = iv_ranks[i]
        ts = timestamps[i]

        # Check if we have an active trade
        if active_trade is not None:
            # Days since entry
            days_held = (ts - active_trade.entry_date).days

            # Check exit conditions
            exit_reason = None

            # 1. Short leg expired
            if days_held >= active_trade.short_dte:
                exit_reason = "short_expired"

            # 2. Price moved too far from strike
            price_move = abs(price - active_trade.strike) / active_trade.strike
            if price_move > params.exit_price_move_pct:
                exit_reason = f"price_move_{price_move:.1%}"

            # 3. Calculate current spread value and check profit target
            short_dte_remaining = max(0, active_trade.short_dte - days_held)
            long_dte_remaining = max(0, active_trade.long_dte - days_held)

            # Get IVs with term structure
            short_iv = get_iv_with_term_structure(dvol, short_dte_remaining) / 100
            long_iv = get_iv_with_term_structure(dvol, long_dte_remaining) / 100

            # Calculate current option prices
            short_price = bs_put_price(
                price, active_trade.strike, short_dte_remaining / 365, r, short_iv
            )
            long_price = bs_put_price(
                price, active_trade.strike, long_dte_remaining / 365, r, long_iv
            )

            # Spread value = long - short (what we'd get closing)
            # Normalize to underlying terms (divide by underlying price)
            current_value = (long_price - short_price) / price

            # Profit check
            if active_trade.entry_debit > 0:
                profit_pct = (current_value - active_trade.entry_debit) / active_trade.entry_debit
                if profit_pct >= params.profit_target:
                    exit_reason = f"profit_target_{profit_pct:.1%}"

            # Exit if any condition met
            if exit_reason:
                active_trade.exit_date = ts
                active_trade.exit_price = price
                active_trade.exit_value = current_value
                active_trade.pnl = current_value - active_trade.entry_debit
                active_trade.exit_reason = exit_reason
                trades.append(active_trade)
                active_trade = None

        # Check for new entry (only if not in position)
        if active_trade is None:
            # Entry condition: IV Rank below threshold
            if iv_rank <= params.max_iv_rank:
                # Calculate target DTEs (middle of range)
                target_short_dte = (params.short_dte_min + params.short_dte_max) // 2
                target_long_dte = (params.long_dte_min + params.long_dte_max) // 2

                # ATM strike
                strike = price

                # Get IVs with term structure
                short_iv = get_iv_with_term_structure(dvol, target_short_dte) / 100
                long_iv = get_iv_with_term_structure(dvol, target_long_dte) / 100

                # Calculate option prices
                short_price = bs_put_price(price, strike, target_short_dte / 365, r, short_iv)
                long_price = bs_put_price(price, strike, target_long_dte / 365, r, long_iv)

                # Net debit (normalized to underlying terms)
                net_debit = (long_price - short_price) / price

                # Only enter if debit is reasonable (0.1% to 5% of underlying)
                if 0.001 < net_debit < 0.05:
                    active_trade = CalendarSpreadTrade(
                        entry_date=ts,
                        entry_price=price,
                        strike=strike,
                        short_dte=target_short_dte,
                        long_dte=target_long_dte,
                        entry_debit=net_debit,
                        entry_dvol=dvol,
                        entry_iv_rank=iv_rank,
                    )

    # Close any remaining trade at end of data
    if active_trade is not None:
        # Mark as incomplete
        active_trade.exit_reason = "end_of_data"
        active_trade.exit_date = timestamps[-1]
        active_trade.exit_price = prices[-1]
        active_trade.pnl = 0  # Neutral for incomplete trades
        trades.append(active_trade)

    # Calculate metrics
    return calculate_metrics(trades, params, timestamps)


def calculate_metrics(
    trades: list[CalendarSpreadTrade],
    params: CalendarSpreadParams,
    timestamps: list[datetime],
) -> SimulationResult:
    """Calculate performance metrics from trades."""
    if not trades:
        return SimulationResult(
            params=params,
            trades=[],
            total_pnl=0,
            win_rate=0,
            avg_pnl=0,
            avg_win=0,
            avg_loss=0,
            max_drawdown=0,
            sharpe_ratio=0,
            trades_per_year=0,
            profit_factor=0,
        )

    # Filter to completed trades
    completed = [t for t in trades if t.exit_reason != "end_of_data" and t.pnl is not None]

    if not completed:
        return SimulationResult(
            params=params,
            trades=trades,
            total_pnl=0,
            win_rate=0,
            avg_pnl=0,
            avg_win=0,
            avg_loss=0,
            max_drawdown=0,
            sharpe_ratio=0,
            trades_per_year=0,
            profit_factor=0,
        )

    pnls = [t.pnl for t in completed if t.pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_pnl = np.mean(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0

    # Max drawdown (cumulative)
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0

    # Sharpe ratio (annualized, assuming ~20 trades/year)
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe_ratio = float(np.mean(pnls) / np.std(pnls) * np.sqrt(20))
    else:
        sharpe_ratio = 0

    # Trades per year
    if len(timestamps) > 1:
        years = (timestamps[-1] - timestamps[0]).days / 365
        trades_per_year = len(completed) / years if years > 0 else 0
    else:
        trades_per_year = 0

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return SimulationResult(
        params=params,
        trades=trades,
        total_pnl=total_pnl,
        win_rate=win_rate,
        avg_pnl=float(avg_pnl),
        avg_win=float(avg_win),
        avg_loss=float(avg_loss),
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        trades_per_year=trades_per_year,
        profit_factor=profit_factor,
    )


# =============================================================================
# PARAMETER GRID
# =============================================================================


def generate_parameter_grid() -> list[CalendarSpreadParams]:
    """Generate parameter combinations to test."""
    params_list = []

    # Short DTE ranges to test
    short_dte_ranges = [
        (7, 14),
        (14, 21),
        (21, 28),
        (14, 28),
    ]

    # Long DTE ranges to test
    long_dte_ranges = [
        (30, 45),
        (45, 60),
        (60, 90),
        (45, 75),
    ]

    # Exit price move thresholds
    exit_moves = [0.05, 0.08, 0.10, 0.12, 0.15]

    # Profit targets
    profit_targets = [0.25, 0.50, 0.75, 1.00]

    # IV Rank entry thresholds
    iv_rank_thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.46, 0.50]

    for short_min, short_max in short_dte_ranges:
        for long_min, long_max in long_dte_ranges:
            # Ensure long leg is further out than short
            if long_min <= short_max:
                continue

            for exit_move in exit_moves:
                for profit_target in profit_targets:
                    for iv_rank in iv_rank_thresholds:
                        params_list.append(
                            CalendarSpreadParams(
                                short_dte_min=short_min,
                                short_dte_max=short_max,
                                long_dte_min=long_min,
                                long_dte_max=long_max,
                                exit_price_move_pct=exit_move,
                                profit_target=profit_target,
                                max_iv_rank=iv_rank,
                            )
                        )

    return params_list


# =============================================================================
# MAIN
# =============================================================================


async def fetch_historical_data(client: DeribitClient, currency: str = "ETH"):
    """Fetch historical price and DVOL data."""
    print(f"Fetching {currency} historical data...")

    # Fetch DVOL
    dvol_raw = await client.get_volatility_index(currency=currency, resolution=86400)
    dvol_values = [c[4] if len(c) > 4 else c[1] for c in dvol_raw]
    dvol_timestamps = [datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc) for c in dvol_raw]

    # Fetch price data
    price_raw = await client.get_tradingview_chart_data(
        instrument_name=f"{currency}-PERPETUAL", resolution="1D"
    )
    prices = price_raw.get("close", [])
    price_timestamps = [
        datetime.fromtimestamp(t / 1000, tz=timezone.utc) for t in price_raw.get("ticks", [])
    ]

    print(f"  DVOL: {len(dvol_values)} days")
    print(f"  Prices: {len(prices)} days")

    # Align data by date
    dvol_by_date = {ts.date(): v for ts, v in zip(dvol_timestamps, dvol_values)}
    price_by_date = {ts.date(): v for ts, v in zip(price_timestamps, prices)}

    common_dates = sorted(set(dvol_by_date.keys()) & set(price_by_date.keys()))
    print(f"  Common dates: {len(common_dates)} ({common_dates[0]} to {common_dates[-1]})")

    aligned_prices = [price_by_date[d] for d in common_dates]
    aligned_dvols = [dvol_by_date[d] for d in common_dates]
    aligned_timestamps = [datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc) for d in common_dates]

    # Calculate IV Rank (252-day lookback)
    iv_ranks = []
    for i, dvol in enumerate(aligned_dvols):
        if i < 252:
            iv_ranks.append(0.5)  # Default during warmup
        else:
            historical = aligned_dvols[i - 252 : i]
            iv_min = min(historical)
            iv_max = max(historical)
            if iv_max == iv_min:
                iv_ranks.append(0.5)
            else:
                iv_ranks.append((dvol - iv_min) / (iv_max - iv_min))

    return aligned_prices, aligned_dvols, iv_ranks, aligned_timestamps


async def main():
    """Run calendar spread calibration."""
    print("=" * 70)
    print("CALENDAR SPREAD PARAMETER CALIBRATION")
    print("=" * 70)
    print()
    print("This script simulates calendar spread performance using Black-Scholes")
    print("option pricing with term structure adjustment, then tests parameter")
    print("combinations to find optimal settings.")
    print()

    client = DeribitClient()

    try:
        prices, dvols, iv_ranks, timestamps = await fetch_historical_data(client, "ETH")

        # Generate parameter grid
        params_grid = generate_parameter_grid()
        print(f"\nTesting {len(params_grid)} parameter combinations...")

        # Run simulations
        results: list[SimulationResult] = []
        for i, params in enumerate(params_grid):
            if i % 100 == 0:
                print(f"  Progress: {i}/{len(params_grid)}")

            result = simulate_calendar_spread(prices, dvols, iv_ranks, timestamps, params)
            results.append(result)

        # Filter to results with enough trades
        min_trades = 10
        valid_results = [r for r in results if len(r.trades) >= min_trades]
        print(f"\nResults with >= {min_trades} trades: {len(valid_results)}")

        if not valid_results:
            print("\nNo valid results. Try adjusting the parameter ranges.")
            return

        # Sort by Sharpe ratio (risk-adjusted returns)
        valid_results.sort(key=lambda r: r.sharpe_ratio, reverse=True)

        # Print top 10
        print("\n" + "=" * 70)
        print("TOP 10 PARAMETER COMBINATIONS (by Sharpe Ratio)")
        print("=" * 70)

        for i, r in enumerate(valid_results[:10], 1):
            p = r.params
            print(f"\n#{i}: Sharpe={r.sharpe_ratio:.2f}, Win Rate={r.win_rate:.1%}, "
                  f"PF={r.profit_factor:.2f}, Trades/Yr={r.trades_per_year:.1f}")
            print(f"    Short DTE: {p.short_dte_min}-{p.short_dte_max}, "
                  f"Long DTE: {p.long_dte_min}-{p.long_dte_max}")
            print(f"    Exit Move: {p.exit_price_move_pct:.0%}, "
                  f"Profit Target: {p.profit_target:.0%}, "
                  f"Max IV Rank: {p.max_iv_rank:.0%}")
            print(f"    Avg P&L: {r.avg_pnl*100:.3f}%, "
                  f"Avg Win: {r.avg_win*100:.3f}%, "
                  f"Avg Loss: {r.avg_loss*100:.3f}%")

        # Analyze which parameters appear most in top results
        print("\n" + "=" * 70)
        print("PARAMETER FREQUENCY IN TOP 20 RESULTS")
        print("=" * 70)

        top_n = min(20, len(valid_results))
        top_results = valid_results[:top_n]

        # Short DTE ranges
        short_counts: dict[tuple[int, int], int] = {}
        for r in top_results:
            key = (r.params.short_dte_min, r.params.short_dte_max)
            short_counts[key] = short_counts.get(key, 0) + 1

        print("\nShort DTE ranges:")
        for k, v in sorted(short_counts.items(), key=lambda x: -x[1]):
            print(f"  {k[0]}-{k[1]} days: {v}/{top_n} ({v/top_n*100:.0f}%)")

        # Long DTE ranges
        long_counts: dict[tuple[int, int], int] = {}
        for r in top_results:
            key = (r.params.long_dte_min, r.params.long_dte_max)
            long_counts[key] = long_counts.get(key, 0) + 1

        print("\nLong DTE ranges:")
        for k, v in sorted(long_counts.items(), key=lambda x: -x[1]):
            print(f"  {k[0]}-{k[1]} days: {v}/{top_n} ({v/top_n*100:.0f}%)")

        # Exit price move
        exit_counts: dict[float, int] = {}
        for r in top_results:
            exit_counts[r.params.exit_price_move_pct] = exit_counts.get(r.params.exit_price_move_pct, 0) + 1

        print("\nExit price move thresholds:")
        for k, v in sorted(exit_counts.items(), key=lambda x: -x[1]):
            print(f"  {k:.0%}: {v}/{top_n} ({v/top_n*100:.0f}%)")

        # Profit targets
        profit_counts: dict[float, int] = {}
        for r in top_results:
            profit_counts[r.params.profit_target] = profit_counts.get(r.params.profit_target, 0) + 1

        print("\nProfit targets:")
        for k, v in sorted(profit_counts.items(), key=lambda x: -x[1]):
            print(f"  {k:.0%}: {v}/{top_n} ({v/top_n*100:.0f}%)")

        # IV Rank thresholds
        ivr_counts: dict[float, int] = {}
        for r in top_results:
            ivr_counts[r.params.max_iv_rank] = ivr_counts.get(r.params.max_iv_rank, 0) + 1

        print("\nIV Rank entry thresholds:")
        for k, v in sorted(ivr_counts.items(), key=lambda x: -x[1]):
            print(f"  <= {k:.0%}: {v}/{top_n} ({v/top_n*100:.0f}%)")

        # Final recommendations
        print("\n" + "=" * 70)
        print("RECOMMENDATIONS")
        print("=" * 70)

        best = valid_results[0]
        p = best.params

        print(f"""
Based on simulation of {len(prices)} days of ETH data with {len(params_grid)} parameter combinations:

RECOMMENDED PARAMETERS:
-----------------------
Short DTE range:     {p.short_dte_min}-{p.short_dte_max} days
Long DTE range:      {p.long_dte_min}-{p.long_dte_max} days
Exit price move:     {p.exit_price_move_pct:.0%}
Profit target:       {p.profit_target:.0%}
Max IV Rank:         {p.max_iv_rank:.0%} (enter when IV Rank <= this)

EXPECTED PERFORMANCE:
---------------------
Sharpe Ratio:        {best.sharpe_ratio:.2f}
Win Rate:            {best.win_rate:.1%}
Profit Factor:       {best.profit_factor:.2f}
Trades/Year:         {best.trades_per_year:.1f}
Avg P&L per trade:   {best.avg_pnl*100:.3f}%

CAVEATS:
--------
- Simulation uses Black-Scholes (may differ from actual market prices)
- Term structure model is simplified
- Does not account for bid-ask spread or slippage
- Does not account for funding/margin costs
- Past performance does not guarantee future results
""")

        # Print trade-level analysis for best params
        print("\n" + "=" * 70)
        print("DETAILED TRADE ANALYSIS (Best Parameters)")
        print("=" * 70)

        exit_reasons: dict[str, int] = {}
        for t in best.trades:
            reason = t.exit_reason.split("_")[0] if t.exit_reason else "unknown"
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        print("\nExit reason distribution:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pct = count / len(best.trades) * 100
            print(f"  {reason}: {count} ({pct:.1f}%)")

        # P&L by exit reason
        print("\nP&L by exit reason:")
        for reason in exit_reasons.keys():
            trades = [t for t in best.trades if t.exit_reason and t.exit_reason.startswith(reason)]
            pnls = [t.pnl for t in trades if t.pnl is not None]
            if pnls:
                avg = np.mean(pnls) * 100
                win_pct = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                print(f"  {reason}: Avg P&L={avg:.3f}%, Win Rate={win_pct:.1f}%")

    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
