"""Tests for backtest data fetcher."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.backtest.data_fetcher import HistoricalDataFetcher, HistoricalBar


@pytest.fixture
def mock_client() -> MagicMock:
    """Create mock Deribit client."""
    client = MagicMock()
    client.get_tradingview_chart_data = AsyncMock(return_value={
        "ticks": [1704067200000, 1704153600000],  # 2024-01-01, 2024-01-02
        "open": [42000.0, 42500.0],
        "high": [43000.0, 43500.0],
        "low": [41500.0, 42000.0],
        "close": [42500.0, 43000.0],
        "volume": [1000.0, 1200.0],
    })
    client.get_volatility_index = AsyncMock(return_value=[
        [1704067200000, 55.0, 58.0, 54.0, 56.0],  # DVOL OHLC
        [1704153600000, 56.0, 60.0, 55.0, 58.0],
    ])
    return client


@pytest.mark.asyncio
async def test_fetch_price_history(mock_client: MagicMock) -> None:
    """Test fetching historical price bars."""
    fetcher = HistoricalDataFetcher(mock_client)

    bars = await fetcher.fetch_price_history(
        instrument="BTC-PERPETUAL",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 3, tzinfo=timezone.utc),
        resolution="1D",
    )

    assert len(bars) == 2
    assert bars[0].close == 42500.0
    assert bars[1].close == 43000.0


@pytest.mark.asyncio
async def test_fetch_dvol_history(mock_client: MagicMock) -> None:
    """Test fetching historical DVOL."""
    fetcher = HistoricalDataFetcher(mock_client)

    dvol_bars = await fetcher.fetch_dvol_history(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )

    assert len(dvol_bars) == 2
    assert dvol_bars[0].close == 56.0  # DVOL close
    assert dvol_bars[1].close == 58.0


def test_calculate_iv_rank() -> None:
    """Test IV rank calculation."""
    # Create DVOL bars with known values
    dvol_bars = [
        HistoricalBar(
            timestamp=datetime(2024, 1, i, tzinfo=timezone.utc),
            open=40.0 + i, high=45.0 + i, low=35.0 + i, close=40.0 + i, volume=0.0,
        )
        for i in range(1, 11)  # DVOL: 41, 42, ..., 50
    ]

    iv_ranks = HistoricalDataFetcher.calculate_iv_rank(dvol_bars, lookback=10)

    # Last bar has DVOL=50, prior window [41..49], rank = (50-41)/(49-41) = 9/8 = 1.125
    # IV rank > 1.0 is expected when current bar exceeds prior window max (no look-ahead)
    last_ts = datetime(2024, 1, 10, tzinfo=timezone.utc)
    assert last_ts in iv_ranks
    assert iv_ranks[last_ts] == pytest.approx(1.125)

    # Bar 2 (DVOL=42) with prior window=[41], needs >=2 bars -> first with data is bar 3
    # Bar 3: DVOL=43, prior window [41, 42], rank = (43-41)/(42-41) = 2.0
    third_ts = datetime(2024, 1, 3, tzinfo=timezone.utc)
    assert third_ts in iv_ranks
    assert iv_ranks[third_ts] == pytest.approx(2.0)


def test_calculate_iv_rank_empty_bars() -> None:
    """Test IV rank with empty input."""
    iv_ranks = HistoricalDataFetcher.calculate_iv_rank([])
    assert iv_ranks == {}


def test_calculate_realized_vol() -> None:
    """Test realized volatility calculation."""
    # Create price bars with known returns
    # Starting at 100, each day +1% -> log returns ~0.01
    price = 100.0
    price_bars = []
    for i in range(1, 32):  # 31 days
        price_bars.append(HistoricalBar(
            timestamp=datetime(2024, 1, i, tzinfo=timezone.utc),
            open=price, high=price * 1.01, low=price * 0.99, close=price, volume=1000.0,
        ))
        price = price * 1.01  # 1% daily return

    rv_values = HistoricalDataFetcher.calculate_realized_vol(price_bars, lookback=30)

    # Should have values for days 2-31 (need at least 2 returns for std)
    assert len(rv_values) > 0

    # With constant 1% daily returns, std should be very small (close to 0)
    # The annualized vol should be near 0 since all returns are identical
    for rv in rv_values.values():
        assert rv < 5.0  # Should be very low with constant returns


def test_calculate_realized_vol_empty_bars() -> None:
    """Test realized vol with empty input."""
    rv_values = HistoricalDataFetcher.calculate_realized_vol([])
    assert rv_values == {}


@pytest.mark.asyncio
async def test_parse_ohlcv_misaligned_arrays(mock_client: MagicMock) -> None:
    """Test _parse_ohlcv handles misaligned arrays safely."""
    mock_client.get_tradingview_chart_data = AsyncMock(return_value={
        "ticks": [1704067200000, 1704153600000, 1704240000000],  # 3 ticks
        "open": [42000.0, 42500.0],  # Only 2 values
        "high": [43000.0, 43500.0],
        "low": [41500.0, 42000.0],
        "close": [42500.0, 43000.0],
        "volume": [1000.0],  # Only 1 value
    })
    fetcher = HistoricalDataFetcher(mock_client)

    bars = await fetcher.fetch_price_history(
        instrument="BTC-PERPETUAL",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 4, tzinfo=timezone.utc),
    )

    # Should only return 2 bars (min length of OHLC arrays)
    assert len(bars) == 2
