"""Fetch real option chain data from Deribit."""

import asyncio
from datetime import datetime, timezone
from src.data.deribit_client import DeribitClient
from src.brain.signal import OptionContract


async def fetch_btc_options() -> None:
    """Fetch and display BTC option chain from Deribit."""
    client = DeribitClient()

    try:
        # Get current BTC price
        btc_price = await client.get_index_price("btc_usd")
        print(f"Current BTC Price: ${btc_price:,.2f}")

        # Get current DVOL (try alternative method)
        try:
            dvol = await client.get_current_dvol("BTC")
            print(f"Current DVOL: {dvol:.2f}")
        except Exception:
            # Fallback: use index price with correct name
            try:
                result = await client._request("GET", "/public/get_index_price", {"index_name": "bvol_btc"})
                dvol = result["index_price"]
                print(f"Current DVOL (BVOL): {dvol:.2f}")
            except Exception:
                dvol = 50.0  # Default
                print(f"Could not fetch DVOL, using default: {dvol:.2f}")
        print()

        # Get all BTC option instruments
        instruments = await client.get_instruments(currency="BTC", kind="option")
        print(f"Total BTC options available: {len(instruments)}")

        # Filter for options expiring in 30-45 days with strikes near ATM
        now = datetime.now(timezone.utc)
        near_term_options = []

        for inst in instruments:
            expiry_ts = inst["expiration_timestamp"] / 1000
            expiry = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
            dte = (expiry - now).days

            strike = inst["strike"]
            option_type = inst["option_type"]

            # Filter: 7-45 DTE, strike within 20% of spot
            if 7 <= dte <= 45 and 0.80 * btc_price <= strike <= 1.20 * btc_price:
                near_term_options.append({
                    "name": inst["instrument_name"],
                    "strike": strike,
                    "type": option_type,
                    "dte": dte,
                    "expiry": expiry,
                })

        print(f"Near-term options (7-45 DTE, ±20% of spot): {len(near_term_options)}")
        print()

        # Get book summaries for all options (more efficient than individual tickers)
        book_summaries = await client.get_book_summary_by_currency(currency="BTC", kind="option")
        summary_by_name = {s["instrument_name"]: s for s in book_summaries}

        # Build option chain
        option_chain: list[OptionContract] = []

        for opt in sorted(near_term_options, key=lambda x: (x["dte"], x["strike"]))[:20]:
            summary = summary_by_name.get(opt["name"])
            if summary:
                contract = OptionContract(
                    instrument_name=opt["name"],
                    strike=opt["strike"],
                    expiry=opt["expiry"],
                    option_type=opt["type"],
                    delta=summary.get("delta"),
                    gamma=summary.get("gamma"),
                    theta=summary.get("theta"),
                    vega=summary.get("vega"),
                    iv=summary.get("mark_iv"),
                    bid=summary.get("bid_price"),
                    ask=summary.get("ask_price"),
                    mark_price=summary.get("mark_price"),
                )
                option_chain.append(contract)

        # Display the chain
        print("=" * 100)
        print(f"{'Instrument':<30} {'Strike':>10} {'Type':>6} {'DTE':>5} {'Delta':>8} {'IV':>8} {'Bid':>10} {'Ask':>10} {'Mark':>10}")
        print("=" * 100)

        for c in option_chain:
            delta_str = f"{c.delta:.4f}" if c.delta else "N/A"
            iv_str = f"{c.iv:.1f}%" if c.iv else "N/A"
            bid_str = f"{c.bid:.6f}" if c.bid else "N/A"
            ask_str = f"{c.ask:.6f}" if c.ask else "N/A"
            mark_str = f"{c.mark_price:.6f}" if c.mark_price else "N/A"
            dte = (c.expiry - now).days

            print(f"{c.instrument_name:<30} {c.strike:>10,.0f} {c.option_type:>6} {dte:>5} {delta_str:>8} {iv_str:>8} {bid_str:>10} {ask_str:>10} {mark_str:>10}")

        print()
        print(f"Fetched {len(option_chain)} contracts from Deribit")

        # Fetch detailed Greeks for a few ATM options
        print()
        print("=" * 100)
        print("DETAILED GREEKS (via ticker endpoint) for selected contracts:")
        print("=" * 100)

        # Find options closest to ATM
        atm_options = sorted(near_term_options, key=lambda x: abs(x["strike"] - btc_price))[:6]

        for opt in atm_options:
            try:
                ticker = await client.get_ticker(opt["name"])
                greeks = ticker.get("greeks", {})
                print(f"\n{opt['name']} (DTE: {opt['dte']})")
                print(f"  Mark Price: {ticker.get('mark_price', 'N/A'):.6f} BTC")
                print(f"  Mark IV: {ticker.get('mark_iv', 'N/A'):.2f}%")
                print(f"  Delta: {greeks.get('delta', 'N/A')}")
                print(f"  Gamma: {greeks.get('gamma', 'N/A')}")
                print(f"  Theta: {greeks.get('theta', 'N/A')}")
                print(f"  Vega: {greeks.get('vega', 'N/A')}")
                print(f"  Bid: {ticker.get('best_bid_price', 'N/A')} | Ask: {ticker.get('best_ask_price', 'N/A')}")
            except Exception as e:
                print(f"\n{opt['name']}: Error fetching ticker - {e}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(fetch_btc_options())
