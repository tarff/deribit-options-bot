"""Compare BTC vs ETH margin requirements via backtest.

Fetches historical data for both assets and runs parallel backtests
to compare margin requirements.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.data_fetcher import HistoricalBar, HistoricalDataFetcher
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.data.deribit_client import DeribitClient
from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository
from src.risk.position_sizer import SizingConfig
from src.risk.risk_manager import RiskConfig


def load_btc_from_database(
    db_path: str,
) -> tuple[list[HistoricalBar], list[HistoricalBar], datetime, datetime]:
    """Load BTC data from the stored database.

    Args:
        db_path: Path to the database.

    Returns:
        Tuple of (price_bars, dvol_bars, start_date, end_date).
    """
    db = Database(db_path)
    db.initialize()
    repo = HistoricalDataRepository(db)

    data_points = repo.get_range()
    db.close()

    if not data_points:
        return [], [], datetime.now(timezone.utc), datetime.now(timezone.utc)

    price_bars: list[HistoricalBar] = []
    dvol_bars: list[HistoricalBar] = []

    for dp in data_points:
        price_bars.append(HistoricalBar(
            timestamp=dp.timestamp,
            open=dp.btc_open,
            high=dp.btc_high,
            low=dp.btc_low,
            close=dp.btc_price,
            volume=dp.btc_volume,
        ))
        dvol_bars.append(HistoricalBar(
            timestamp=dp.timestamp,
            open=dp.dvol_open,
            high=dp.dvol_high,
            low=dp.dvol_low,
            close=dp.dvol,
            volume=0.0,
        ))

    start_date = data_points[0].timestamp
    end_date = data_points[-1].timestamp

    return price_bars, dvol_bars, start_date, end_date


async def fetch_asset_data(
    client: DeribitClient,
    currency: str,
    start: datetime,
    end: datetime,
) -> tuple[list[HistoricalBar], list[HistoricalBar]]:
    """Fetch price and DVOL data for an asset.

    Args:
        client: Deribit API client.
        currency: Currency code (BTC or ETH).
        start: Start datetime.
        end: End datetime.

    Returns:
        Tuple of (price_bars, dvol_bars).
    """
    fetcher = HistoricalDataFetcher(client)

    # Instrument names for perpetual futures
    instrument = f"{currency}-PERPETUAL"

    print(f"  Fetching {currency} price data...")
    price_bars = await fetcher.fetch_price_history(
        instrument=instrument,
        start=start,
        end=end,
        resolution="1D",
    )

    print(f"  Fetching {currency} DVOL data...")
    dvol_bars = await fetcher.fetch_dvol_history(
        start=start,
        end=end,
        currency=currency,
        resolution=86400,  # Daily
    )

    return price_bars, dvol_bars


async def run_backtest_for_asset(
    price_bars: list[HistoricalBar],
    dvol_bars: list[HistoricalBar],
    initial_capital: float,
    asset_name: str,
    dvol_reduce_threshold: float = 60.0,
    dvol_halt_threshold: float = 80.0,
) -> BacktestResult:
    """Run backtest for a single asset.

    Args:
        price_bars: Price history.
        dvol_bars: DVOL history.
        initial_capital: Starting capital.
        asset_name: Asset name for logging.
        dvol_reduce_threshold: DVOL level for HIGH_STRESS regime.
        dvol_halt_threshold: DVOL level for EXTREME_FEAR regime.

    Returns:
        BacktestResult.
    """
    risk_config = RiskConfig(
        max_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )

    sizing_config = SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
    )

    config = BacktestConfig(
        initial_capital=initial_capital,
        risk_config=risk_config,
        sizing_config=sizing_config,
        track_margin=True,
        dvol_reduce_threshold=dvol_reduce_threshold,
        dvol_halt_threshold=dvol_halt_threshold,
    )

    engine = BacktestEngine(config)
    result = await engine.run(price_bars, dvol_bars)

    return result


def print_comparison(
    btc_result: BacktestResult,
    eth_result: BacktestResult,
    btc_price: float,
    eth_price: float,
) -> None:
    """Print side-by-side comparison of BTC vs ETH results.

    Args:
        btc_result: BTC backtest result.
        eth_result: ETH backtest result.
        btc_price: Latest BTC price.
        eth_price: Latest ETH price.
    """
    print("\n" + "=" * 80)
    print("  BTC vs ETH MARGIN COMPARISON")
    print("=" * 80)

    # Price context
    print("\n  Asset Prices (latest):")
    print(f"    BTC: ${btc_price:>12,.2f}")
    print(f"    ETH: ${eth_price:>12,.2f}")
    print(f"    Ratio: {btc_price / eth_price:.1f}x")

    # Performance comparison
    print(f"\n  {'Metric':<30} {'BTC':>15} {'ETH':>15} {'Ratio':>10}")
    print("  " + "-" * 70)

    print(f"  {'Total Return':<30} {btc_result.total_return:>14.2%} {eth_result.total_return:>14.2%}")
    print(f"  {'Sharpe Ratio':<30} {btc_result.sharpe_ratio:>15.2f} {eth_result.sharpe_ratio:>15.2f}")
    print(f"  {'Max Drawdown':<30} {btc_result.max_drawdown:>14.2%} {eth_result.max_drawdown:>14.2%}")
    print(f"  {'Win Rate':<30} {btc_result.win_rate:>14.2%} {eth_result.win_rate:>14.2%}")
    print(f"  {'Total Trades':<30} {btc_result.total_trades:>15} {eth_result.total_trades:>15}")

    # Margin comparison
    print(f"\n  {'MARGIN METRICS':<30} {'BTC':>15} {'ETH':>15} {'Ratio':>10}")
    print("  " + "-" * 70)

    btc_mm = btc_result.margin_metrics
    eth_mm = eth_result.margin_metrics

    if btc_mm and eth_mm:
        ratio_min_cap = btc_mm.min_capital_required / eth_mm.min_capital_required if eth_mm.min_capital_required > 0 else 0
        ratio_peak = btc_mm.peak_margin_used / eth_mm.peak_margin_used if eth_mm.peak_margin_used > 0 else 0

        print(f"  {'Min Capital Required':<30} ${btc_mm.min_capital_required:>13,.2f} ${eth_mm.min_capital_required:>13,.2f} {ratio_min_cap:>9.1f}x")
        print(f"  {'Peak Margin Used':<30} ${btc_mm.peak_margin_used:>13,.2f} ${eth_mm.peak_margin_used:>13,.2f} {ratio_peak:>9.1f}x")
        print(f"  {'Avg Margin Utilization':<30} {btc_mm.avg_margin_utilization:>14.2%} {eth_mm.avg_margin_utilization:>14.2%}")
        print(f"  {'Margin Breach Count':<30} {btc_mm.margin_breach_count:>15} {eth_mm.margin_breach_count:>15}")

        if btc_mm.peak_margin_timestamp:
            print(f"  {'BTC Peak Margin Date':<30} {btc_mm.peak_margin_timestamp.strftime('%Y-%m-%d'):>15}")
        if eth_mm.peak_margin_timestamp:
            print(f"  {'ETH Peak Margin Date':<30} {eth_mm.peak_margin_timestamp.strftime('%Y-%m-%d'):>15}")

    # Regime distribution
    print(f"\n  {'REGIME DISTRIBUTION':<30} {'BTC':>15} {'ETH':>15}")
    print("  " + "-" * 70)

    btc_regimes = btc_result.regime_distribution
    eth_regimes = eth_result.regime_distribution

    all_regimes = sorted(set(btc_regimes.keys()) | set(eth_regimes.keys()))
    btc_total = sum(btc_regimes.values()) or 1
    eth_total = sum(eth_regimes.values()) or 1

    for regime in all_regimes:
        btc_count = btc_regimes.get(regime, 0)
        eth_count = eth_regimes.get(regime, 0)
        btc_pct = btc_count / btc_total * 100
        eth_pct = eth_count / eth_total * 100
        print(f"  {regime:<30} {btc_pct:>14.1f}% {eth_pct:>14.1f}%")

    # Key insight
    print("\n" + "=" * 80)
    print("  KEY INSIGHT")
    print("=" * 80)
    if btc_mm and eth_mm and eth_mm.min_capital_required > 0:
        savings = btc_mm.min_capital_required - eth_mm.min_capital_required
        savings_pct = savings / btc_mm.min_capital_required * 100
        print(f"\n  ETH requires ${savings:,.2f} less minimum capital ({savings_pct:.1f}% less)")
        print(f"  This is roughly proportional to the {btc_price / eth_price:.1f}x price difference")
        print("\n  To deploy similar capital with ETH, increase position size proportionally.")
    elif eth_result.total_trades == 0:
        print("\n  ETH generated NO TRADES due to different regime distribution.")
        print("  ETH DVOL runs higher (mean ~62 vs BTC's ~51), keeping it mostly in HIGH_STRESS.")
        print("\n  To trade ETH, consider:")
        print("    1. Recalibrate regime thresholds for ETH's higher baseline volatility")
        print("    2. ETH HIGH_STRESS threshold could be ~70 instead of 60")
        print("    3. This would shift more ETH days into NEUTRAL regime for Calendar Spread")


async def run(args: argparse.Namespace) -> int:
    """Execute the comparison.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    print(f"Initial capital: ${args.capital:,.2f}")

    # Load BTC data from database (has 3 years of data)
    print("\nLoading BTC data from database...")
    btc_price_bars, btc_dvol_bars, start_date, end_date = load_btc_from_database(
        args.db
    )

    if not btc_price_bars:
        print("Error: No BTC data in database. Run fetch_historical_data.py first.")
        return 1

    print(f"  Loaded {len(btc_price_bars)} bars ({start_date.date()} to {end_date.date()})")

    # Fetch ETH data for the same date range
    client = DeribitClient()

    try:
        print("\nFetching ETH data for same date range...")
        eth_price_bars, eth_dvol_bars = await fetch_asset_data(
            client, "ETH", start_date, end_date
        )
        print(f"  Got {len(eth_price_bars)} price bars, {len(eth_dvol_bars)} DVOL bars")

        if not eth_price_bars:
            print("Error: Failed to fetch ETH data")
            return 1

        # Align data by date (not timestamp) to handle different time-of-day
        # Group by date
        btc_price_by_date = {b.timestamp.date(): b for b in btc_price_bars}
        btc_dvol_by_date = {b.timestamp.date(): b for b in btc_dvol_bars}
        eth_price_by_date = {b.timestamp.date(): b for b in eth_price_bars}
        eth_dvol_by_date = {b.timestamp.date(): b for b in eth_dvol_bars}

        # Find dates where we have all 4 data points
        common_dates = sorted(
            set(btc_price_by_date.keys())
            & set(btc_dvol_by_date.keys())
            & set(eth_price_by_date.keys())
            & set(eth_dvol_by_date.keys())
        )
        print(f"\n  Common dates: {len(common_dates)} ({common_dates[0]} to {common_dates[-1]})")

        # Rebuild aligned lists with matching timestamps
        # Use price bar timestamps and update DVOL timestamps to match
        btc_price_aligned = []
        btc_dvol_aligned = []
        eth_price_aligned = []
        eth_dvol_aligned = []

        for d in common_dates:
            btc_p = btc_price_by_date[d]
            btc_d = btc_dvol_by_date[d]
            eth_p = eth_price_by_date[d]
            eth_d = eth_dvol_by_date[d]

            # Align DVOL timestamps to match price timestamps for proper matching in engine
            btc_d_aligned = HistoricalBar(
                timestamp=btc_p.timestamp,
                open=btc_d.open,
                high=btc_d.high,
                low=btc_d.low,
                close=btc_d.close,
                volume=btc_d.volume,
            )
            eth_d_aligned = HistoricalBar(
                timestamp=eth_p.timestamp,
                open=eth_d.open,
                high=eth_d.high,
                low=eth_d.low,
                close=eth_d.close,
                volume=eth_d.volume,
            )

            btc_price_aligned.append(btc_p)
            btc_dvol_aligned.append(btc_d_aligned)
            eth_price_aligned.append(eth_p)
            eth_dvol_aligned.append(eth_d_aligned)

        # Get latest prices for context
        btc_price = btc_price_aligned[-1].close if btc_price_aligned else 0
        eth_price = eth_price_aligned[-1].close if eth_price_aligned else 0

        # Show DVOL statistics
        btc_dvol_values = [b.close for b in btc_dvol_aligned]
        eth_dvol_values = [b.close for b in eth_dvol_aligned]

        print(f"\n  BTC DVOL: min={min(btc_dvol_values):.1f}, max={max(btc_dvol_values):.1f}, mean={sum(btc_dvol_values)/len(btc_dvol_values):.1f}")
        print(f"  ETH DVOL: min={min(eth_dvol_values):.1f}, max={max(eth_dvol_values):.1f}, mean={sum(eth_dvol_values)/len(eth_dvol_values):.1f}")

        # Run BTC backtest (using default thresholds: 60/80)
        print("\nRunning BTC backtest (thresholds: 60/80)...")
        btc_result = await run_backtest_for_asset(
            btc_price_aligned, btc_dvol_aligned, args.capital, "BTC",
            dvol_reduce_threshold=60.0,
            dvol_halt_threshold=80.0,
        )
        print(f"  BTC: {btc_result.total_trades} trades, {btc_result.total_return:.2%} return")

        # Run ETH backtest with calibrated thresholds
        # Thresholds derived from analyze_eth_dvol.py (percentile-matched):
        # - ETH HIGH_STRESS (reduce): 73 (matches BTC's 85th percentile at 60)
        # - ETH EXTREME_FEAR (halt): 82 (matches BTC's 99.8th percentile at 80)
        print("\nRunning ETH backtest (thresholds: 73/82 - calibrated)...")
        eth_result = await run_backtest_for_asset(
            eth_price_aligned, eth_dvol_aligned, args.capital, "ETH",
            dvol_reduce_threshold=73.0,
            dvol_halt_threshold=82.0,
        )
        print(f"  ETH: {eth_result.total_trades} trades, {eth_result.total_return:.2%} return")

        # Print comparison
        print_comparison(btc_result, eth_result, btc_price, eth_price)

        return 0

    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await client.close()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Compare BTC vs ETH margin requirements"
    )
    parser.add_argument(
        "--db",
        default="data/trading.db",
        help="Database path for BTC data (default: data/trading.db)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
        help="Initial capital in USD (default: 100000)",
    )

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(130)


if __name__ == "__main__":
    main()
