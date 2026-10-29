#!/usr/bin/env python
"""Calibrate ETH strategy thresholds using percentile-matching.

Method: Find what percentile BTC thresholds represent in BTC's distribution,
then find the ETH values at those same percentiles.

This ensures ETH thresholds trigger at the same relative frequency as BTC.

Usage:
    python scripts/calibrate_eth_thresholds.py
"""

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient


async def calibrate():
    """Run calibration analysis."""
    client = DeribitClient()

    try:
        print("=" * 70)
        print("ETH THRESHOLD CALIBRATION (Percentile-Matched)")
        print("=" * 70)

        # Fetch BTC data
        print("\nFetching BTC data...")
        btc_dvol_raw = await client.get_volatility_index(currency="BTC", resolution=86400)
        btc_price_raw = await client.get_tradingview_chart_data(
            instrument_name="BTC-PERPETUAL", resolution="1D"
        )

        # Fetch ETH data
        print("Fetching ETH data...")
        eth_dvol_raw = await client.get_volatility_index(currency="ETH", resolution=86400)
        eth_price_raw = await client.get_tradingview_chart_data(
            instrument_name="ETH-PERPETUAL", resolution="1D"
        )

        # Parse data
        btc_dvol = [c[4] if len(c) > 4 else c[1] for c in btc_dvol_raw]
        eth_dvol = [c[4] if len(c) > 4 else c[1] for c in eth_dvol_raw]
        btc_prices = btc_price_raw.get("close", [])
        eth_prices = eth_price_raw.get("close", [])

        print(f"  BTC: {len(btc_dvol)} DVOL days, {len(btc_prices)} price days")
        print(f"  ETH: {len(eth_dvol)} DVOL days, {len(eth_prices)} price days")

        # Calculate 7-day RV for each asset
        def calc_rv_series(prices):
            rv_values = []
            for i in range(7, len(prices)):
                log_returns = np.diff(np.log(prices[i - 7 : i + 1]))
                rv = float(np.std(log_returns, ddof=1) * np.sqrt(365) * 100)
                rv_values.append(rv)
            return rv_values

        btc_rv = calc_rv_series(btc_prices)
        eth_rv = calc_rv_series(eth_prices)

        # Calculate IV-RV spread for each asset
        def calc_spread_series(dvol, rv):
            min_len = min(len(dvol), len(rv))
            spreads = []
            for i in range(min_len):
                spread = dvol[-(min_len - i)] - rv[-(min_len - i)]
                spreads.append(spread)
            return spreads

        btc_spreads = calc_spread_series(btc_dvol, btc_rv)
        eth_spreads = calc_spread_series(eth_dvol, eth_rv)

        # ============================================================
        # 1. GAMMA SCALP min_rv CALIBRATION
        # ============================================================
        print("\n" + "=" * 70)
        print("1. GAMMA SCALP min_rv CALIBRATION")
        print("=" * 70)

        btc_min_rv = 40.0  # Current BTC threshold

        # Find what percentile 40% represents in BTC RV distribution
        btc_rv_arr = np.array(btc_rv)
        btc_percentile = np.sum(btc_rv_arr < btc_min_rv) / len(btc_rv_arr)

        print(f"\nBTC min_rv threshold: {btc_min_rv}%")
        print(
            f"BTC RV distribution: min={np.min(btc_rv_arr):.1f}, "
            f"max={np.max(btc_rv_arr):.1f}, median={np.median(btc_rv_arr):.1f}"
        )
        print(f"BTC percentile of {btc_min_rv}%: {btc_percentile:.1%}")
        print(f"  (meaning {(1-btc_percentile)*100:.1f}% of BTC days have RV > {btc_min_rv}%)")

        # Find ETH RV at same percentile
        eth_rv_arr = np.array(eth_rv)
        eth_min_rv = np.percentile(eth_rv_arr, btc_percentile * 100)

        print(
            f"\nETH RV distribution: min={np.min(eth_rv_arr):.1f}, "
            f"max={np.max(eth_rv_arr):.1f}, median={np.median(eth_rv_arr):.1f}"
        )
        print(f"ETH value at {btc_percentile:.1%} percentile: {eth_min_rv:.1f}%")

        # Verify
        eth_days_above = np.sum(eth_rv_arr > eth_min_rv) / len(eth_rv_arr)
        btc_days_above = np.sum(btc_rv_arr > btc_min_rv) / len(btc_rv_arr)

        print(f"\nVerification (% of days qualifying):")
        print(f"  BTC with threshold {btc_min_rv}%: {btc_days_above*100:.1f}%")
        print(f"  ETH with threshold {eth_min_rv:.1f}%: {eth_days_above*100:.1f}%")

        print(f"\n>>> RECOMMENDATION: ETH min_rv = {eth_min_rv:.0f}%")

        # ============================================================
        # 2. VOL ARB iv_rv_threshold_sell CALIBRATION
        # ============================================================
        print("\n" + "=" * 70)
        print("2. VOL ARB iv_rv_threshold_sell CALIBRATION")
        print("=" * 70)

        btc_sell_thresh = 15.0  # Current BTC threshold

        btc_sp_arr = np.array(btc_spreads)
        btc_sp_percentile = np.sum(btc_sp_arr < btc_sell_thresh) / len(btc_sp_arr)

        print(f"\nBTC iv_rv_threshold_sell: {btc_sell_thresh}")
        print(
            f"BTC spread distribution: min={np.min(btc_sp_arr):.1f}, "
            f"max={np.max(btc_sp_arr):.1f}, median={np.median(btc_sp_arr):.1f}"
        )
        print(f"BTC percentile of {btc_sell_thresh}: {btc_sp_percentile:.1%}")
        print(
            f"  (meaning {(1-btc_sp_percentile)*100:.1f}% of BTC days have spread > {btc_sell_thresh})"
        )

        eth_sp_arr = np.array(eth_spreads)
        eth_sell_thresh = np.percentile(eth_sp_arr, btc_sp_percentile * 100)

        print(
            f"\nETH spread distribution: min={np.min(eth_sp_arr):.1f}, "
            f"max={np.max(eth_sp_arr):.1f}, median={np.median(eth_sp_arr):.1f}"
        )
        print(f"ETH value at {btc_sp_percentile:.1%} percentile: {eth_sell_thresh:.1f}")

        # Verify
        eth_days_above = np.sum(eth_sp_arr > eth_sell_thresh) / len(eth_sp_arr)
        btc_days_above = np.sum(btc_sp_arr > btc_sell_thresh) / len(btc_sp_arr)

        print(f"\nVerification (% of days qualifying):")
        print(f"  BTC with threshold {btc_sell_thresh}: {btc_days_above*100:.1f}%")
        print(f"  ETH with threshold {eth_sell_thresh:.1f}: {eth_days_above*100:.1f}%")

        print(f"\n>>> RECOMMENDATION: ETH iv_rv_threshold_sell = {eth_sell_thresh:.0f}")

        # ============================================================
        # 3. VOL ARB iv_rv_threshold_buy CALIBRATION
        # ============================================================
        print("\n" + "=" * 70)
        print("3. VOL ARB iv_rv_threshold_buy CALIBRATION")
        print("=" * 70)

        btc_buy_thresh = -10.0  # Current BTC threshold

        btc_buy_percentile = np.sum(btc_sp_arr > btc_buy_thresh) / len(btc_sp_arr)

        print(f"\nBTC iv_rv_threshold_buy: {btc_buy_thresh}")
        print(f"BTC percentile of {btc_buy_thresh}: {(1-btc_buy_percentile):.1%}")
        print(
            f"  (meaning {(1-btc_buy_percentile)*100:.1f}% of BTC days have spread < {btc_buy_thresh})"
        )

        eth_buy_thresh = np.percentile(eth_sp_arr, (1 - btc_buy_percentile) * 100)

        print(f"\nETH value at {(1-btc_buy_percentile):.1%} percentile: {eth_buy_thresh:.1f}")

        # Verify
        eth_days_below = np.sum(eth_sp_arr < eth_buy_thresh) / len(eth_sp_arr)
        btc_days_below = np.sum(btc_sp_arr < btc_buy_thresh) / len(btc_sp_arr)

        print(f"\nVerification (% of days qualifying):")
        print(f"  BTC with threshold {btc_buy_thresh}: {btc_days_below*100:.1f}%")
        print(f"  ETH with threshold {eth_buy_thresh:.1f}: {eth_days_below*100:.1f}%")

        print(f"\n>>> RECOMMENDATION: ETH iv_rv_threshold_buy = {eth_buy_thresh:.0f}")

        # ============================================================
        # SUMMARY
        # ============================================================
        print("\n" + "=" * 70)
        print("CALIBRATION SUMMARY")
        print("=" * 70)
        print(f"\n{'Parameter':<30} {'BTC':>10} {'ETH':>10} {'Method':>25}")
        print("-" * 75)
        print(
            f"{'Gamma Scalp min_rv':<30} {btc_min_rv:>10.0f}% {eth_min_rv:>10.0f}% {'percentile-matched':>25}"
        )
        print(
            f"{'Vol Arb iv_rv_threshold_sell':<30} {btc_sell_thresh:>10.0f} {eth_sell_thresh:>10.0f} {'percentile-matched':>25}"
        )
        print(
            f"{'Vol Arb iv_rv_threshold_buy':<30} {btc_buy_thresh:>10.0f} {eth_buy_thresh:>10.0f} {'percentile-matched':>25}"
        )

        print("\n" + "=" * 70)
        print("These values maintain the same entry frequency as BTC thresholds,")
        print("adjusted for ETH's different volatility characteristics.")
        print("=" * 70)

    finally:
        await client.close()


def main():
    """Main entry point."""
    try:
        asyncio.run(calibrate())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
