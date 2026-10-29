"""Market analyzer service for aggregating metrics and detecting regime."""

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data.deribit_client import DeribitClient
from src.data.market_metrics import MarketMetrics
from src.data.volatility import (
    calculate_realized_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
)
from src.brain.regime_detector import (
    MarketRegime,
    RegimeDetector,
)

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """Aggregates market data and calculates volatility metrics.

    Fetches data from Deribit, calculates derived metrics (IV Rank, RV, etc.),
    and detects the current market regime.
    """

    def __init__(
        self,
        client: DeribitClient,
        detector: RegimeDetector | None = None,
        currency: str = "BTC",
    ) -> None:
        """Initialize market analyzer.

        Args:
            client: Deribit API client.
            detector: Regime detector (uses default if not provided).
            currency: Trading currency (BTC or ETH).
        """
        self.client = client
        self.detector = detector or RegimeDetector()
        self.currency = currency.upper()

    async def get_current_metrics(self) -> MarketMetrics:
        """Fetch current market data and calculate metrics.

        Returns:
            MarketMetrics with current values.
        """
        # Fetch current data
        index_name = f"{self.currency.lower()}_usd"
        price = await self.client.get_index_price(index_name)
        current_dvol = await self.client.get_current_dvol(self.currency)

        # Fetch historical DVOL for IV Rank (52 weeks)
        historical_dvol = await self._fetch_historical_dvol()
        # Enforce 252-day lookback for IV rank (documented in volatility.py)
        if len(historical_dvol) > 252:
            historical_dvol = historical_dvol[-252:]

        # Fetch historical prices for RV calculation
        historical_prices = await self._fetch_historical_prices(days=30)

        # Calculate metrics
        iv_rank = calculate_iv_rank(current_dvol, historical_dvol)
        iv_percentile = calculate_iv_percentile(current_dvol, historical_dvol)
        rv_30d = calculate_realized_volatility(historical_prices)

        # Calculate 7-day RV from last 7 prices
        rv_7d = None
        if len(historical_prices) >= 7:
            rv_7d = calculate_realized_volatility(historical_prices[-7:])
            if rv_7d is None:
                logger.warning("RV 7d calculation returned None (bad price data in last 7 days)")

        # Calculate IV-RV spread
        iv_rv_spread = None
        if rv_30d is not None:
            iv_rv_spread = current_dvol - rv_30d

        return MarketMetrics(
            btc_price=price,  # Field name kept for backwards compatibility
            dvol=current_dvol,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            rv_7d=rv_7d,
            rv_30d=rv_30d,
            iv_rv_spread=iv_rv_spread,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_current_regime(self) -> MarketRegime:
        """Get current market regime.

        Returns:
            Current market regime.
        """
        metrics = await self.get_current_metrics()
        return self.detector.detect(metrics)

    async def analyze(self) -> dict[str, Any]:
        """Perform full market analysis.

        Returns:
            Dict with metrics, regime, and recommendation.
        """
        metrics = await self.get_current_metrics()
        regime = self.detector.detect(metrics)
        recommendation = self.detector.get_recommendation(regime)

        return {
            "metrics": metrics,
            "regime": regime,
            "recommendation": recommendation,
        }

    async def _fetch_historical_dvol(self) -> list[float]:
        """Fetch 365 days of historical DVOL data for IV rank calculation.

        Uses 365-day window to provide sufficient data for 252-day IV rank lookback
        (252 trading days ~ 365 calendar days).

        Returns:
            List of DVOL values (oldest first), max 365 entries.
        """
        # Constrain to 365 days to avoid unbounded API fetch
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (365 * 86400 * 1000)

        # Fetch DVOL data - returns [[timestamp, open, high, low, close], ...]
        dvol_data = await self.client.get_volatility_index(
            currency=self.currency,
            resolution=86400,  # Daily
            start_timestamp=start_ms,
            end_timestamp=end_ms,
        )

        # Extract close values (index 4 for OHLC, index 1 for 2-element format)
        return [candle[4] if len(candle) > 4 else candle[1] for candle in dvol_data]

    async def _fetch_historical_prices(self, days: int = 30) -> list[float]:
        """Fetch historical prices for the trading currency.

        Tries Deribit API first, falls back to local historical data if
        API returns insufficient data (common on testnet).

        Args:
            days: Number of days of history.

        Returns:
            List of close prices (oldest first).
        """
        # Try Deribit API first
        instrument = f"{self.currency}-PERPETUAL"
        data = await self.client.get_tradingview_chart_data(
            instrument_name=instrument,
            resolution="1D",
        )

        close_prices: list[float] = data.get("close", [])

        # If API returned sufficient data, use it
        if len(close_prices) >= days:
            return list(close_prices[-days:])

        # Fall back to local historical data (e.g., on testnet with limited data)
        local_prices = self._fetch_local_historical_prices(days)
        if local_prices:
            return local_prices

        # Return whatever the API gave us
        return list(close_prices)

    def _fetch_local_historical_prices(self, days: int = 30) -> list[float]:
        """Fetch historical prices from local database.

        Used as fallback when Deribit API returns insufficient data.

        Args:
            days: Number of days of history.

        Returns:
            List of close prices (oldest first), or empty list if unavailable.
        """
        # Look for trading.db in data/ directory
        local_db_path = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"

        if not local_db_path.exists():
            return []

        try:
            with sqlite3.connect(str(local_db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT btc_price FROM historical_data WHERE btc_price IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (days,),
                )
                prices = [r[0] for r in cursor.fetchall()]

            if len(prices) >= 2:
                # Prices are in DESC order, reverse for calculation (oldest first)
                prices.reverse()
                return prices
        except OSError as e:
            logger.debug(f"Could not load local prices: {e}")
        except sqlite3.Error as e:
            logger.warning(f"DB error loading local prices: {e}")

        return []
