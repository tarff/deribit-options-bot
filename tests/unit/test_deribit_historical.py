"""Tests for Deribit historical data methods."""

import re
import pytest
from aioresponses import aioresponses

from src.data.deribit_client import DeribitClient


@pytest.fixture
async def client():
    """Create test client."""
    c = DeribitClient(base_url="https://test.deribit.com")
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_get_tradingview_chart_data(client: DeribitClient) -> None:
    """Test fetching OHLCV data for BTC."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r".*/public/get_tradingview_chart_data\?.*"),
            payload={
                "result": {
                    "ticks": [1705363200000, 1705449600000],
                    "open": [97000.0, 97500.0],
                    "high": [98000.0, 98200.0],
                    "low": [96500.0, 97000.0],
                    "close": [97500.0, 97800.0],
                    "volume": [1000.0, 1200.0],
                    "status": "ok",
                }
            },
        )

        data = await client.get_tradingview_chart_data(
            instrument_name="BTC-PERPETUAL",
            resolution="1D",
            start_timestamp=1705363200000,
            end_timestamp=1705449600000,
        )

        assert len(data["ticks"]) == 2
        assert data["close"] == [97500.0, 97800.0]


@pytest.mark.asyncio
async def test_get_historical_volatility(client: DeribitClient) -> None:
    """Test fetching historical volatility data."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r".*/public/get_historical_volatility\?.*"),
            payload={
                "result": [[1705363200000, 45.2], [1705449600000, 46.1]],
            },
        )

        data = await client.get_historical_volatility("BTC")

        assert len(data) == 2
        assert data[0][1] == 45.2  # First volatility value
