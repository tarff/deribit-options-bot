#!/usr/bin/env python3
"""
Fee Impact Analysis on Historical Paper Trading P&L

Retroactively calculates what Deribit trading fees would have been on all
historical paper trades, then assesses the impact on realized P&L.

Fee rates sourced from Deribit public API (get_instrument endpoint):
  - maker_commission: 0.0003 (0.03% of underlying)
  - taker_commission: 0.0003 (0.03% of underlying)
  - Fee cap: 12.5% of option premium (Deribit standard)

Formula per leg:
  uncapped = commission_rate × underlying_price × quantity
  fee = min(uncapped, 0.125 × option_price × quantity)

Usage:
  python scripts/analyze_fee_impact.py --db data/pi_paper_trading.db
  python scripts/analyze_fee_impact.py --db data/pi_paper_trading.db --verbose
"""

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# From Deribit public API: get_instrument → maker_commission / taker_commission
# Verified on 2026-03-10 for ETH inverse, ETH_USDC linear, and AVAX_USDC linear
COMMISSION_RATE = 0.0003  # 0.03% of underlying
FEE_CAP_PCT = 0.125  # 12.5% of option premium


@dataclass
class Trade:
    id: int
    strategy_id: str
    strategy_type: str
    instrument: str
    side: str
    quantity: float
    price: float  # option premium (USDC for linear, fraction of underlying for inverse)
    pnl: float
    opened_at: str
    is_linear: bool = True

    @property
    def is_entry(self) -> bool:
        """Entry = sell for CSP/IC credit legs, buy for IC debit legs."""
        # We don't have enough context to determine entry vs exit cleanly
        # from the trade alone, so we calculate fee for every trade
        return True


@dataclass
class PositionFees:
    strategy_id: str
    strategy_type: str
    trade_count: int = 0
    total_fees: float = 0.0
    total_pnl: float = 0.0
    total_premium: float = 0.0
    instruments: set = field(default_factory=set)


def get_underlying_price(conn: sqlite3.Connection, timestamp: str) -> float | None:
    """Look up nearest ETH price from market_snapshots.

    Note: The column is named 'btc_price' but stores ETH price since the bot
    trades ETH_USDC options.
    """
    cur = conn.execute(
        """
        SELECT btc_price FROM market_snapshots
        WHERE timestamp <= ?
        ORDER BY timestamp DESC LIMIT 1
        """,
        (timestamp,),
    )
    row = cur.fetchone()
    if row:
        return row["btc_price"]

    # Fall back to earliest snapshot if trade predates snapshots
    cur = conn.execute(
        "SELECT btc_price FROM market_snapshots ORDER BY timestamp ASC LIMIT 1"
    )
    row = cur.fetchone()
    return row["btc_price"] if row else None


def calculate_fee(
    option_price: float,
    underlying_price: float,
    quantity: float,
    is_linear: bool,
) -> tuple[float, float, bool]:
    """Calculate Deribit trading fee for one leg.

    Returns: (fee_amount, uncapped_amount, was_capped)
    Fee is in USDC for linear options.
    """
    uncapped = COMMISSION_RATE * underlying_price * quantity

    if is_linear:
        # Linear: option_price is in USDC
        cap = FEE_CAP_PCT * option_price * quantity
    else:
        # Inverse: option_price is fraction of underlying
        cap = FEE_CAP_PCT * option_price * underlying_price * quantity

    was_capped = uncapped > cap
    fee = min(uncapped, cap)
    return fee, uncapped, was_capped


def load_trades(conn: sqlite3.Connection) -> list[Trade]:
    """Load all trades from the database."""
    cur = conn.execute(
        """
        SELECT id, strategy_id, strategy_type, instrument, side,
               quantity, price, pnl, opened_at
        FROM trades
        ORDER BY opened_at
        """
    )
    trades = []
    for row in cur:
        instrument = row["instrument"]
        is_linear = "_USDC" in instrument
        trades.append(
            Trade(
                id=row["id"],
                strategy_id=row["strategy_id"],
                strategy_type=row["strategy_type"],
                instrument=instrument,
                side=row["side"],
                quantity=row["quantity"],
                price=row["price"],
                pnl=row["pnl"] or 0.0,
                opened_at=row["opened_at"],
                is_linear=is_linear,
            )
        )
    return trades


def analyze(db_path: str, verbose: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    trades = load_trades(conn)
    if not trades:
        print("No trades found in database.")
        return

    print(f"Database: {db_path}")
    print(f"Total trades: {len(trades)}")
    print(f"Fee rate: {COMMISSION_RATE*100:.2f}% of underlying (from Deribit API)")
    print(f"Fee cap: {FEE_CAP_PCT*100:.1f}% of option premium")
    print()

    # Calculate fees for each trade
    total_fees = 0.0
    total_pnl = 0.0
    capped_count = 0
    missing_price_count = 0
    strategy_fees: dict[str, PositionFees] = {}
    position_fees: dict[str, PositionFees] = {}

    for trade in trades:
        underlying = get_underlying_price(conn, trade.opened_at)
        if underlying is None:
            missing_price_count += 1
            if verbose:
                print(f"  WARNING: No underlying price for {trade.opened_at}")
            continue

        fee, uncapped, was_capped = calculate_fee(
            trade.price, underlying, trade.quantity, trade.is_linear
        )

        if was_capped:
            capped_count += 1

        total_fees += fee
        total_pnl += trade.pnl

        # Aggregate by strategy type
        if trade.strategy_type not in strategy_fees:
            strategy_fees[trade.strategy_type] = PositionFees(
                strategy_id="", strategy_type=trade.strategy_type
            )
        sf = strategy_fees[trade.strategy_type]
        sf.trade_count += 1
        sf.total_fees += fee
        sf.total_pnl += trade.pnl
        sf.total_premium += trade.price * trade.quantity

        # Aggregate by position
        if trade.strategy_id not in position_fees:
            position_fees[trade.strategy_id] = PositionFees(
                strategy_id=trade.strategy_id,
                strategy_type=trade.strategy_type,
            )
        pf = position_fees[trade.strategy_id]
        pf.trade_count += 1
        pf.total_fees += fee
        pf.total_pnl += trade.pnl
        pf.total_premium += trade.price * trade.quantity
        pf.instruments.add(trade.instrument)

        if verbose:
            cap_str = " [CAPPED]" if was_capped else ""
            print(
                f"  {trade.opened_at[:16]} {trade.strategy_type:12s} "
                f"{trade.side:4s} {trade.quantity:.2f} × "
                f"${trade.price:.2f} → fee=${fee:.4f} "
                f"(underlying=${underlying:.2f}){cap_str}"
            )

    # === Summary ===
    print("=" * 70)
    print("FEE IMPACT ANALYSIS")
    print("=" * 70)

    print(f"\n{'Metric':<35} {'Value':>15}")
    print("-" * 50)
    print(f"{'Total trades analyzed':<35} {len(trades) - missing_price_count:>15d}")
    print(f"{'Total estimated fees':<35} {'$' + f'{total_fees:.2f}':>15}")
    print(f"{'Total realized P&L (excl. fees)':<35} {'$' + f'{total_pnl:.2f}':>15}")
    print(f"{'P&L after fees':<35} {'$' + f'{total_pnl - total_fees:.2f}':>15}")
    pct = (total_fees / abs(total_pnl) * 100) if total_pnl != 0 else float("inf")
    print(f"{'Fees as % of |P&L|':<35} {f'{pct:.1f}%':>15}")
    print(f"{'Avg fee per trade':<35} {'$' + f'{total_fees / max(len(trades), 1):.4f}':>15}")
    print(f"{'Trades where cap applied':<35} {capped_count:>15d}")
    if missing_price_count:
        print(f"{'Trades missing price data':<35} {missing_price_count:>15d}")

    # === By Strategy ===
    print(f"\n{'Strategy':<15} {'Trades':>7} {'Fees':>12} {'P&L':>12} {'P&L-Fees':>12} {'Fee%':>8}")
    print("-" * 66)
    for stype, sf in sorted(strategy_fees.items()):
        pnl_after = sf.total_pnl - sf.total_fees
        fee_pct = (
            (sf.total_fees / abs(sf.total_pnl) * 100) if sf.total_pnl != 0 else 0
        )
        print(
            f"{stype:<15} {sf.trade_count:>7d} "
            f"{'$' + f'{sf.total_fees:.2f}':>12} "
            f"{'$' + f'{sf.total_pnl:.2f}':>12} "
            f"{'$' + f'{pnl_after:.2f}':>12} "
            f"{f'{fee_pct:.1f}%':>8}"
        )

    # === By Position ===
    print(f"\n{'Position (strategy_id)':<42} {'Type':>12} {'Legs':>5} {'Fees':>10} {'P&L':>10}")
    print("-" * 82)
    for pid, pf in sorted(
        position_fees.items(), key=lambda x: x[1].total_fees, reverse=True
    ):
        short_id = pid[:38] if len(pid) > 38 else pid
        print(
            f"{short_id:<42} {pf.strategy_type:>12} "
            f"{pf.trade_count:>5d} "
            f"{'$' + f'{pf.total_fees:.2f}':>10} "
            f"{'$' + f'{pf.total_pnl:.2f}':>10}"
        )

    # === Mainnet Projection ===
    print("\n" + "=" * 70)
    print("MAINNET FEE PROJECTION")
    print("=" * 70)

    # Exclude churning bug trades (Feb 21 rapid buy/sell cycle)
    clean_trades = [
        t
        for t in trades
        if not (
            t.strategy_type == "wheel"
            and t.opened_at.startswith("2026-02-21")
        )
    ]
    clean_fees = 0.0
    clean_pnl = 0.0
    clean_count = 0
    for t in clean_trades:
        underlying = get_underlying_price(conn, t.opened_at)
        if underlying is None:
            continue
        fee, _, _ = calculate_fee(t.price, underlying, t.quantity, t.is_linear)
        clean_fees += fee
        clean_pnl += t.pnl
        clean_count += 1

    print(f"\nExcluding Feb 21 churning bug ({len(trades) - len(clean_trades)} trades removed):")
    print(f"{'Clean trades':<35} {clean_count:>15d}")
    print(f"{'Clean total fees':<35} {'$' + f'{clean_fees:.2f}':>15}")
    print(f"{'Clean P&L':<35} {'$' + f'{clean_pnl:.2f}':>15}")
    print(f"{'Clean P&L after fees':<35} {'$' + f'{clean_pnl - clean_fees:.2f}':>15}")

    # Per-position fee (typical Wheel: 2 trades, IC: 8 trades)
    if clean_count > 0:
        avg_fee = clean_fees / clean_count
        print(f"\n{'Avg fee per clean trade':<35} {'$' + f'{avg_fee:.4f}':>15}")
        print(f"{'Est. fee per Wheel round-trip':<35} {'$' + f'{avg_fee * 2:.4f}':>15}")
        print(f"{'Est. fee per IC round-trip':<35} {'$' + f'{avg_fee * 8:.4f}':>15}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze fee impact on trading P&L")
    parser.add_argument(
        "--db",
        default="data/pi_paper_trading.db",
        help="Path to paper trading database (default: data/pi_paper_trading.db)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show per-trade fee details"
    )
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        print("Copy from Pi: scp pi@<pi-host>:~/options-trading-bot/data/paper_trading.db data/pi_paper_trading.db")
        raise SystemExit(1)

    analyze(args.db, args.verbose)
