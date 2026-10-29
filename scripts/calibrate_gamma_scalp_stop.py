#!/usr/bin/env python
"""Calibrate gamma scalp long-debit stop loss from historical ETH data.

Methodology:
1. Fetch daily ETH price + DVOL from Deribit (existing infrastructure).
2. Identify entry days where realized volatility (7d) > min_rv (gamma scalp
   entry condition).
3. For each entry day, simulate buying an ATM straddle with target_dte days
   to expiry. Track the straddle's mark-to-market value daily via
   Black-Scholes until DTE exit (DTE <= exit_dte) or expiry.
4. Compute the worst (max) intra-trade drawdown as a fraction of the
   entry debit.
5. Report drawdown percentiles. The chosen ``long_debit_stop_loss_pct``
   should be calibrated against this distribution.

CONSERVATIVE BIAS: This simulation omits the delta-hedge (scalp) PnL stream
that real gamma scalping adds. Scalp gains reduce drawdowns, so the
percentiles reported here are an UPPER BOUND on production drawdowns.
A production stop calibrated against this distribution is therefore
intentionally cautious.

Usage:
    python scripts/calibrate_gamma_scalp_stop.py
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.calibrate_exit_params import (
    bs_call_price,
    bs_put_price,
    fetch_historical_data,
    get_iv_with_term_structure,
)
from src.data.deribit_client import DeribitClient


# Gamma scalp parameters held constant during this sweep (from factory.py).
TARGET_DTE = 21
EXIT_DTE = 7
MIN_RV = {"BTC": 40.0, "ETH": 54.0}  # from factory.py
RV_WINDOW = 7


@dataclass
class TradeOutcome:
    entry_date: datetime
    exit_date: datetime
    days_held: int
    entry_debit: float
    exit_value: float
    max_drawdown_pct: float  # peak underwater / entry_debit
    final_pnl_pct: float
    exit_reason: str


def realized_vol(prices: list[float], lookback: int = RV_WINDOW) -> list[float]:
    """Rolling annualized realized volatility (close-to-close), in percent."""
    out: list[float] = [0.0] * len(prices)
    for i in range(lookback, len(prices)):
        window = prices[i - lookback : i + 1]
        rets = np.diff(np.log(window))
        if len(rets) == 0 or np.std(rets) == 0:
            out[i] = 0.0
        else:
            out[i] = float(np.std(rets) * np.sqrt(365) * 100)
    return out


def simulate_straddle_hold(
    entry_idx: int,
    prices: list[float],
    dvols: list[float],
    timestamps: list[datetime],
) -> TradeOutcome | None:
    """Buy ATM straddle on entry_idx, track MTM daily until DTE exit."""
    entry_price = prices[entry_idx]
    entry_dvol = dvols[entry_idx]
    strike = entry_price  # ATM
    r = 0.0
    T0 = TARGET_DTE / 365

    iv0 = get_iv_with_term_structure(entry_dvol, TARGET_DTE) / 100
    put0 = bs_put_price(entry_price, strike, T0, r, iv0)
    call0 = bs_call_price(entry_price, strike, T0, r, iv0)
    entry_debit = (put0 + call0) / entry_price  # normalize to fraction of underlying

    if entry_debit <= 0:
        return None

    max_dd = 0.0
    final_value = entry_debit
    final_idx = entry_idx
    exit_reason = "end_of_data"

    for j in range(entry_idx + 1, len(prices)):
        days_held = (timestamps[j] - timestamps[entry_idx]).days
        dte_remaining = TARGET_DTE - days_held
        if dte_remaining <= EXIT_DTE:
            exit_reason = "dte"
            final_idx = j
            T = max(dte_remaining, 0) / 365
            iv = get_iv_with_term_structure(dvols[j], max(dte_remaining, 1)) / 100
            put_v = bs_put_price(prices[j], strike, T, r, iv)
            call_v = bs_call_price(prices[j], strike, T, r, iv)
            final_value = (put_v + call_v) / entry_price
            break

        T = dte_remaining / 365
        iv = get_iv_with_term_structure(dvols[j], dte_remaining) / 100
        put_v = bs_put_price(prices[j], strike, T, r, iv)
        call_v = bs_call_price(prices[j], strike, T, r, iv)
        cur_value = (put_v + call_v) / entry_price

        underwater = (entry_debit - cur_value) / entry_debit
        if underwater > max_dd:
            max_dd = underwater

        final_value = cur_value
        final_idx = j

    return TradeOutcome(
        entry_date=timestamps[entry_idx],
        exit_date=timestamps[final_idx],
        days_held=(timestamps[final_idx] - timestamps[entry_idx]).days,
        entry_debit=entry_debit,
        exit_value=final_value,
        max_drawdown_pct=max_dd,
        final_pnl_pct=(final_value - entry_debit) / entry_debit,
        exit_reason=exit_reason,
    )


async def calibrate_currency(client: DeribitClient, currency: str) -> dict:
    min_rv = MIN_RV[currency]
    print("=" * 80)
    print(f"{currency}: Target DTE={TARGET_DTE}, Exit DTE={EXIT_DTE}, Min RV(7d)={min_rv}%")
    print("=" * 80)

    prices, dvols, _iv_ranks, timestamps = await fetch_historical_data(client, currency)
    rv = realized_vol(prices, RV_WINDOW)

    entry_indices: list[int] = []
    last_entry = -TARGET_DTE
    for i in range(len(prices) - TARGET_DTE - 1):
        if rv[i] < min_rv:
            continue
        if i - last_entry < TARGET_DTE:
            continue
        entry_indices.append(i)
        last_entry = i

    print(f"Days analyzed: {len(prices)}")
    print(f"Days with RV(7d) > {min_rv}%: {sum(1 for v in rv if v >= min_rv)}")
    print(f"Non-overlapping entries simulated: {len(entry_indices)}")

    outcomes: list[TradeOutcome] = []
    for idx in entry_indices:
        result = simulate_straddle_hold(idx, prices, dvols, timestamps)
        if result is not None:
            outcomes.append(result)

    if not outcomes:
        print("No valid simulated trades.\n")
        return {"currency": currency, "trades": 0}

    drawdowns = sorted(o.max_drawdown_pct for o in outcomes)
    final_pnls = [o.final_pnl_pct for o in outcomes]
    hold_days = [o.days_held for o in outcomes]

    print(f"Simulated trades: {len(outcomes)}")
    print(f"Avg hold days: {np.mean(hold_days):.1f}")
    print(f"Avg buy-and-hold PnL: {np.mean(final_pnls):+.1%}")
    print(f"Win rate (buy-and-hold): {sum(1 for p in final_pnls if p > 0) / len(final_pnls):.1%}")
    print()

    print(f"{'Percentile':>12} {'Drawdown':>10}   {'Catches':<30}")
    print("-" * 60)
    pcts = [50, 60, 70, 75, 80, 85, 90, 95, 99]
    percentile_values = {}
    for p in pcts:
        v = float(np.percentile(drawdowns, p))
        percentile_values[p] = v
        print(f"{f'p{p}':>12} {v:>9.1%}   worst {100 - p}% of trades")
    print()

    return {
        "currency": currency,
        "trades": len(outcomes),
        "p90": percentile_values[90],
        "p95": percentile_values[95],
        "avg_pnl": float(np.mean(final_pnls)),
        "win_rate": sum(1 for p in final_pnls if p > 0) / len(final_pnls),
    }


async def run() -> None:
    print("=" * 80)
    print("GAMMA SCALP LONG-DEBIT STOP CALIBRATION")
    print("=" * 80)
    print("Buy-and-hold proxy (no scalp PnL): results are an UPPER BOUND on production drawdowns.")
    print()

    client = DeribitClient()
    summaries = []
    try:
        for currency in ("ETH", "BTC"):
            summary = await calibrate_currency(client, currency)
            summaries.append(summary)
    finally:
        await client.close()

    print("=" * 80)
    print("CALIBRATED long_debit_stop_loss_pct RECOMMENDATION")
    print("=" * 80)
    print(f"{'Currency':<10} {'Trades':>8} {'p90':>8} {'p95':>8} {'Avg P&L':>10} {'Win%':>7}")
    print("-" * 80)
    for s in summaries:
        if s.get("trades", 0) == 0:
            print(f"{s['currency']:<10} {'-':>8} {'-':>8} {'-':>8} {'-':>10} {'-':>7}")
            continue
        print(
            f"{s['currency']:<10} {s['trades']:>8} "
            f"{s['p90']:>7.1%} {s['p95']:>7.1%} "
            f"{s['avg_pnl']:>+9.1%} {s['win_rate']:>6.1%}"
        )
    print()
    print("Use the p90 column as the calibrated value. Production scalp PnL will")
    print("reduce real drawdowns vs this proxy; rerun after collecting live data.")


if __name__ == "__main__":
    asyncio.run(run())
