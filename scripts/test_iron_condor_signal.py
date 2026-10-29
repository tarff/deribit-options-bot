#!/usr/bin/env python
"""Test if Iron Condor generates a signal with current market conditions."""

import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_settings
from src.data.deribit_client import DeribitClient
from src.data.market_metrics import MarketMetrics
from src.data.volatility import calculate_iv_rank
from src.strategies.iron_condor import IronCondorStrategy, IronCondorConfig
from src.brain.signal import OptionContract


async def main():
    print("=" * 70)
    print("IRON CONDOR SIGNAL TEST")
    print("=" * 70)

    settings = load_settings()

    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Config (same as paper_trading.py)
    ic_config = IronCondorConfig(
        name="iron_condor",
        enabled=True,
        target_dte_min=25,
        target_dte_max=55,
        profit_target=0.50,
        short_delta=0.15,
        wing_delta=0.05,
        max_delta_diff=0.08,
    )

    strategy = IronCondorStrategy(ic_config)

    # Get current market data
    ticker = await client.get_ticker("ETH-PERPETUAL")
    current_price = ticker.get("index_price", 0)
    dvol = await client.get_current_dvol("ETH")

    # Get IV Rank from local database (same as paper_trading)
    local_db_path = Path("data/trading.db")
    iv_rank = None
    if local_db_path.exists():
        conn = sqlite3.connect(str(local_db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT dvol FROM historical_data WHERE dvol IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 252"
        )
        historical_dvol = [r[0] for r in cursor.fetchall()]
        conn.close()
        if len(historical_dvol) >= 10:
            iv_rank = calculate_iv_rank(dvol, historical_dvol)

    print(f"\nCurrent ETH price: ${current_price:,.0f}")
    print(f"DVOL: {dvol:.1f}")
    print(f"IV Rank (252-day): {iv_rank:.1%}" if iv_rank else "IV Rank: N/A")
    print(f"Iron Condor threshold: 60%")

    if iv_rank and iv_rank >= 0.60:
        print(">>> IV Rank ABOVE threshold - checking for signal")
    else:
        print(">>> IV Rank BELOW threshold - no signal expected")
        await client.close()
        return

    # Build option chain
    now = datetime.now(timezone.utc)
    instruments = await client.get_instruments("ETH", "option")

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

            if dte < 25 or dte > 55:
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

    print(f"\nOption chain size: {len(option_chain)}")

    # Create metrics
    metrics = MarketMetrics(
        btc_price=current_price,  # Using ETH price
        dvol=dvol,
        iv_rank=iv_rank,
        rv_30d=45.0,
        timestamp=now,
    )

    # Evaluate strategy
    signal = await strategy.evaluate(metrics, option_chain)

    if signal:
        print("\n>>> SIGNAL GENERATED! <<<")
        print(f"Strategy: {signal.strategy_type}")
        print(f"Action: {signal.action}")
        print(f"Contracts:")
        for i, (c, d) in enumerate(zip(signal.contracts, signal.legs_direction)):
            print(f"  {i+1}. {d.upper():5} {c.instrument_name} delta={c.delta:.3f} strike={c.strike:.0f}")
        print(f"Max Profit: {signal.max_profit:.4f}")
        print(f"Max Loss: {signal.max_loss:.4f}")
        print(f"Reason: {signal.reason}")
    else:
        print("\n>>> NO SIGNAL - strategy did not generate a trade")
        print("Possible reasons:")
        print("  - No matching legs found")
        print("  - Position already active")
        print("  - Strategy disabled")


if __name__ == "__main__":
    asyncio.run(main())
