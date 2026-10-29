"""
Market data router.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/live")
async def get_live_market_data():
    """Get current market data."""
    # Import here to avoid circular imports
    from main import live_data_service

    if live_data_service is None:
        return {"error": "Service not initialized"}

    return await live_data_service.get_market_data()


@router.get("/regime")
async def get_current_regime():
    """Get current market regime."""
    from main import live_data_service

    if live_data_service is None:
        return {"error": "Service not initialized"}

    market_data = await live_data_service.get_market_data()
    return {
        "regime": market_data.get("regime", "NEUTRAL"),
        "dvol": market_data.get("dvol", 50),
        "iv_rank": market_data.get("iv_rank", 0.5),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
