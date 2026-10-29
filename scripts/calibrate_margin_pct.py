#!/usr/bin/env python
"""Calibrate margin percentage by analyzing Deribit's margin formula.

This script:
1. Connects to production Deribit (public API, no auth needed)
2. Gets option chain with mark prices
3. Calculates margin using Deribit's published formula
4. Recommends calibrated naked_short_pct value

Deribit Short Option Margin Formula (from docs):
  Initial Margin = max(
    0.15 * index_price,
    0.10 * index_price + option_mark_price
  ) + option_mark_price

For ETH/BTC options, margin is in the underlying currency.

Usage:
    python scripts/calibrate_margin_pct.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.deribit_client import DeribitClient


@dataclass
class MarginSample:
    """Single margin data point."""
    instrument: str
    option_type: str
    strike: float
    moneyness: str  # ITM, ATM, OTM
    dte: int
    index_price: float
    mark_price: float  # In underlying currency (fraction)
    mark_usd: float  # In USD
    initial_margin: float  # Calculated margin (fraction of underlying)
    margin_usd: float  # In USD
    notional_usd: float  # 1 contract in USD
    margin_pct: float  # initial_margin_usd / notional_usd


def calculate_deribit_margin(index_price: float, mark_price: float) -> float:
    """Calculate Deribit short option margin using their formula.

    Deribit formula for short options:
    Initial Margin = max(0.15 * index, 0.10 * index + mark) + mark

    This returns margin in the underlying currency (as a fraction of 1 contract).

    Args:
        index_price: Current index price in USD.
        mark_price: Option mark price in underlying currency (e.g., 0.05 ETH).

    Returns:
        Initial margin in underlying currency.
    """
    # Component 1: 15% of index (in underlying = 0.15)
    component_1 = 0.15

    # Component 2: 10% of index + mark_price (in underlying = 0.10 + mark)
    component_2 = 0.10 + mark_price

    # Initial margin = max(comp1, comp2) + mark_price
    initial_margin = max(component_1, component_2) + mark_price

    return initial_margin


def classify_moneyness(strike: float, spot: float, option_type: str) -> str:
    """Classify option as ITM, ATM, or OTM."""
    pct_diff = (strike - spot) / spot

    if abs(pct_diff) < 0.03:
        return "ATM"

    if option_type == "put":
        return "ITM" if strike > spot else "OTM"
    else:  # call
        return "ITM" if strike < spot else "OTM"


async def analyze_option_chain(client: DeribitClient, currency: str) -> list[MarginSample]:
    """Analyze option chain and calculate margin for each option."""
    samples = []

    # Get index price from perpetual ticker
    try:
        perp_ticker = await client.get_ticker(f"{currency}-PERPETUAL")
        index_price = perp_ticker.get("index_price", perp_ticker.get("last_price", 0))
        print(f"  {currency} index price: ${index_price:,.2f}")
    except Exception as e:
        print(f"  Error getting {currency} price: {e}")
        return samples

    # Get all option instruments
    await asyncio.sleep(0.2)
    try:
        instruments = await client.get_instruments(currency=currency, kind="option")
        print(f"  Found {len(instruments)} option instruments")
    except Exception as e:
        print(f"  Error getting instruments: {e}")
        return samples

    now = datetime.now(timezone.utc)

    # Filter for reasonable DTE range
    valid_instruments = []
    for inst in instruments:
        expiry_ts = inst.get("expiration_timestamp", 0)
        expiry_dt = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc)
        dte = (expiry_dt - now).days

        if 7 <= dte <= 45:  # Typical trading range
            valid_instruments.append((inst, dte))

    print(f"  {len(valid_instruments)} options in 7-45 DTE range")

    # Sample options across different strikes and types
    # Group by expiry, then sample
    by_expiry = {}
    for inst, dte in valid_instruments:
        expiry = inst.get("instrument_name", "").split("-")[1]
        if expiry not in by_expiry:
            by_expiry[expiry] = []
        by_expiry[expiry].append((inst, dte))

    # Take 2-3 expiries, sample options from each
    expiries = sorted(by_expiry.keys())[:3]

    for expiry in expiries:
        options = by_expiry[expiry]
        print(f"\n  Analyzing expiry {expiry} ({len(options)} options)...")

        # Sample ~10 options per expiry (mix of puts/calls, different strikes)
        step = max(1, len(options) // 10)
        sampled = options[::step][:12]

        for inst, dte in sampled:
            instrument_name = inst.get("instrument_name", "")
            strike = inst.get("strike", 0)
            option_type = inst.get("option_type", "")

            # Get ticker for mark price (with small delay to avoid rate limit)
            await asyncio.sleep(0.1)
            try:
                ticker = await client.get_ticker(instrument_name)
            except Exception as e:
                print(f"    Skipping {instrument_name}: {e}")
                continue

            mark_price = ticker.get("mark_price", 0)  # In underlying currency

            if mark_price <= 0:
                continue

            # Calculate margin using Deribit formula
            initial_margin = calculate_deribit_margin(index_price, mark_price)

            # Convert to USD and calculate percentage
            margin_usd = initial_margin * index_price
            notional_usd = index_price  # 1 contract
            margin_pct = margin_usd / notional_usd

            moneyness = classify_moneyness(strike, index_price, option_type)

            samples.append(MarginSample(
                instrument=instrument_name,
                option_type=option_type,
                strike=strike,
                moneyness=moneyness,
                dte=dte,
                index_price=index_price,
                mark_price=mark_price,
                mark_usd=mark_price * index_price,
                initial_margin=initial_margin,
                margin_usd=margin_usd,
                notional_usd=notional_usd,
                margin_pct=margin_pct,
            ))

    return samples


def analyze_results(samples: list[MarginSample]) -> dict:
    """Analyze margin samples and calculate statistics."""
    if not samples:
        return {}

    # Group by moneyness
    by_moneyness = {"ITM": [], "ATM": [], "OTM": []}
    for s in samples:
        by_moneyness[s.moneyness].append(s.margin_pct)

    results = {}
    for moneyness, pcts in by_moneyness.items():
        if pcts:
            results[moneyness] = {
                "count": len(pcts),
                "min": min(pcts),
                "max": max(pcts),
                "mean": np.mean(pcts),
                "median": np.median(pcts),
            }

    # Overall
    all_pcts = [s.margin_pct for s in samples]
    results["ALL"] = {
        "count": len(all_pcts),
        "min": min(all_pcts),
        "max": max(all_pcts),
        "mean": np.mean(all_pcts),
        "median": np.median(all_pcts),
    }

    return results


async def main():
    print("=" * 70)
    print("DERIBIT MARGIN CALIBRATION")
    print("Using Deribit's published margin formula")
    print("=" * 70)

    # Use production Deribit (public API only)
    client = DeribitClient(base_url="https://www.deribit.com")

    try:
        all_samples = []

        for currency in ["ETH", "BTC"]:
            print(f"\n{'-' * 70}")
            print(f"Analyzing {currency} options...")
            print("-" * 70)

            samples = await analyze_option_chain(client, currency)
            all_samples.extend(samples)

            if samples:
                results = analyze_results(samples)

                print(f"\n  Margin % by Moneyness:")
                print(f"  {'Category':<10} {'Count':>6} {'Min':>8} {'Max':>8} {'Mean':>8} {'Median':>8}")
                print(f"  {'-' * 50}")

                for cat in ["OTM", "ATM", "ITM", "ALL"]:
                    if cat in results:
                        r = results[cat]
                        print(f"  {cat:<10} {r['count']:>6} {r['min']:>7.1%} {r['max']:>7.1%} "
                              f"{r['mean']:>7.1%} {r['median']:>7.1%}")

        # Overall analysis
        print(f"\n{'=' * 70}")
        print("COMBINED ANALYSIS (ETH + BTC)")
        print("=" * 70)

        if all_samples:
            results = analyze_results(all_samples)

            print(f"\n{'Category':<10} {'Count':>6} {'Min':>8} {'Max':>8} {'Mean':>8} {'Median':>8}")
            print("-" * 55)

            for cat in ["OTM", "ATM", "ITM", "ALL"]:
                if cat in results:
                    r = results[cat]
                    print(f"{cat:<10} {r['count']:>6} {r['min']:>7.1%} {r['max']:>7.1%} "
                          f"{r['mean']:>7.1%} {r['median']:>7.1%}")

            # Recommendation
            print(f"\n{'=' * 70}")
            print("RECOMMENDATIONS")
            print("=" * 70)

            otm_median = results.get("OTM", {}).get("median", 0.15)
            atm_median = results.get("ATM", {}).get("median", 0.20)
            all_median = results.get("ALL", {}).get("median", 0.18)

            print(f"""
Based on Deribit's margin formula analysis:

  CURRENT VALUE:
    naked_short_pct = 0.15 (15%)

  EMPIRICAL DATA:
    OTM options median margin: {otm_median:.1%}
    ATM options median margin: {atm_median:.1%}
    All options median margin: {all_median:.1%}

  RECOMMENDATIONS:
    - For Wheel strategy (sells OTM puts):      {otm_median:.0%}
    - For Iron Condor (sells OTM put + call):   {otm_median:.0%}
    - For conservative backtesting:             {all_median:.0%}

  Deribit Formula Explanation:
    Margin = max(15% of index, 10% of index + mark_price) + mark_price

    For OTM options with low mark price (~1-3%):
      Margin ~ 15% + mark = 16-18%

    For ATM options with higher mark price (~5-10%):
      Margin ~ max(15%, 10% + mark) + mark = 20-30%

  CONCLUSION:
    The current 15% placeholder is SLIGHTLY LOW for typical positions.
    Recommend updating to: {max(otm_median, 0.18):.0%}
""")

            return 0

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await client.close()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)
