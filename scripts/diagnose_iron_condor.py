#!/usr/bin/env python
"""Diagnose why Iron Condor isn't trading."""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_settings
from src.data.deribit_client import DeribitClient


async def main():
    print("=" * 70)
    print("IRON CONDOR DIAGNOSTIC")
    print("=" * 70)

    settings = load_settings()

    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Config values
    SHORT_DELTA = 0.15
    WING_DELTA = 0.05
    MAX_DELTA_DIFF = 0.08
    MIN_DTE = 25
    MAX_DTE = 55

    ticker = await client.get_ticker("ETH-PERPETUAL")
    current_price = ticker.get("index_price", 0)
    print(f"\nCurrent ETH price: ${current_price:,.0f}")

    now = datetime.now(timezone.utc)
    instruments = await client.get_instruments("ETH", "option")

    min_strike = current_price * 0.7
    max_strike = current_price * 1.3

    # Group by DTE
    by_dte = {}
    for inst in instruments:
        try:
            parts = inst["instrument_name"].split("-")
            expiry_str = parts[1]
            strike = float(parts[2])
            opt_type = "put" if inst["instrument_name"].endswith("-P") else "call"

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

            if dte not in by_dte:
                by_dte[dte] = {"puts": [], "calls": []}

            entry = {
                "name": inst["instrument_name"],
                "strike": strike,
                "delta": delta,
            }

            if opt_type == "put":
                by_dte[dte]["puts"].append(entry)
            else:
                by_dte[dte]["calls"].append(entry)

        except Exception:
            continue

    await client.close()

    # Analyze each DTE
    for dte in sorted(by_dte.keys()):
        data = by_dte[dte]
        puts = sorted(data["puts"], key=lambda x: x["strike"], reverse=True)
        calls = sorted(data["calls"], key=lambda x: x["strike"])

        print(f"\n{'='*60}")
        print(f"DTE: {dte}")
        print("=" * 60)

        print(f"\n  PUTS (sorted by strike desc, need short at -0.15, wing at -0.05):")
        for p in puts:
            in_short = abs(p["delta"] - (-SHORT_DELTA)) <= MAX_DELTA_DIFF
            in_wing = abs(p["delta"] - (-WING_DELTA)) <= MAX_DELTA_DIFF
            markers = []
            if in_short:
                markers.append("SHORT")
            if in_wing:
                markers.append("WING")
            marker_str = f" <-- {', '.join(markers)}" if markers else ""
            print(f"    {p['name']:30} strike={p['strike']:,.0f}  delta={p['delta']:+.3f}{marker_str}")

        print(f"\n  CALLS (sorted by strike asc, need short at +0.15, wing at +0.05):")
        for c in calls:
            in_short = abs(c["delta"] - SHORT_DELTA) <= MAX_DELTA_DIFF
            in_wing = abs(c["delta"] - WING_DELTA) <= MAX_DELTA_DIFF
            markers = []
            if in_short:
                markers.append("SHORT")
            if in_wing:
                markers.append("WING")
            marker_str = f" <-- {', '.join(markers)}" if markers else ""
            print(f"    {c['name']:30} strike={c['strike']:,.0f}  delta={c['delta']:+.3f}{marker_str}")

        # Check if valid IC possible
        print(f"\n  IRON CONDOR FEASIBILITY:")

        # Find best short put (closest to -0.15)
        short_puts = [p for p in puts if abs(p["delta"] - (-SHORT_DELTA)) <= MAX_DELTA_DIFF]
        # Find best wing put (closest to -0.05, LOWER strike than short)
        wing_puts = [p for p in puts if abs(p["delta"] - (-WING_DELTA)) <= MAX_DELTA_DIFF]

        short_calls = [c for c in calls if abs(c["delta"] - SHORT_DELTA) <= MAX_DELTA_DIFF]
        wing_calls = [c for c in calls if abs(c["delta"] - WING_DELTA) <= MAX_DELTA_DIFF]

        valid_put_spread = False
        valid_call_spread = False

        if short_puts and wing_puts:
            # Check if any wing has lower strike than any short
            for sp in short_puts:
                for wp in wing_puts:
                    if wp["strike"] < sp["strike"]:
                        valid_put_spread = True
                        print(f"    Put spread: SELL {sp['name']} ({sp['delta']:+.3f}), BUY {wp['name']} ({wp['delta']:+.3f})")
                        break
                if valid_put_spread:
                    break

        if not valid_put_spread:
            if not short_puts:
                print(f"    Put spread: FAIL - no put within {MAX_DELTA_DIFF} of -0.15 delta")
            elif not wing_puts:
                print(f"    Put spread: FAIL - no put within {MAX_DELTA_DIFF} of -0.05 delta")
            else:
                print(f"    Put spread: FAIL - wing puts not at lower strike than short puts")
                print(f"      Short candidates: {[p['strike'] for p in short_puts]}")
                print(f"      Wing candidates: {[p['strike'] for p in wing_puts]}")

        if short_calls and wing_calls:
            for sc in short_calls:
                for wc in wing_calls:
                    if wc["strike"] > sc["strike"]:
                        valid_call_spread = True
                        print(f"    Call spread: SELL {sc['name']} ({sc['delta']:+.3f}), BUY {wc['name']} ({wc['delta']:+.3f})")
                        break
                if valid_call_spread:
                    break

        if not valid_call_spread:
            if not short_calls:
                print(f"    Call spread: FAIL - no call within {MAX_DELTA_DIFF} of +0.15 delta")
            elif not wing_calls:
                print(f"    Call spread: FAIL - no call within {MAX_DELTA_DIFF} of +0.05 delta")
            else:
                print(f"    Call spread: FAIL - wing calls not at higher strike than short calls")
                print(f"      Short candidates: {[c['strike'] for c in short_calls]}")
                print(f"      Wing candidates: {[c['strike'] for c in wing_calls]}")

        if valid_put_spread and valid_call_spread:
            print(f"\n  >>> VALID IRON CONDOR POSSIBLE <<<")
        else:
            print(f"\n  >>> CANNOT TRADE IRON CONDOR <<<")


if __name__ == "__main__":
    asyncio.run(main())
