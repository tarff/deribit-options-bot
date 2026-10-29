"""Tests for MarketAnalyzer service."""

import pytest
from unittest.mock import AsyncMock

from src.data.market_analyzer import MarketAnalyzer
from src.data.deribit_client import DeribitClient
from src.brain.regime_detector import MarketRegime


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create mock Deribit client."""
    client = AsyncMock(spec=DeribitClient)

    # Mock index price
    client.get_index_price.return_value = 97432.50

    # Mock current DVOL
    client.get_current_dvol.return_value = 52.3

    # Mock historical DVOL (52 weeks of data)
    # Format: [[timestamp, open, high, low, close], ...]
    client.get_volatility_index.return_value = [
        [1705363200000 + i * 86400000, 40.0 + i * 0.5, 42.0 + i * 0.5, 39.0 + i * 0.5, 40.5 + i * 0.5]
        for i in range(365)
    ]

    # Mock historical prices (30 days)
    client.get_tradingview_chart_data.return_value = {
        "ticks": [1705363200000 + i * 86400000 for i in range(30)],
        "close": [95000.0 + i * 100 for i in range(30)],
    }

    return client


@pytest.fixture
def analyzer(mock_client: AsyncMock) -> MarketAnalyzer:
    """Create market analyzer with mock client."""
    return MarketAnalyzer(mock_client)


@pytest.mark.asyncio
async def test_get_current_metrics(analyzer: MarketAnalyzer, mock_client: AsyncMock) -> None:
    """Test fetching and calculating current market metrics."""
    metrics = await analyzer.get_current_metrics()

    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank is not None
    assert metrics.rv_30d is not None
    mock_client.get_index_price.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_regime(analyzer: MarketAnalyzer) -> None:
    """Test getting current market regime."""
    regime = await analyzer.get_current_regime()

    assert isinstance(regime, MarketRegime)


@pytest.mark.asyncio
async def test_analyze_returns_metrics_and_regime(analyzer: MarketAnalyzer) -> None:
    """Test full analysis returns both metrics and regime."""
    result = await analyzer.analyze()

    assert "metrics" in result
    assert "regime" in result
    assert "recommendation" in result
    assert result["metrics"].btc_price > 0
