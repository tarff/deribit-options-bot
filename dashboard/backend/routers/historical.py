"""
Historical data router.

Uses real data from the trading.db historical_data table when available,
falls back to mock data generation when no real data exists.
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Request

router = APIRouter()


def get_db_service():
    """Get database service instance with default path."""
    from services.db_service import DatabaseService
    return DatabaseService()  # Uses default path from db_service.py


@router.get("")
async def get_historical_data(
    request: Request,
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    resolution: str = Query("1h", enum=["15m", "1h", "4h", "1d"]),
):
    """Get historical price and DVOL data."""
    try:
        start_date = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_date = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD"}

    # Validate range (max 365 days to prevent large DB scans)
    range_days = (end_date - start_date).days
    if range_days > 365:
        return {"error": "Date range cannot exceed 365 days"}
    if range_days < 0:
        return {"error": "End date must be after start date"}

    # Try to get real data from database
    db = get_db_service()
    raw_data = db.get_historical_prices(start_date, end_date)

    if raw_data:
        # Convert to expected format
        price_data = []
        dvol_data = []

        for row in raw_data:
            price_data.append({
                "timestamp": row["timestamp"],
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
                "volume": round(row["volume"], 2),
            })
            dvol_data.append({
                "timestamp": row["timestamp"],
                "value": round(row["dvol"], 2),
            })

        # Resample if needed (data is daily, may want hourly)
        if resolution != "1d" and len(price_data) > 0:
            price_data = _resample_to_resolution(price_data, resolution)
            dvol_data = _resample_dvol_to_resolution(dvol_data, resolution)

        return {
            "price": price_data,
            "btc": price_data,  # Legacy key for backwards compatibility
            "dvol": dvol_data,
        }

    # No real data, return empty
    return {
        "price": [],
        "btc": [],
        "dvol": [],
    }


@router.get("/btc")
async def get_btc_history(request: Request, days: int = Query(7, ge=1, le=365)):
    """Get price history for configured currency."""
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    db = get_db_service()
    raw_data = db.get_historical_prices(start_date, end_date)

    if raw_data:
        return [
            {
                "timestamp": row["timestamp"],
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
                "volume": round(row["volume"], 2),
            }
            for row in raw_data
        ]

    return []


@router.get("/dvol")
async def get_dvol_history(days: int = Query(7, ge=1, le=365)):
    """Get DVOL history."""
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    db = get_db_service()
    raw_data = db.get_historical_prices(start_date, end_date)

    if raw_data:
        return [
            {
                "timestamp": row["timestamp"],
                "value": round(row["dvol"], 2),
            }
            for row in raw_data
        ]

    return []


def _resample_to_resolution(
    daily_data: list[dict], resolution: str
) -> list[dict]:
    """Expand daily data to finer resolution by interpolation.

    Creates smoother intraday data from daily OHLCV.
    """
    resolution_hours = {
        "15m": 0.25,
        "1h": 1,
        "4h": 4,
        "1d": 24,
    }
    hours = resolution_hours.get(resolution, 1)
    periods_per_day = int(24 / hours)

    if periods_per_day <= 1:
        return daily_data

    result = []
    for i, day in enumerate(daily_data):
        ts = datetime.fromisoformat(day["timestamp"])
        day_open = day["open"]
        day_close = day["close"]
        day_high = day["high"]
        day_low = day["low"]
        day_volume = day["volume"]

        # Distribute the day's range across periods
        for p in range(periods_per_day):
            period_ts = ts + timedelta(hours=p * hours)
            # Linear interpolation from open to close
            progress = (p + 1) / periods_per_day
            price = day_open + (day_close - day_open) * progress

            # Add some variation within high/low bounds
            high = min(day_high, price * 1.002)
            low = max(day_low, price * 0.998)

            result.append({
                "timestamp": period_ts.isoformat(),
                "open": round(day_open + (day_close - day_open) * (p / periods_per_day), 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(price, 2),
                "volume": round(day_volume / periods_per_day, 2),
            })

    return result


def _resample_dvol_to_resolution(
    daily_data: list[dict], resolution: str
) -> list[dict]:
    """Expand daily DVOL data to finer resolution."""
    resolution_hours = {
        "15m": 0.25,
        "1h": 1,
        "4h": 4,
        "1d": 24,
    }
    hours = resolution_hours.get(resolution, 1)
    periods_per_day = int(24 / hours)

    if periods_per_day <= 1:
        return daily_data

    result = []
    for i, day in enumerate(daily_data):
        ts = datetime.fromisoformat(day["timestamp"])
        value = day["value"]

        # Get next day's value for interpolation
        next_value = daily_data[i + 1]["value"] if i + 1 < len(daily_data) else value

        for p in range(periods_per_day):
            period_ts = ts + timedelta(hours=p * hours)
            progress = p / periods_per_day
            interpolated = value + (next_value - value) * progress

            result.append({
                "timestamp": period_ts.isoformat(),
                "value": round(interpolated, 2),
            })

    return result
