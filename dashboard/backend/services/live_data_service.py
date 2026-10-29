"""
Live Data Service

Fetches live data from Deribit API and the bot's database.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from services.config_loader import load_dashboard_config

# Load .env file from project root
project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(project_root / ".env")

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

try:
    from src.data.deribit_client import DeribitClient
    from src.data.volatility import calculate_iv_rank, calculate_realized_volatility
    from src.brain.regime_detector import RegimeDetector
    HAS_BOT_MODULES = True
except ImportError:
    HAS_BOT_MODULES = False
    print("Warning: Bot modules not available, using mock data")


def load_config() -> dict[str, Any]:
    """Load dashboard-selected bot configuration."""
    return load_dashboard_config()


class LiveDataService:
    """Service for fetching live market data."""

    def __init__(self):
        self.client: DeribitClient | None = None
        self.regime_detector: RegimeDetector | None = None
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 3  # seconds (must be shorter than broadcast interval of 5s)
        self._last_update: dict[str, float] = {}
        self._cache_lock = asyncio.Lock()
        self._currency = "BTC"  # Default, will be loaded from config
        self._is_linear = False  # Default, will be loaded from config

    async def start(self):
        """Initialize the service."""
        if HAS_BOT_MODULES:
            try:
                config = load_config()
                deribit_config = config.get("deribit", {})
                trading_config = config.get("trading", {})

                # Load currency and settlement from config
                self._currency = trading_config.get("currency", "BTC").upper()
                self._is_linear = trading_config.get("settlement", "inverse") == "linear"

                base_url = deribit_config.get("base_url", "https://test.deribit.com")
                api_key = deribit_config.get("api_key", "")
                api_secret = deribit_config.get("api_secret", "")

                if not api_key or not api_secret or api_key.startswith("${"):
                    print("Warning: Deribit API credentials not configured")
                    print("Set DERIBIT_TESTNET_API_KEY and DERIBIT_TESTNET_API_SECRET in .env")
                    self.client = None
                    return

                self.client = DeribitClient(
                    base_url=base_url,
                    api_key=api_key,
                    api_secret=api_secret,
                )
                await self.client.authenticate()
                self.regime_detector = RegimeDetector()
                settlement = "linear/USDC" if self._is_linear else "inverse"
                print(f"LiveDataService initialized with Deribit client ({base_url}, currency={self._currency}, settlement={settlement})")
            except Exception as e:
                print(f"Failed to initialize Deribit client: {e}")
                self.client = None
        else:
            print("LiveDataService running in mock mode")

    async def stop(self):
        """Cleanup resources."""
        if self.client:
            await self.client.close()

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still valid."""
        if key not in self._cache or key not in self._last_update:
            return False
        age = datetime.now(timezone.utc).timestamp() - self._last_update[key]
        return age < self._cache_ttl

    def _update_cache(self, key: str, data: Any):
        """Update cache with new data."""
        self._cache[key] = data
        self._last_update[key] = datetime.now(timezone.utc).timestamp()

    async def get_market_data(self) -> dict[str, Any]:
        """Get current market data (lock prevents duplicate API fetches)."""
        async with self._cache_lock:
            if self._is_cache_valid("market"):
                return self._cache["market"]

            if self.client and HAS_BOT_MODULES:
                try:
                    # Fetch live data from Deribit
                    ticker = await self.client.get_ticker(f"{self._currency}-PERPETUAL")
                    dvol = await self.client.get_current_dvol(self._currency)

                    # Use index_price (spot reference) instead of last_price (perpetual trade)
                    # Index price is more accurate, especially on testnet with low liquidity
                    price = ticker.get("index_price", 0)
                    price_change = ticker.get("stats", {}).get("price_change", 0)

                    # Calculate IV metrics
                    iv_rank = await self._calculate_iv_rank()
                    rv = await self._calculate_realized_vol()
                    iv_rv_spread = dvol - rv if dvol and rv else 0

                    # Detect regime
                    regime = "NEUTRAL"
                    if self.regime_detector:
                        from src.data.market_metrics import MarketMetrics
                        metrics = MarketMetrics(
                            timestamp=datetime.now(timezone.utc),
                            btc_price=price,  # Field name kept for compatibility
                            dvol=dvol or 50,
                            iv_rank=iv_rank,
                            rv_30d=rv,
                            iv_rv_spread=iv_rv_spread,
                        )
                        detected = self.regime_detector.detect(metrics)
                        regime = detected.name

                    data = {
                        "price": price,
                        "price_change_24h": price_change,
                        "currency": self._currency,
                        "is_linear": self._is_linear,
                        "dvol": dvol or 50,
                        "iv_rank": iv_rank,
                        "iv_percentile": iv_rank,  # Simplified
                        "realized_vol": rv,
                        "iv_rv_spread": iv_rv_spread,
                        "regime": regime,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                except Exception as e:
                    print(f"Error fetching market data: {e}")
                    data = self._get_mock_market_data()
            else:
                data = self._get_mock_market_data()

            self._update_cache("market", data)
            return data

    async def _calculate_iv_rank(self) -> float:
        """Calculate IV rank using local 252-day historical data.

        Uses the same data source as the paper trader for consistency.
        Falls back to simplified formula if local data unavailable.
        """
        current_dvol = None
        if self.client:
            try:
                current_dvol = await self.client.get_current_dvol(self._currency)
            except Exception:
                pass

        if current_dvol is None:
            return 0.5

        # Try local historical database first (same as paper trader)
        import sqlite3
        # Use resolve() to get absolute path regardless of working directory
        local_db_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "trading.db"

        if local_db_path.exists():
            try:
                with sqlite3.connect(str(local_db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT dvol FROM historical_data WHERE dvol IS NOT NULL "
                        "ORDER BY timestamp DESC LIMIT 252"
                    )
                    historical_dvol = [r[0] for r in cursor.fetchall()]

                if len(historical_dvol) >= 10:
                    return calculate_iv_rank(current_dvol, historical_dvol)
            except Exception as e:
                print(f"Could not load local IV Rank: {e}")

        # Fallback: simplified formula based on typical DVOL range (30-100)
        iv_rank = (current_dvol - 30) / 70
        return max(0, min(1, iv_rank))

    async def _calculate_realized_vol(self) -> float:
        """Calculate 30-day realized volatility from local historical data.

        Uses the same data source as the paper trader for consistency.
        Falls back to 45.0 if local data unavailable.
        """
        import sqlite3
        # Use resolve() to get absolute path regardless of working directory
        local_db_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "trading.db"

        if local_db_path.exists():
            try:
                with sqlite3.connect(str(local_db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT btc_price FROM historical_data WHERE btc_price IS NOT NULL "
                        "ORDER BY timestamp DESC LIMIT 30"
                    )
                    prices = [r[0] for r in cursor.fetchall()]

                if len(prices) >= 2:
                    # Prices are in DESC order, reverse for calculation
                    prices.reverse()
                    rv = calculate_realized_volatility(prices)
                    if rv is not None:
                        return rv
            except Exception as e:
                print(f"Could not calculate RV from local data: {e}")

        # Fallback to typical RV value
        return 45.0

    async def get_account(self) -> dict[str, Any]:
        """Get account information."""
        if self._is_cache_valid("account"):
            return self._cache["account"]

        if self.client:
            try:
                account = await self.client.get_account_summary(self._account_currency)

                # Calculate unrealized P&L from positions (position-based, never resets)
                # This sums floating_profit_loss from all open positions, giving true
                # unrealized P&L since position entry rather than session-based P&L
                positions = await self.get_positions()
                unrealized_pnl = sum(p.get("unrealized_pnl", 0) for p in positions)

                data = {
                    "equity": account.get("equity", 0),
                    "balance": account.get("balance", 0),
                    "margin_balance": account.get("margin_balance", 0),
                    "available_funds": account.get("available_funds", 0),
                    "initial_margin": account.get("initial_margin", 0),
                    "maintenance_margin": account.get("maintenance_margin", 0),
                    "margin_usage_pct": self._calc_margin_usage(account),
                    "unrealized_pnl": unrealized_pnl,
                    "realized_pnl_today": account.get("session_rpl", 0) or 0,
                }
            except Exception as e:
                print(f"Error fetching account: {e}")
                data = self._get_mock_account()
        else:
            data = self._get_mock_account()

        self._update_cache("account", data)
        return data

    def _calc_margin_usage(self, account: dict) -> float:
        """Calculate margin usage percentage."""
        equity = account.get("equity", 1)
        initial_margin = account.get("initial_margin", 0)
        if equity <= 0:
            return 0
        return (initial_margin / equity) * 100

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get open positions from Deribit API.

        Returns actual positions from the exchange. Returns empty list
        if no positions exist or on error (no mock data).
        """
        if self._is_cache_valid("positions"):
            return self._cache["positions"]

        data: list[dict[str, Any]] = []

        if self.client:
            try:
                positions = await self.client.get_positions(self._account_currency)
                print(f"[DEBUG] Fetched {len(positions)} positions from Deribit API for {self._account_currency}")
                for pos in positions:
                    print(f"[DEBUG]   - {pos.get('instrument_name')}: size={pos.get('size')}, direction={pos.get('direction')}")
                data = [
                    {
                        "id": pos.get("instrument_name", ""),
                        "instrument_name": pos.get("instrument_name", ""),
                        "direction": "long" if pos.get("direction") == "buy" else "short",
                        "size": abs(pos.get("size", 0)),
                        "average_price": pos.get("average_price", 0),
                        "mark_price": pos.get("mark_price", 0),
                        "unrealized_pnl": pos.get("floating_profit_loss", 0),
                        "realized_pnl": pos.get("realized_profit_loss", 0),
                        "delta": pos.get("delta", 0),
                        "gamma": pos.get("gamma", 0),
                        "theta": pos.get("theta", 0),
                        "vega": pos.get("vega", 0),
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                    }
                    for pos in positions
                    if pos.get("size", 0) != 0
                ]
            except Exception as e:
                print(f"Error fetching positions: {e}")
                # Return empty list on error, not mock data

        self._update_cache("positions", data)
        return data

    async def get_portfolio_greeks(self) -> dict[str, float]:
        """Get aggregated portfolio Greeks."""
        positions = await self.get_positions()

        delta = sum(p.get("delta", 0) for p in positions)
        gamma = sum(p.get("gamma", 0) for p in positions)
        theta = sum(p.get("theta", 0) for p in positions)
        vega = sum(p.get("vega", 0) for p in positions)

        return {
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
        }

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
        """Currency for account/position API calls.

        Linear (USDC) options use 'USDC' for account queries.
        """
        return "USDC" if self._is_linear else self._currency

    # Mock data methods for development/testing
    def _get_mock_market_data(self) -> dict[str, Any]:
        import random
        mock_price = 3200 if self._currency == "ETH" else 97500
        return {
            "price": mock_price + random.uniform(-50, 50),
            "price_change_24h": random.uniform(-3, 3),
            "currency": self._currency,
            "is_linear": self._is_linear,
            "dvol": 52 + random.uniform(-5, 5),
            "iv_rank": 0.45 + random.uniform(-0.1, 0.1),
            "iv_percentile": 0.48,
            "realized_vol": 48,
            "iv_rv_spread": 4.2,
            "regime": "NEUTRAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _get_mock_account(self) -> dict[str, Any]:
        if self._is_linear:
            return {
                "equity": 5023.45,
                "balance": 5000.00,
                "margin_balance": 4800.00,
                "available_funds": 4250.00,
                "initial_margin": 723.45,
                "maintenance_margin": 485.00,
                "margin_usage_pct": 14.4,
                "unrealized_pnl": 23.45,
                "realized_pnl_today": 15.00,
            }
        return {
            "equity": 1.5234,
            "balance": 1.5000,
            "margin_balance": 1.4800,
            "available_funds": 1.2500,
            "initial_margin": 0.2234,
            "maintenance_margin": 0.1500,
            "margin_usage_pct": 14.7,
            "unrealized_pnl": 0.0234,
            "realized_pnl_today": 0.0150,
        }

    def _get_mock_positions(self) -> list[dict[str, Any]]:
        if self._is_linear:
            return [
                {
                    "id": "ETH_USDC-27FEB26-2100-P",
                    "instrument_name": "ETH_USDC-27FEB26-2100-P",
                    "direction": "short",
                    "size": 0.5,
                    "average_price": 125.00,
                    "mark_price": 118.00,
                    "unrealized_pnl": 35.00,
                    "realized_pnl": 0,
                    "delta": -0.25,
                    "gamma": 0.00012,
                    "theta": 4.55,
                    "vega": 2.83,
                    "strategy_type": "WHEEL",
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
        return [
            {
                "id": "BTC-31JAN25-95000-P",
                "instrument_name": "BTC-31JAN25-95000-P",
                "direction": "short",
                "size": 0.5,
                "average_price": 1250.0,
                "mark_price": 1180.0,
                "unrealized_pnl": 35.0,
                "realized_pnl": 0,
                "delta": -0.25,
                "gamma": 0.00012,
                "theta": 45.5,
                "vega": 28.3,
                "strategy_type": "WHEEL",
                "opened_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "BTC-31JAN25-105000-C",
                "instrument_name": "BTC-31JAN25-105000-C",
                "direction": "short",
                "size": 0.3,
                "average_price": 980.0,
                "mark_price": 920.0,
                "unrealized_pnl": 18.0,
                "realized_pnl": 0,
                "delta": 0.18,
                "gamma": 0.00008,
                "theta": 32.1,
                "vega": 21.5,
                "strategy_type": "WHEEL",
                "opened_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
