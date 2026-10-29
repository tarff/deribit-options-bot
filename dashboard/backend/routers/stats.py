"""
Statistics router.

Uses real data from the trading.db when available.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query

router = APIRouter()


def get_db_service():
    """Get database service instance with default path."""
    from services.db_service import DatabaseService
    return DatabaseService()  # Uses default path from db_service.py


@router.get("")
async def get_trade_stats():
    """Get overall trading statistics from database."""
    db = get_db_service()

    # Check if trades table exists
    if not db.table_exists("trades"):
        return _empty_stats()

    stats = db.get_trade_stats()

    # Add strategy breakdown if we have trades
    if stats.get("total_trades", 0) > 0:
        stats["by_strategy"] = _get_strategy_breakdown(db)

    return stats


def _get_strategy_breakdown(db) -> dict:
    """Get P&L breakdown by strategy type."""
    strategies = ["wheel", "iron_condor", "vol_arb", "gamma_scalp", "calendar_spread"]
    breakdown = {}

    for strategy in strategies:
        trades = db.get_trades(limit=10000, strategy_type=strategy)
        if trades:
            total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
            winning = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
            total = len(trades)

            breakdown[strategy] = {
                "trades": total,
                "win_rate": (winning / total * 100) if total > 0 else 0,
                "total_pnl": round(total_pnl, 4),
                "avg_pnl": round(total_pnl / total, 4) if total > 0 else 0,
            }

    return breakdown


@router.get("/regimes")
async def get_regime_stats(days: int = Query(30, ge=1, le=365)):
    """Get regime distribution statistics from market snapshots."""
    db = get_db_service()

    if not db.table_exists("market_snapshots"):
        return []

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)
    snapshots = db.get_market_snapshots(start_time, end_time)

    if not snapshots:
        return []

    # Count regimes
    regime_counts: dict[str, int] = {}
    for snap in snapshots:
        regime = snap.get("regime", "UNKNOWN")
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

    total = sum(regime_counts.values())

    return [
        {
            "regime": regime,
            "count": count,
            "percentage": round(count / total * 100, 1) if total > 0 else 0,
        }
        for regime, count in sorted(regime_counts.items(), key=lambda x: -x[1])
    ]


@router.get("/daily")
async def get_daily_stats(days: int = Query(30, ge=1, le=90)):
    """Get daily P&L statistics from daily_performance table."""
    db = get_db_service()

    if not db.table_exists("daily_performance"):
        return []

    try:
        with db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT date, pnl,
                       SUM(pnl) OVER (ORDER BY date) as cumulative,
                       trades_closed as trades
                FROM daily_performance
                WHERE date >= date('now', ?)
                ORDER BY date ASC
                """,
                [f"-{days} days"],
            )
            rows = cursor.fetchall()
            return [
                {
                    "date": row["date"],
                    "pnl": round(row["pnl"] or 0, 4),
                    "cumulative": round(row["cumulative"] or 0, 4),
                    "trades": row["trades"] or 0,
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Error fetching daily stats: {e}")
        return []


@router.get("/performance")
async def get_performance_metrics():
    """Get detailed performance metrics."""
    db = get_db_service()

    if not db.table_exists("trades"):
        return _empty_performance()

    stats = db.get_trade_stats()
    total_trades = stats.get("total_trades", 0)

    if total_trades == 0:
        return _empty_performance()

    # Calculate basic metrics from available data
    avg_win = stats.get("avg_win", 0) or 0
    avg_loss = abs(stats.get("avg_loss", 0) or 0)
    win_rate = stats.get("win_rate", 0) / 100

    # Simplified Sharpe estimate (would need daily returns for accurate calc)
    profit_factor = stats.get("profit_factor", 0)

    return {
        "sharpe_ratio": 0,  # Needs daily returns
        "sortino_ratio": 0,  # Needs daily returns
        "calmar_ratio": 0,  # Needs drawdown data
        "max_drawdown": 0,  # Needs equity curve
        "max_drawdown_duration_days": 0,
        "recovery_factor": 0,
        "avg_trade_duration_hours": 0,  # Needs trade timing data
        "avg_trades_per_day": 0,
        "best_day": 0,
        "worst_day": 0,
        "consecutive_wins": 0,
        "consecutive_losses": 0,
        "profit_factor": profit_factor,
        "win_rate": win_rate * 100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


def _empty_stats() -> dict:
    """Return empty stats when no data available."""
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "avg_win": 0,
        "avg_loss": 0,
        "profit_factor": 0,
        "by_strategy": {},
    }


def _empty_performance() -> dict:
    """Return empty performance metrics."""
    return {
        "sharpe_ratio": 0,
        "sortino_ratio": 0,
        "calmar_ratio": 0,
        "max_drawdown": 0,
        "max_drawdown_duration_days": 0,
        "recovery_factor": 0,
        "avg_trade_duration_hours": 0,
        "avg_trades_per_day": 0,
        "best_day": 0,
        "worst_day": 0,
        "consecutive_wins": 0,
        "consecutive_losses": 0,
        "profit_factor": 0,
        "win_rate": 0,
        "avg_win": 0,
        "avg_loss": 0,
    }
