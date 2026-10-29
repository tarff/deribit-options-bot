"""Tests for live data provider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.dashboard.live_data_provider import LiveDataProvider
from src.dashboard.models import LiveMarketData, LivePosition, AccountInfo
from src.data.deribit_client import DeribitError
from src.data.market_metrics import MarketMetrics
from src.config import Settings, DeribitConfig


@pytest.fixture
def mock_settings() -> Settings:
    """Create mock settings."""
    return Settings(
        deribit=DeribitConfig(
            base_url="https://test.deribit.com",
            api_key="test_key",
            api_secret="test_secret",
        )
    )


@pytest.fixture
def mock_settings_no_creds() -> Settings:
    """Create mock settings without credentials."""
    return Settings(
        deribit=DeribitConfig(
            base_url="https://test.deribit.com",
            api_key="",
            api_secret="",
        )
    )


@pytest.fixture
def provider(mock_settings: Settings) -> LiveDataProvider:
    """Create LiveDataProvider with mock settings."""
    return LiveDataProvider(settings=mock_settings)


def test_has_credentials_true(provider: LiveDataProvider) -> None:
    """Test has_credentials returns True when configured."""
    assert provider.has_credentials is True


def test_has_credentials_false(mock_settings_no_creds: Settings) -> None:
    """Test has_credentials returns False when not configured."""
    provider = LiveDataProvider(settings=mock_settings_no_creds)
    assert provider.has_credentials is False


def test_is_authenticated_false(provider: LiveDataProvider) -> None:
    """Test is_authenticated returns False by default."""
    assert provider.is_authenticated is False


def test_authenticate_success(provider: LiveDataProvider) -> None:
    """Test successful authentication."""
    with patch.object(provider, "_authenticate_async", new_callable=AsyncMock) as mock_auth:
        mock_auth.return_value = "test_token_123"

        result = provider.authenticate()

        assert result is True
        assert provider.is_authenticated is True
        assert provider._access_token == "test_token_123"


def test_authenticate_no_credentials(mock_settings_no_creds: Settings) -> None:
    """Test authentication fails without credentials."""
    provider = LiveDataProvider(settings=mock_settings_no_creds)

    result = provider.authenticate()

    assert result is False


def test_authenticate_api_error(provider: LiveDataProvider) -> None:
    """Test authentication handles API errors."""
    with patch.object(provider, "_authenticate_async", new_callable=AsyncMock) as mock_auth:
        mock_auth.side_effect = DeribitError(10001, "Auth failed")

        result = provider.authenticate()

        assert result is False


def test_get_live_market_data_success(provider: LiveDataProvider) -> None:
    """Test successful market data fetch."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=52.5,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )

    async def mock_get_market_data():
        return LiveMarketData(
            btc_price=metrics.btc_price,
            dvol=metrics.dvol,
            iv_rank=metrics.iv_rank,
            regime="neutral",
            timestamp=datetime.now(timezone.utc),
        )

    with patch.object(provider, "_get_live_market_data_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = LiveMarketData(
            btc_price=97000.0,
            dvol=52.5,
            iv_rank=0.45,
            regime="neutral",
            timestamp=datetime.now(timezone.utc),
        )

        result = provider.get_live_market_data()

        assert result is not None
        assert isinstance(result, LiveMarketData)
        assert result.btc_price == 97000.0
        assert result.dvol == 52.5
        assert result.iv_rank == 0.45
        assert result.regime == "neutral"


def test_get_live_market_data_api_error(provider: LiveDataProvider) -> None:
    """Test market data fetch handles API errors."""
    with patch.object(provider, "_get_live_market_data_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = DeribitError(10001, "API error")

        result = provider.get_live_market_data()

        assert result is None


def test_get_live_positions_not_authenticated(provider: LiveDataProvider) -> None:
    """Test positions fetch returns None when not authenticated."""
    result = provider.get_live_positions()

    assert result is None


def test_get_live_positions_success(provider: LiveDataProvider) -> None:
    """Test successful positions fetch."""
    provider._access_token = "test_token"

    with patch.object(provider, "_get_live_positions_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            LivePosition(
                instrument="BTC-28MAR25-100000-P",
                size=-0.1,
                direction="sell",
                average_price=0.05,
                mark_price=0.045,
                pnl=50.0,
                delta=-0.25,
                gamma=0.001,
                theta=15.5,
                vega=-12.3,
            )
        ]

        result = provider.get_live_positions()

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], LivePosition)
        assert result[0].instrument == "BTC-28MAR25-100000-P"
        assert result[0].size == -0.1
        assert result[0].delta == -0.25


def test_get_live_positions_api_error(provider: LiveDataProvider) -> None:
    """Test positions fetch handles API errors."""
    provider._access_token = "test_token"

    with patch.object(provider, "_get_live_positions_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = DeribitError(10001, "API error")

        result = provider.get_live_positions()

        assert result is None


def test_get_account_info_not_authenticated(provider: LiveDataProvider) -> None:
    """Test account info fetch returns None when not authenticated."""
    result = provider.get_account_info()

    assert result is None


def test_get_account_info_success(provider: LiveDataProvider) -> None:
    """Test successful account info fetch."""
    provider._access_token = "test_token"

    with patch.object(provider, "_get_account_info_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = AccountInfo(
            equity=1.5,
            balance=1.48,
            margin_balance=1.45,
            initial_margin=0.1,
            maintenance_margin=0.05,
            equity_usd=145500.0,
        )

        result = provider.get_account_info()

        assert result is not None
        assert isinstance(result, AccountInfo)
        assert result.equity == 1.5
        assert result.balance == 1.48
        assert result.equity_usd == 145500.0


def test_get_account_info_api_error(provider: LiveDataProvider) -> None:
    """Test account info fetch handles API errors."""
    provider._access_token = "test_token"

    with patch.object(provider, "_get_account_info_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = DeribitError(10001, "API error")

        result = provider.get_account_info()

        assert result is None


def test_get_all_live_data_unauthenticated(provider: LiveDataProvider) -> None:
    """Test get_all_live_data when not authenticated returns only market data."""
    with patch.object(provider, "_get_all_live_data_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (
            LiveMarketData(
                btc_price=97000.0,
                dvol=52.5,
                iv_rank=0.45,
                regime="neutral",
                timestamp=datetime.now(timezone.utc),
            ),
            None,
            None,
        )

        market_data, positions, account_info = provider.get_all_live_data()

        assert market_data is not None
        assert market_data.btc_price == 97000.0
        assert positions is None
        assert account_info is None


def test_get_all_live_data_authenticated(provider: LiveDataProvider) -> None:
    """Test get_all_live_data when authenticated returns all data."""
    provider._access_token = "test_token"

    with patch.object(provider, "_get_all_live_data_async", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (
            LiveMarketData(
                btc_price=97000.0,
                dvol=52.5,
                iv_rank=0.45,
                regime="neutral",
                timestamp=datetime.now(timezone.utc),
            ),
            [
                LivePosition(
                    instrument="BTC-28MAR25-100000-P",
                    size=-0.1,
                    direction="sell",
                    average_price=0.05,
                    mark_price=0.045,
                    pnl=50.0,
                    delta=-0.25,
                    gamma=0.001,
                    theta=15.5,
                    vega=-12.3,
                )
            ],
            AccountInfo(
                equity=1.5,
                balance=1.48,
                margin_balance=1.45,
                initial_margin=0.1,
                maintenance_margin=0.05,
                equity_usd=145500.0,
            ),
        )

        market_data, positions, account_info = provider.get_all_live_data()

        assert market_data is not None
        assert positions is not None
        assert len(positions) == 1
        assert account_info is not None
        assert account_info.equity == 1.5


def test_provider_creates_from_settings() -> None:
    """Test provider loads settings when not provided."""
    with patch("src.dashboard.live_data_provider.load_settings") as mock_load:
        mock_load.return_value = Settings(
            deribit=DeribitConfig(
                base_url="https://test.deribit.com",
                api_key="key",
                api_secret="secret",
            )
        )
        provider = LiveDataProvider()

        assert provider._settings.deribit.base_url == "https://test.deribit.com"
        assert provider.has_credentials is True
