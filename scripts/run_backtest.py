"""CLI script to run backtests with different configurations."""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.data_fetcher import HistoricalBar
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.persistence.database import Database
from src.persistence.repositories import HistoricalDataRepository
from src.persistence.models import HistoricalDataPoint
from src.risk.risk_manager import RiskConfig
from src.risk.position_sizer import SizingConfig


# Note: DVOL thresholds are handled by RegimeDetector and PositionSizer,
# not directly by RiskConfig. The backtest engine uses regime detection
# which classifies markets based on DVOL levels.


def load_historical_data(db_path: str) -> tuple[list[HistoricalBar], list[HistoricalBar]]:
    """Load historical data from database and convert to HistoricalBar format.

    Args:
        db_path: Path to the database.

    Returns:
        Tuple of (price_bars, dvol_bars).
    """
    db = Database(db_path)
    db.initialize()
    repo = HistoricalDataRepository(db)

    data_points = repo.get_range()
    db.close()

    if not data_points:
        print("Error: No historical data found in database")
        sys.exit(1)

    print(f"Loaded {len(data_points)} data points")
    print(f"Date range: {data_points[0].timestamp.date()} to {data_points[-1].timestamp.date()}")

    # Convert to HistoricalBar format
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

    return price_bars, dvol_bars


def print_result(result: BacktestResult, label: str) -> None:
    """Print backtest results in a formatted way.

    Args:
        result: BacktestResult to print.
        label: Label for this configuration.
    """
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Return:    {result.total_return:>10.2%}")
    print(f"  Sharpe Ratio:    {result.sharpe_ratio:>10.2f}")
    print(f"  Max Drawdown:    {result.max_drawdown:>10.2%}")
    print(f"  Win Rate:        {result.win_rate:>10.2%}")
    print(f"  Total Trades:    {result.total_trades:>10}")
    print(f"  Profit Factor:   {result.profit_factor:>10.2f}")
    print(f"  Avg Trade P&L:   {result.avg_trade_pnl:>10.6f} BTC")
    print(f"  Final Capital:   ${result.final_capital:>10,.2f}")

    # Print margin metrics if available
    if result.margin_metrics is not None:
        mm = result.margin_metrics
        print(f"\n  Margin Metrics:")
        print(f"    Min Capital Required:  ${mm.min_capital_required:>12,.2f}")
        print(f"    Peak Margin Used:      ${mm.peak_margin_used:>12,.2f}")
        print(f"    Avg Margin Utilization: {mm.avg_margin_utilization:>11.2%}")
        print(f"    Margin Breach Count:   {mm.margin_breach_count:>12}")
        if mm.peak_margin_timestamp:
            print(f"    Peak Margin Date:      {mm.peak_margin_timestamp.strftime('%Y-%m-%d %H:%M')}")

    print(f"\n  Regime Distribution:")
    for regime, count in sorted(result.regime_distribution.items()):
        pct = count / sum(result.regime_distribution.values()) * 100
        print(f"    {regime:<25} {count:>5} ({pct:>5.1f}%)")


async def run_single_backtest(
    price_bars: list[HistoricalBar],
    dvol_bars: list[HistoricalBar],
    initial_capital: float,
    label: str,
    max_positions: int = 5,
    max_daily_loss_pct: float = 0.05,
    max_drawdown_pct: float = 0.15,
) -> BacktestResult:
    """Run a single backtest with specific configuration.

    Args:
        price_bars: Price history.
        dvol_bars: DVOL history.
        initial_capital: Starting capital.
        label: Label for this configuration.
        max_positions: Max concurrent positions.
        max_daily_loss_pct: Max daily loss as fraction.
        max_drawdown_pct: Max drawdown as fraction.

    Returns:
        BacktestResult.
    """
    risk_config = RiskConfig(
        max_positions=max_positions,
        max_daily_loss_pct=max_daily_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
    )

    sizing_config = SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
    )

    config = BacktestConfig(
        initial_capital=initial_capital,
        risk_config=risk_config,
        sizing_config=sizing_config,
        # ETH DVOL thresholds (calibrated via scripts/analyze_eth_dvol.py)
        dvol_halt_threshold=82.0,
        dvol_reduce_threshold=73.0,
    )

    engine = BacktestEngine(config)
    result = await engine.run(price_bars, dvol_bars)

    # Show final state
    open_positions = len(engine.position_tracker.positions)
    closed_trades = len(engine.position_tracker.closed_trades)
    print(f"\n  Open positions: {open_positions}, Closed trades: {closed_trades}")

    print_result(result, label)
    return result


async def run_risk_comparison(
    price_bars: list[HistoricalBar],
    dvol_bars: list[HistoricalBar],
    initial_capital: float,
) -> dict[str, BacktestResult]:
    """Run backtests comparing different risk configurations.

    Args:
        price_bars: Price history.
        dvol_bars: DVOL history.
        initial_capital: Starting capital.

    Returns:
        Dict mapping config label to result.
    """
    results: dict[str, BacktestResult] = {}

    # Test different risk configurations
    configs = [
        {"max_positions": 3, "max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.10, "label": "Conservative (3 pos, 3% daily, 10% DD)"},
        {"max_positions": 5, "max_daily_loss_pct": 0.05, "max_drawdown_pct": 0.15, "label": "Default (5 pos, 5% daily, 15% DD)"},
        {"max_positions": 7, "max_daily_loss_pct": 0.07, "max_drawdown_pct": 0.20, "label": "Aggressive (7 pos, 7% daily, 20% DD)"},
    ]

    for cfg in configs:
        result = await run_single_backtest(
            price_bars=price_bars,
            dvol_bars=dvol_bars,
            initial_capital=initial_capital,
            label=cfg["label"],
            max_positions=cfg["max_positions"],
            max_daily_loss_pct=cfg["max_daily_loss_pct"],
            max_drawdown_pct=cfg["max_drawdown_pct"],
        )
        results[cfg["label"]] = result

    return results


async def run(args: argparse.Namespace) -> int:
    """Execute the backtest.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code.
    """
    # Load data
    print("Loading historical data...")
    price_bars, dvol_bars = load_historical_data(args.db)

    # Analyze DVOL distribution first
    dvol_values = [bar.close for bar in dvol_bars]
    print(f"\nDVOL Statistics:")
    print(f"  Min:    {min(dvol_values):.1f}")
    print(f"  Max:    {max(dvol_values):.1f}")
    print(f"  Mean:   {sum(dvol_values)/len(dvol_values):.1f}")

    # Count days above thresholds (ETH-calibrated)
    above_73 = sum(1 for v in dvol_values if v > 73)
    above_82 = sum(1 for v in dvol_values if v > 82)
    above_100 = sum(1 for v in dvol_values if v > 100)

    print(f"\nETH DVOL Threshold Frequency:")
    print(f"  > 73 (Size Reduce):     {above_73:>4} days ({above_73/len(dvol_values)*100:.1f}%)")
    print(f"  > 82 (EXTREME_FEAR):    {above_82:>4} days ({above_82/len(dvol_values)*100:.1f}%)")
    print(f"  > 100 (Emergency):      {above_100:>4} days ({above_100/len(dvol_values)*100:.1f}%)")

    if args.compare:
        print("\n" + "="*60)
        print("  RISK CONFIGURATION COMPARISON")
        print("="*60)

        results = await run_risk_comparison(
            price_bars, dvol_bars, args.capital
        )

        # Summary comparison
        print("\n" + "="*60)
        print("  COMPARISON SUMMARY")
        print("="*60)
        print(f"{'Config':<45} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>8}")
        print("-"*80)
        for label, result in results.items():
            print(f"{label:<45} {result.total_return:>10.2%} {result.sharpe_ratio:>8.2f} {result.max_drawdown:>8.2%} {result.total_trades:>8}")

    else:
        # Single backtest with default config
        await run_single_backtest(
            price_bars=price_bars,
            dvol_bars=dvol_bars,
            initial_capital=args.capital,
            label="Default Configuration",
        )

    return 0


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run backtests on historical data"
    )
    parser.add_argument(
        "--db",
        default="data/trading.db",
        help="Database path (default: data/trading.db)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
        help="Initial capital in USD (default: 100000)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run comparison of different risk configurations",
    )

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nBacktest cancelled")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
