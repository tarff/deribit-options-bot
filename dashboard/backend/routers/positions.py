"""
Positions router.
"""

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("")
async def get_positions(status: str = Query("open", enum=["open", "closed", "all"])):
    """Get positions by status."""
    from main import live_data_service

    if live_data_service is None:
        return []

    positions = await live_data_service.get_positions()

    # Filter would be applied here based on status
    # For now, return all as "open"
    return positions


@router.get("/live")
async def get_live_positions():
    """Get live positions with real-time Greeks."""
    from main import live_data_service

    if live_data_service is None:
        return []

    return await live_data_service.get_positions()


@router.get("/strategies")
async def get_strategy_positions(status: str = Query("open", enum=["open", "closed", "all"])):
    """Get positions grouped by strategy."""
    from main import live_data_service

    if live_data_service is None:
        return []

    positions = await live_data_service.get_positions()

    # Group positions by strategy (simplified)
    # In production, this would query the database for strategy groupings
    strategies = {}
    for pos in positions:
        strategy_type = pos.get("strategy_type", "MANUAL")
        if strategy_type not in strategies:
            strategies[strategy_type] = {
                "strategy_id": f"{strategy_type.lower()}-001",
                "strategy_type": strategy_type,
                "legs": [],
                "total_pnl": 0,
                "portfolio_delta": 0,
                "portfolio_gamma": 0,
                "portfolio_theta": 0,
                "portfolio_vega": 0,
                "status": "open",
                "opened_at": pos.get("opened_at"),
            }

        strategies[strategy_type]["legs"].append(pos)
        strategies[strategy_type]["total_pnl"] += pos.get("unrealized_pnl", 0)
        strategies[strategy_type]["portfolio_delta"] += pos.get("delta", 0)
        strategies[strategy_type]["portfolio_gamma"] += pos.get("gamma", 0)
        strategies[strategy_type]["portfolio_theta"] += pos.get("theta", 0)
        strategies[strategy_type]["portfolio_vega"] += pos.get("vega", 0)

    return list(strategies.values())


@router.get("/greeks")
async def get_portfolio_greeks():
    """Get aggregated portfolio Greeks."""
    from main import live_data_service

    if live_data_service is None:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

    return await live_data_service.get_portfolio_greeks()


@router.get("/bot")
async def get_bot_positions():
    """Get positions from the bot's internal database.

    This shows what the paper trading bot is tracking, which may differ
    from Deribit API if there are sync issues.
    """
    import sqlite3
    from pathlib import Path
    from services.config_loader import get_configured_database_path

    db_path = Path(get_configured_database_path())

    if not db_path.exists():
        return {"error": f"Database not found: {db_path}", "positions": []}

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get open positions
            cursor.execute("""
                SELECT strategy_id, strategy_type, status, opened_at, entry_price, current_pnl
                FROM positions
                WHERE status = 'open'
            """)
            positions = [dict(row) for row in cursor.fetchall()]

            # Get contracts for each position
            for pos in positions:
                cursor.execute("""
                    SELECT instrument_name, strike, expiry, option_type, direction, quantity
                    FROM position_contracts
                    WHERE strategy_id = ?
                """, (pos["strategy_id"],))
                pos["contracts"] = [dict(row) for row in cursor.fetchall()]

        return {"db_path": str(db_path), "positions": positions}

    except Exception as e:
        return {"error": str(e), "positions": []}
