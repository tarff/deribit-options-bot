"""Tests for Deribit API client."""

import re
import pytest
from collections.abc import AsyncGenerator
from aioresponses import aioresponses

from src.data.deribit_client import DeribitClient, DeribitError


@pytest.fixture
async def client() -> AsyncGenerator[DeribitClient, None]:
    """Create test client with cleanup."""
    c = DeribitClient(
        base_url="https://test.deribit.com",
        api_key="test_key",
        api_secret="test_secret",
    )
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_authenticate_success(client: DeribitClient) -> None:
    """Test successful authentication."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r"https://test\.deribit\.com/api/v2/public/auth\?.*"),
            payload={
                "result": {
                    "access_token": "test_token_123",
                    "expires_in": 900,
                    "refresh_token": "refresh_123",
                    "token_type": "bearer",
                }
            },
        )

        await client.authenticate()

        assert client.access_token == "test_token_123"
        assert client.is_authenticated


@pytest.mark.asyncio
async def test_get_index_price(client: DeribitClient) -> None:
    """Test fetching BTC index price."""
    with aioresponses() as mocked:
        mocked.get(
            "https://test.deribit.com/api/v2/public/get_index_price?index_name=btc_usd",
            payload={
                "result": {
                    "index_price": 97432.50,
                    "estimated_delivery_price": 97430.00,
                }
            },
        )

        price = await client.get_index_price("btc_usd")

        assert price == 97432.50


@pytest.mark.asyncio
async def test_get_account_summary(client: DeribitClient) -> None:
    """Test fetching account summary (private endpoint)."""
    with aioresponses() as mocked:
        # First authenticate
        mocked.get(
            re.compile(r"https://test\.deribit\.com/api/v2/public/auth\?.*"),
            payload={
                "result": {
                    "access_token": "test_token_123",
                    "expires_in": 900,
                }
            },
        )
        # Then get account
        mocked.get(
            "https://test.deribit.com/api/v2/private/get_account_summary?currency=BTC",
            payload={
                "result": {
                    "equity": 1.5,
                    "balance": 1.48,
                    "available_funds": 1.2,
                    "margin_balance": 1.45,
                }
            },
        )

        await client.authenticate()
        summary = await client.get_account_summary("BTC")

        assert summary["equity"] == 1.5
        assert summary["balance"] == 1.48


@pytest.mark.asyncio
async def test_get_positions(client: DeribitClient) -> None:
    """Test fetching open positions."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r"https://test\.deribit\.com/api/v2/public/auth\?.*"),
            payload={"result": {"access_token": "test_token_123", "expires_in": 900}},
        )
        mocked.get(
            "https://test.deribit.com/api/v2/private/get_positions?currency=BTC",
            payload={
                "result": [
                    {
                        "instrument_name": "BTC-28MAR25-100000-P",
                        "size": -0.1,
                        "direction": "sell",
                        "delta": -0.25,
                        "gamma": 0.001,
                        "theta": 15.5,
                        "vega": -12.3,
                    }
                ]
            },
        )

        await client.authenticate()
        positions = await client.get_positions("BTC")

        assert len(positions) == 1
        assert positions[0]["instrument_name"] == "BTC-28MAR25-100000-P"
        assert positions[0]["delta"] == -0.25


@pytest.mark.asyncio
async def test_handles_api_error(client: DeribitClient) -> None:
    """Test that API errors are properly raised as DeribitError."""
    with aioresponses() as mocked:
        mocked.get(
            "https://test.deribit.com/api/v2/public/get_index_price?index_name=btc_usd",
            payload={"error": {"code": 10001, "message": "Invalid params"}},
        )

        with pytest.raises(DeribitError) as exc:
            await client.get_index_price("btc_usd")

        assert exc.value.code == 10001
        assert exc.value.message == "Invalid params"


@pytest.mark.asyncio
async def test_get_volatility_index(client: DeribitClient) -> None:
    """Test fetching DVOL index data."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r"https://test\.deribit\.com/api/v2/public/get_volatility_index_data\?.*"),
            payload={
                "result": {
                    "data": [[1705420800000, 52.3, 51.8, 53.1, 52.0]],
                    "continuation": None,
                }
            },
        )

        dvol_data = await client.get_volatility_index("BTC")

        assert len(dvol_data) == 1
        assert dvol_data[0][1] == 52.3  # Open DVOL


@pytest.mark.asyncio
async def test_get_current_dvol(client: DeribitClient) -> None:
    """Test getting current DVOL value."""
    with aioresponses() as mocked:
        mocked.get(
            "https://test.deribit.com/api/v2/public/get_index_price?index_name=dvol_btc",
            payload={
                "result": {
                    "index_price": 52.3,
                    "estimated_delivery_price": 52.0,
                }
            },
        )

        dvol = await client.get_current_dvol("BTC")

        assert dvol == 52.3
