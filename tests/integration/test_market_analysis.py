"""Integration tests for market analysis pipeline."""

import pytest
from unittest.mock import AsyncMock

from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer
from src.brain.regime_detector import MarketRegime
from src.persistence.database import Database
from src.persistence.repositories import SnapshotRepository
from src.persistence.models import MarketSnapshot


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create mock Deribit client with realistic data."""
    client = AsyncMock(spec=DeribitClient)

    # Realistic BTC price
    client.get_index_price.return_value = 97432.50

    # Current DVOL at 52.3 (moderate)
    client.get_current_dvol.return_value = 52.3

    # Historical DVOL: range 35-75 over past year
    # Current 52.3 should give IV Rank around 0.43
    # Format: [[timestamp, open, high, low, close], ...]
    client.get_volatility_index.return_value = [
        [1705363200000 + i * 86400000, 35.0 + (i % 40), 37.0 + (i % 40), 34.0 + (i % 40), 35.5 + (i % 40)]
        for i in range(365)
    ]

    # Historical prices with some volatility
    client.get_tradingview_chart_data.return_value = {
        "ticks": [1705363200000 + i * 86400000 for i in range(30)],
        "close": [95000.0 + (i * 100) + ((i % 5) * 200) for i in range(30)],
    }

    return client


@pytest.fixture
def db(tmp_path):
    """Create test database."""
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    yield database
    database.close()


@pytest.mark.asyncio
async def test_full_analysis_pipeline(mock_client: AsyncMock, db: Database) -> None:
    """Test complete flow: fetch data -> calculate metrics -> detect regime -> persist."""
    # 1. Analyze market
    analyzer = MarketAnalyzer(mock_client)
    result = await analyzer.analyze()

    # 2. Verify metrics calculated
    metrics = result["metrics"]
    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank is not None
    assert 0.0 <= metrics.iv_rank <= 1.0
    assert metrics.rv_30d is not None
    assert metrics.rv_30d > 0

    # 3. Verify regime detected
    regime = result["regime"]
    assert isinstance(regime, MarketRegime)

    # 4. Verify recommendation provided
    recommendation = result["recommendation"]
    assert recommendation.strategy is not None or recommendation.action == "close_all"

    # 5. Persist as snapshot
    snapshot_repo = SnapshotRepository(db)
    snapshot_repo.save(MarketSnapshot(
        btc_price=metrics.btc_price,
        dvol=metrics.dvol,
        iv_rank=metrics.iv_rank,
        iv_percentile=metrics.iv_percentile,
        rv_7d=metrics.rv_7d,
        rv_30d=metrics.rv_30d,
        iv_rv_spread=metrics.iv_rv_spread,
        regime=regime.value,
        active_strategy=recommendation.strategy,
        timestamp=metrics.timestamp,
    ))

    # 6. Verify persisted correctly
    saved = snapshot_repo.get_latest()
    assert saved is not None
    assert saved.btc_price == 97432.50
    assert saved.regime == regime.value


@pytest.mark.asyncio
async def test_regime_transitions(mock_client: AsyncMock) -> None:
    """Test regime changes as market conditions change."""
    analyzer = MarketAnalyzer(mock_client)

    # Scenario 1: Normal market
    mock_client.get_current_dvol.return_value = 50.0
    result = await analyzer.analyze()
    # With moderate DVOL and no extreme conditions, should be NEUTRAL
    assert result["regime"] in [MarketRegime.NEUTRAL, MarketRegime.HIGH_IV_OVERPRICED]

    # Scenario 2: DVOL spike - no longer triggers EXTREME_FEAR
    # Regime detector classifies market conditions; PositionSizer handles risk
    mock_client.get_current_dvol.return_value = 85.0
    result = await analyzer.analyze()
    # Without IV rank/spread data from mock, falls to NEUTRAL or HIGH_IV_OVERPRICED
    assert result["regime"] in [MarketRegime.NEUTRAL, MarketRegime.HIGH_IV_OVERPRICED]

    # Scenario 3: Elevated DVOL with high IV conditions
    # DVOL 70 + high IV Rank = HIGH_IV_OVERPRICED (sell premium)
    # Position sizing handles DVOL-based reduction separately
    mock_client.get_current_dvol.return_value = 70.0
    result = await analyzer.analyze()
    assert result["regime"] == MarketRegime.HIGH_IV_OVERPRICED
