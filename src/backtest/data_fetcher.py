"""Historical data fetcher for backtesting."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from src.data.deribit_client import DeribitClient


@dataclass
class HistoricalBar:
    """Single OHLCV bar.

    Attributes:
        timestamp: Bar timestamp (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Trading volume.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class HistoricalDataFetcher:
    """Fetches historical data from Deribit for backtesting."""

    def __init__(self, client: DeribitClient) -> None:
        """Initialize fetcher.

        Args:
            client: Deribit API client.
        """
        self.client = client

    async def fetch_price_history(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        resolution: str = "1D",
    ) -> list[HistoricalBar]:
        """Fetch historical price bars.

        Args:
            instrument: Instrument name (e.g., BTC-PERPETUAL).
            start: Start datetime (UTC).
            end: End datetime (UTC).
            resolution: Candle resolution (1D, 1, 60, etc).

        Returns:
            List of HistoricalBar objects.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        data = await self.client.get_tradingview_chart_data(
            instrument_name=instrument,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms,
        )

        return self._parse_ohlcv(data)

    async def fetch_dvol_history(
        self,
        start: datetime,
        end: datetime,
        currency: str = "BTC",
        resolution: int = 86400,  # Daily
    ) -> list[HistoricalBar]:
        """Fetch historical DVOL data.

        Args:
            start: Start datetime (UTC).
            end: End datetime (UTC).
            currency: Currency (BTC, ETH).
            resolution: Resolution in seconds (default 1 day).

        Returns:
            List of HistoricalBar objects with DVOL as close.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        data = await self.client.get_volatility_index(
            currency=currency,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms,
        )

        bars: list[HistoricalBar] = []
        for row in data:
            # Row: [timestamp_ms, open, high, low, close]
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            bars.append(HistoricalBar(
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=0.0,
            ))

        return bars

    def _parse_ohlcv(self, data: dict[str, Any]) -> list[HistoricalBar]:
        """Parse TradingView chart data response.

        Args:
            data: Response from get_tradingview_chart_data.

        Returns:
            List of HistoricalBar objects.
        """
        bars: list[HistoricalBar] = []

        ticks = data.get("ticks", [])
        opens = data.get("open", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        closes = data.get("close", [])
        volumes = data.get("volume", [])

        # Find minimum length to avoid IndexError on misaligned arrays
        min_len = min(len(ticks), len(opens), len(highs), len(lows), len(closes))

        for i in range(min_len):
            ts = datetime.fromtimestamp(ticks[i] / 1000, tz=timezone.utc)
            bars.append(HistoricalBar(
                timestamp=ts,
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i] if i < len(volumes) else 0.0,
            ))

        return bars

    @staticmethod
    def calculate_iv_rank(
        dvol_bars: list[HistoricalBar],
        lookback: int = 252,
    ) -> dict[datetime, float]:
        """Calculate IV rank for each bar based on lookback period.

        IV rank = (current - min) / (max - min) over lookback period.

        Args:
            dvol_bars: Historical DVOL bars (must be sorted by timestamp).
            lookback: Number of bars for lookback period (default 252 = 1 year daily).

        Returns:
            Dict mapping timestamp to IV rank (0.0 to 1.0).
        """
        iv_ranks: dict[datetime, float] = {}

        if len(dvol_bars) < 2:
            return iv_ranks

        for i in range(len(dvol_bars)):
            # Get lookback window excluding current bar (avoid look-ahead)
            start_idx = max(0, i - lookback)
            window = dvol_bars[start_idx:i]  # Exclude current bar

            if len(window) < 2:
                continue

            dvol_values = [bar.close for bar in window]
            min_dvol = min(dvol_values)
            max_dvol = max(dvol_values)

            if (max_dvol - min_dvol) < 1e-6:
                iv_rank = 0.5  # Flat period
            else:
                current_dvol = dvol_bars[i].open
                iv_rank = (current_dvol - min_dvol) / (max_dvol - min_dvol)

            iv_ranks[dvol_bars[i].timestamp] = iv_rank

        return iv_ranks

    @staticmethod
    def calculate_realized_vol(
        price_bars: list[HistoricalBar],
        lookback: int = 30,
        annualization_factor: float = 365.0,
    ) -> dict[datetime, float]:
        """Calculate realized volatility for each bar.

        RV = std(log returns) * sqrt(annualization_factor) * 100

        Args:
            price_bars: Historical price bars (must be sorted by timestamp).
            lookback: Number of bars for lookback period (default 30 days).
            annualization_factor: Days per year for annualization (default 365 for crypto).

        Returns:
            Dict mapping timestamp to realized volatility (as percentage, e.g., 45.0 = 45%).
        """
        rv_values: dict[datetime, float] = {}

        if len(price_bars) < 2:
            return rv_values

        # Use open prices to avoid look-ahead bias (engine decisions happen at bar open)
        opens = np.array([bar.open for bar in price_bars])
        log_returns = np.diff(np.log(opens))

        for i in range(1, len(price_bars)):
            # Get lookback window for returns (returns are offset by 1)
            return_idx = i - 1  # Index into log_returns
            start_idx = max(0, return_idx - lookback + 1)
            window = log_returns[start_idx:return_idx + 1]

            if len(window) < 2:
                continue

            # Annualized volatility as percentage
            rv = float(np.std(window) * np.sqrt(annualization_factor) * 100)
            rv_values[price_bars[i].timestamp] = rv

        return rv_values
