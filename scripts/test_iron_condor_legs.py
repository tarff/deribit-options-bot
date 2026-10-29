#!/usr/bin/env python
"""Test if Iron Condor can find all 4 legs with current config."""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_settings
from src.data.deribit_client import DeribitClient
from src.data.option_selector import OptionSelector
from src.brain.signal import OptionContract


async def main():
    print("=" * 70)
    print("IRON CONDOR LEG FINDER TEST")
    print("=" * 70)

    settings = load_settings()

    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Config values (from calibration)
    SHORT_DELTA = 0.15
    WING_DELTA = 0.05
    MAX_DELTA_DIFF = 0.08
    MIN_DTE = 25
    MAX_DTE = 55

    # Get current price
    ticker = await client.get_ticker("ETH-PERPETUAL")
    current_price = ticker.get("last_price", 0)
    print(f"\nCurrent ETH price: ${current_price:,.0f}")
    print(f"\nConfig: short_delta={SHORT_DELTA}, wing_delta={WING_DELTA}, max_delta_diff={MAX_DELTA_DIFF}")
    print(f"DTE range: {MIN_DTE}-{MAX_DTE}")

    now = datetime.now(timezone.utc)

    # Get all ETH options
    instruments = await client.get_instruments("ETH", "option")

    # Build option chain like paper_trading does
    min_strike = current_price * 0.7
    max_strike = current_price * 1.3

    option_chain = []
    for inst in instruments:
        try:
            parts = inst["instrument_name"].split("-")
            expiry_str = parts[1]
            strike = float(parts[2])

            expiry = datetime.strptime(expiry_str, "%d%b%y")
            expiry = expiry.replace(hour=8, tzinfo=timezone.utc)
            dte = (expiry - now).days

            if dte < MIN_DTE or dte > MAX_DTE:
                continue
            if strike < min_strike or strike > max_strike:
                continue

            ticker_data = await client.get_ticker(inst["instrument_name"])
            delta = ticker_data.get("greeks", {}).get("delta")

            if delta is None:
                continue

            opt_type = "put" if inst["instrument_name"].endswith("-P") else "call"

            contract = OptionContract(
                instrument_name=inst["instrument_name"],
                strike=strike,
                expiry=expiry,
                option_type=opt_type,
                delta=delta,
                bid=ticker_data.get("best_bid_price"),
                ask=ticker_data.get("best_ask_price"),
            )
            option_chain.append(contract)

        except Exception:
            continue

    await client.close()

    print(f"\nOption chain: {len(option_chain)} options")

    # Group by DTE
    by_dte = {}
    for opt in option_chain:
        dte = (opt.expiry - now).days
        if dte not in by_dte:
            by_dte[dte] = []
        by_dte[dte].append(opt)

    print(f"DTEs available: {sorted(by_dte.keys())}")

    # Test each DTE
    for dte in sorted(by_dte.keys()):
        opts = by_dte[dte]

        print(f"\n{'='*50}")
        print(f"DTE: {dte}")
        print("=" * 50)

        # Find put spread using iterative approach
        puts = [o for o in opts if o.option_type == "put" and o.delta is not None]
        short_put, long_put = None, None

        # Find all short put candidates
        short_put_candidates = [
            o for o in puts
            if abs(o.delta - (-SHORT_DELTA)) <= MAX_DELTA_DIFF
        ]
        short_put_candidates.sort(key=lambda o: abs(o.delta - (-SHORT_DELTA)))

        for sp in short_put_candidates:
            wing_candidates = [o for o in puts if o.strike < sp.strike]
            if not wing_candidates:
                continue
            wing_candidates.sort(key=lambda o: abs(o.delta - (-WING_DELTA)))
            if abs(wing_candidates[0].delta - (-WING_DELTA)) <= MAX_DELTA_DIFF:
                short_put = sp
                long_put = wing_candidates[0]
                break

        # Find call spread using iterative approach
        calls = [o for o in opts if o.option_type == "call" and o.delta is not None]
        short_call, long_call = None, None

        short_call_candidates = [
            o for o in calls
            if abs(o.delta - SHORT_DELTA) <= MAX_DELTA_DIFF
        ]
        short_call_candidates.sort(key=lambda o: abs(o.delta - SHORT_DELTA))

        for sc in short_call_candidates:
            wing_candidates = [o for o in calls if o.strike > sc.strike]
            if not wing_candidates:
                continue
            wing_candidates.sort(key=lambda o: abs(o.delta - WING_DELTA))
            if abs(wing_candidates[0].delta - WING_DELTA) <= MAX_DELTA_DIFF:
                short_call = sc
                long_call = wing_candidates[0]
                break

        legs = {
            "Short Put": (short_put, -SHORT_DELTA),
            "Long Put (wing)": (long_put, -WING_DELTA),
            "Short Call": (short_call, SHORT_DELTA),
            "Long Call (wing)": (long_call, WING_DELTA),
        }

        all_found = True
        for name, (leg, target) in legs.items():
            if leg:
                diff = abs(leg.delta - target)
                print(f"  {name}: {leg.instrument_name} delta={leg.delta:.3f} (diff={diff:.3f})")
            else:
                all_found = False
                # Find what's closest
                closest = None
                opt_type = "put" if "Put" in name else "call"
                for opt in opts:
                    if opt.option_type == opt_type:
                        if closest is None or abs(opt.delta - target) < abs(closest.delta - target):
                            closest = opt
                if closest:
                    print(f"  {name}: NOT FOUND (target {target:.2f}, closest is {closest.delta:.3f})")
                else:
                    print(f"  {name}: NOT FOUND (no {opt_type}s in chain)")

        if all_found:
            print(f"\n  >>> CAN TRADE IRON CONDOR AT {dte} DTE <<<")
        else:
            print(f"\n  >>> CANNOT trade at {dte} DTE (missing legs)")


if __name__ == "__main__":
    asyncio.run(main())
