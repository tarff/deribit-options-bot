"""
Trade history router.

Uses real data from the trading.db trades table when available.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()


def get_db_service():
    """Get database service instance with default path."""
    from services.db_service import DatabaseService
    return DatabaseService()  # Uses default path from db_service.py


@router.get("")
async def get_trades(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    strategy_type: Optional[str] = None,
):
    """Get trade history from database."""
    db = get_db_service()

    # Check if trades table exists
    if not db.table_exists("trades"):
        return []

    return db.get_trades(limit=limit, offset=offset, strategy_type=strategy_type)


@router.get("/recent")
async def get_recent_trades(hours: int = Query(24, ge=1, le=168)):
    """Get trades from the last N hours."""
    db = get_db_service()

    if not db.table_exists("trades"):
        return []

    # Get all recent trades and filter by time
    trades = db.get_trades(limit=1000)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    return [
        t for t in trades
        if datetime.fromisoformat(t.get("timestamp", "2000-01-01")) > cutoff
    ]


@router.get("/by-strategy/{strategy_type}")
async def get_trades_by_strategy(strategy_type: str, limit: int = 50):
    """Get trades for a specific strategy type."""
    db = get_db_service()

    if not db.table_exists("trades"):
        return []

    return db.get_trades(limit=limit, strategy_type=strategy_type.lower())
