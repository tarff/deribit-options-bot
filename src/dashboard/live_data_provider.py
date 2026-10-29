"""Live data provider for real-time dashboard.

Provides sync wrappers around async DeribitClient and MarketAnalyzer
for compatibility with Streamlit's synchronous execution model.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import load_settings, Settings
from src.data.deribit_client import DeribitClient, DeribitError
from src.data.market_analyzer import MarketAnalyzer
from src.brain.regime_detector import RegimeDetector
from src.dashboard.models import LiveMarketData, LivePosition, AccountInfo

logger = logging.getLogger(__name__)


class LiveDataProvider:
    """Synchronous wrapper for fetching live data from Deribit.

    Creates fresh client connections for each request to avoid
    event loop and session issues with Streamlit's execution model.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Initialize live data provider.

        Args:
            settings: Application settings. If None, loads from config.
        """
        self._settings = settings or load_settings()
        self._access_token: Optional[str] = None
        self._currency = self._settings.trading.currency.upper()
        self._is_linear = self._settings.trading.settlement == "linear"

    def _create_client(self) -> DeribitClient:
        """Create a fresh DeribitClient instance."""
        client = DeribitClient(
            base_url=self._settings.deribit.base_url,
            api_key=self._settings.deribit.api_key,
            api_secret=self._settings.deribit.api_secret,
        )
        # Restore access token if we've authenticated before
        if self._access_token:
            client.access_token = self._access_token
        return client

    @property
    def is_authenticated(self) -> bool:
        """Check if we have a valid access token."""
        return self._access_token is not None

    @property
    def has_credentials(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self._settings.deribit.api_key and self._settings.deribit.api_secret)

    @property
    def currency(self) -> str:
        """Get the configured trading currency."""
        return self._currency

    @property
    def is_linear(self) -> bool:
        """Whether using USDC-settled linear options."""
        return self._is_linear

    @property
    def _account_currency(self) -> str:
        """Currency to use for account/position API calls.

        Linear (USDC) options are settled in USDC, so account
        and position queries use 'USDC' instead of the underlying.
        """
        return "USDC" if self._is_linear else self._currency

    def authenticate(self) -> bool:
        """Authenticate with Deribit API.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        if not self.has_credentials:
            logger.warning("No API credentials configured")
            return False

        try:
            self._access_token = asyncio.run(self._authenticate_async())
            return True
        except DeribitError as e:
            logger.error(f"Authentication failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    async def _authenticate_async(self) -> str:
        """Async authentication helper."""
        client = self._create_client()
        try:
            await client.authenticate()
            return client.access_token  # type: ignore
        finally:
            await client.close()

    def get_live_market_data(self) -> Optional[LiveMarketData]:
        """Fetch current market data and regime.

        Returns:
            LiveMarketData with current values, or None on error.
        """
        try:
            return asyncio.run(self._get_live_market_data_async())
        except DeribitError as e:
            logger.error(f"Failed to fetch market data: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return None

    async def _get_live_market_data_async(self) -> LiveMarketData:
        """Async helper to fetch market data."""
        client = self._create_client()
        try:
            analyzer = MarketAnalyzer(client, RegimeDetector(), currency=self._currency)
            analysis = await analyzer.analyze()
            metrics = analysis["metrics"]
            regime = analysis["regime"]

            return LiveMarketData(
                btc_price=metrics.btc_price,
                dvol=metrics.dvol,
                iv_rank=metrics.iv_rank,
                regime=regime.value,
                timestamp=datetime.now(timezone.utc),
            )
        finally:
            await client.close()

    def get_live_positions(self) -> Optional[list[LivePosition]]:
        """Fetch current open positions with Greeks.

        Returns:
            List of LivePosition objects, or None on error.
            Returns empty list if authenticated but no positions.
        """
        if not self.is_authenticated:
            logger.warning("Cannot fetch positions: not authenticated")
            return None

        try:
            return asyncio.run(self._get_live_positions_async())
        except DeribitError as e:
            logger.error(f"Failed to fetch positions: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return None

    async def _get_live_positions_async(self) -> list[LivePosition]:
        """Async helper to fetch positions."""
        client = self._create_client()
        try:
            positions_data = await client.get_positions(currency=self._account_currency)
            positions = []

            for pos in positions_data:
                # Skip positions with zero size
                if pos.get("size", 0) == 0:
                    continue

                positions.append(
                    LivePosition(
                        instrument=pos.get("instrument_name", ""),
                        size=pos.get("size", 0),
                        direction=pos.get("direction", ""),
                        average_price=pos.get("average_price", 0),
                        mark_price=pos.get("mark_price", 0),
                        pnl=pos.get("floating_profit_loss", 0),
                        delta=pos.get("delta", 0),
                        gamma=pos.get("gamma", 0),
                        theta=pos.get("theta", 0),
                        vega=pos.get("vega", 0),
                    )
                )

            return positions
        finally:
            await client.close()

    def get_account_info(self) -> Optional[AccountInfo]:
        """Fetch account summary.

        Returns:
            AccountInfo with account details, or None on error.
        """
        if not self.is_authenticated:
            logger.warning("Cannot fetch account info: not authenticated")
            return None

        try:
            return asyncio.run(self._get_account_info_async())
        except DeribitError as e:
            logger.error(f"Failed to fetch account info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching account info: {e}")
            return None

    async def _get_account_info_async(self) -> AccountInfo:
        """Async helper to fetch account info."""
        client = self._create_client()
        try:
            summary = await client.get_account_summary(currency=self._account_currency)

            equity = summary.get("equity", 0)

            if self._is_linear:
                # USDC account: equity is already in USD
                equity_usd = equity
            else:
                # Crypto account: convert to USD using index price
                index_name = f"{self._currency.lower()}_usd"
                price = await client.get_index_price(index_name)
                equity_usd = equity * price

            return AccountInfo(
                equity=equity,
                balance=summary.get("balance", 0),
                margin_balance=summary.get("margin_balance", 0),
                initial_margin=summary.get("initial_margin", 0),
                maintenance_margin=summary.get("maintenance_margin", 0),
                equity_usd=equity_usd,
            )
        finally:
            await client.close()

    def get_all_live_data(
        self,
    ) -> tuple[Optional[LiveMarketData], Optional[list[LivePosition]], Optional[AccountInfo]]:
        """Fetch all live data in a single call.

        More efficient than calling individual methods as it reuses
        the same async session.

        Returns:
            Tuple of (market_data, positions, account_info).
            Any component may be None on error.
        """
        try:
            return asyncio.run(self._get_all_live_data_async())
        except Exception as e:
            logger.error(f"Error fetching all live data: {e}")
            return None, None, None

    async def _get_all_live_data_async(
        self,
    ) -> tuple[Optional[LiveMarketData], Optional[list[LivePosition]], Optional[AccountInfo]]:
        """Async helper to fetch all data efficiently."""
        client = self._create_client()
        market_data: Optional[LiveMarketData] = None
        positions: Optional[list[LivePosition]] = None
        account_info: Optional[AccountInfo] = None

        try:
            # Always fetch market data (public endpoint)
            try:
                analyzer = MarketAnalyzer(client, RegimeDetector(), currency=self._currency)
                analysis = await analyzer.analyze()
                metrics = analysis["metrics"]
                regime = analysis["regime"]

                market_data = LiveMarketData(
                    btc_price=metrics.btc_price,
                    dvol=metrics.dvol,
                    iv_rank=metrics.iv_rank,
                    regime=regime.value,
                    timestamp=datetime.now(timezone.utc),
                )
            except Exception as e:
                logger.error(f"Error fetching market data: {e}")

            # Only fetch private data if authenticated
            if self.is_authenticated:
                # Fetch positions
                try:
                    positions_data = await client.get_positions(currency=self._account_currency)
                    positions = []
                    for pos in positions_data:
                        if pos.get("size", 0) == 0:
                            continue
                        positions.append(
                            LivePosition(
                                instrument=pos.get("instrument_name", ""),
                                size=pos.get("size", 0),
                                direction=pos.get("direction", ""),
                                average_price=pos.get("average_price", 0),
                                mark_price=pos.get("mark_price", 0),
                                pnl=pos.get("floating_profit_loss", 0),
                                delta=pos.get("delta", 0),
                                gamma=pos.get("gamma", 0),
                                theta=pos.get("theta", 0),
                                vega=pos.get("vega", 0),
                            )
                        )
                except DeribitError as e:
                    if e.code == 13009:  # unauthorized - token expired
                        logger.warning("Token expired, clearing authentication")
                        self._access_token = None
                    else:
                        logger.error(f"Error fetching positions: {e}")
                except Exception as e:
                    logger.error(f"Error fetching positions: {e}")

                # Fetch account info
                try:
                    summary = await client.get_account_summary(currency=self._account_currency)
                    equity = summary.get("equity", 0)

                    if self._is_linear:
                        # USDC account: equity is already in USD
                        equity_usd = equity
                    else:
                        # Crypto account: convert to USD using index price
                        index_name = f"{self._currency.lower()}_usd"
                        price = (
                            market_data.btc_price
                            if market_data
                            else await client.get_index_price(index_name)
                        )
                        equity_usd = equity * price

                    account_info = AccountInfo(
                        equity=equity,
                        balance=summary.get("balance", 0),
                        margin_balance=summary.get("margin_balance", 0),
                        initial_margin=summary.get("initial_margin", 0),
                        maintenance_margin=summary.get("maintenance_margin", 0),
                        equity_usd=equity_usd,
                    )
                except DeribitError as e:
                    if e.code == 13009:  # unauthorized - token expired
                        logger.warning("Token expired, clearing authentication")
                        self._access_token = None
                    else:
                        logger.error(f"Error fetching account info: {e}")
                except Exception as e:
                    logger.error(f"Error fetching account info: {e}")

            return market_data, positions, account_info
        finally:
            await client.close()
