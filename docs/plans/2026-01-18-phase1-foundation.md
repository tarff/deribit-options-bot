# Phase 1: Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the foundational infrastructure for the crypto options trading bot - project scaffolding, Deribit API client, and SQLite database.

**Architecture:** Python async architecture using `aiohttp` for REST/WebSocket communication with Deribit. SQLite for persistence with repository pattern. Configuration via YAML files. All components designed for testability with dependency injection.

**Tech Stack:** Python 3.11+, aiohttp, SQLite, pydantic, pytest, pytest-asyncio, PyYAML

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `src/__init__.py`
- Create: `src/main.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "crypto-options-bot"
version = "0.1.0"
description = "Autonomous BTC options trading bot for Deribit"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "aiohttp>=3.9.0",
    "pydantic>=2.5.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-v --tb=short"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

**Step 2: Create requirements.txt**

```
aiohttp>=3.9.0
pydantic>=2.5.0
pyyaml>=6.0
python-dotenv>=1.0.0
```

**Step 3: Create requirements-dev.txt**

```
-r requirements.txt
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
ruff>=0.1.0
mypy>=1.7.0
aioresponses>=0.7.6
```

**Step 4: Create directory structure**

```bash
mkdir -p src/data src/brain src/strategies src/execution src/risk src/persistence src/monitoring
mkdir -p tests/unit tests/integration
mkdir -p config
```

**Step 5: Create src/__init__.py**

```python
"""Crypto Options Trading Bot."""
```

**Step 6: Create src/main.py**

```python
"""Entry point for the crypto options trading bot."""

import asyncio


async def main() -> None:
    """Main entry point."""
    print("Crypto Options Bot starting...")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 7: Create tests/__init__.py**

```python
"""Test suite for crypto options bot."""
```

**Step 8: Create tests/conftest.py**

```python
"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def sample_btc_price() -> float:
    """Sample BTC price for testing."""
    return 97432.50
```

**Step 9: Create virtual environment and install dependencies**

Run:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
```

**Step 10: Verify setup by running pytest**

Run: `pytest --collect-only`
Expected: "no tests ran" (no tests yet, but pytest works)

**Step 11: Commit**

```bash
git add pyproject.toml requirements.txt requirements-dev.txt src/ tests/ config/
git commit -m "feat: add project scaffolding with Python packaging"
```

---

## Task 2: Configuration System

**Files:**
- Create: `src/config.py`
- Create: `config/settings.yaml`
- Create: `config/settings.example.yaml`
- Create: `tests/unit/test_config.py`

**Step 1: Write the failing test for config loading**

Create `tests/unit/__init__.py`:
```python
"""Unit tests."""
```

Create `tests/unit/test_config.py`:
```python
"""Tests for configuration loading."""

import pytest
from pathlib import Path

from src.config import Settings, load_settings


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    """Test loading settings from YAML file."""
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("""
deribit:
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"

risk:
  max_position_pct: 10.0
  max_exposure_pct: 30.0
  max_daily_loss_pct: 5.0
  max_drawdown_pct: 15.0

database:
  path: "data/bot.db"
""")

    settings = load_settings(config_file)

    assert settings.deribit.base_url == "https://test.deribit.com"
    assert settings.risk.max_position_pct == 10.0
    assert settings.database.path == "data/bot.db"


def test_settings_validation_rejects_invalid_risk() -> None:
    """Test that invalid risk parameters are rejected."""
    with pytest.raises(ValueError):
        Settings(
            deribit={"base_url": "https://test.deribit.com", "ws_url": "wss://test.deribit.com/ws/api/v2"},
            risk={"max_position_pct": 150.0},  # Invalid: > 100%
            database={"path": "test.db"},
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.config'"

**Step 3: Write minimal implementation**

Create `src/config.py`:
```python
"""Configuration management for the trading bot."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class DeribitConfig(BaseModel):
    """Deribit API configuration."""

    base_url: str = "https://www.deribit.com"
    ws_url: str = "wss://www.deribit.com/ws/api/v2"
    api_key: str = ""
    api_secret: str = ""


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_position_pct: float = Field(default=10.0, ge=0, le=100)
    max_exposure_pct: float = Field(default=30.0, ge=0, le=100)
    max_daily_loss_pct: float = Field(default=5.0, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15.0, ge=0, le=100)
    dvol_reduce_threshold: float = Field(default=60.0)
    dvol_halt_threshold: float = Field(default=80.0)

    @field_validator("max_position_pct", "max_exposure_pct", "max_daily_loss_pct", "max_drawdown_pct")
    @classmethod
    def validate_percentage(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError(f"Percentage must be between 0 and 100, got {v}")
        return v


class DatabaseConfig(BaseModel):
    """Database configuration."""

    path: str = "data/bot.db"


class Settings(BaseModel):
    """Application settings."""

    deribit: DeribitConfig = Field(default_factory=DeribitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file.

    Args:
        config_path: Path to YAML config file. Defaults to config/settings.yaml.

    Returns:
        Loaded Settings object.
    """
    if config_path is None:
        config_path = Path("config/settings.yaml")

    if not config_path.exists():
        return Settings()

    with open(config_path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return Settings(**data)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS (2 tests)

**Step 5: Create example config file**

Create `config/settings.example.yaml`:
```yaml
# Crypto Options Bot Configuration
# Copy this to settings.yaml and fill in your values

deribit:
  # Use test.deribit.com for paper trading
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"
  api_key: "YOUR_API_KEY"
  api_secret: "YOUR_API_SECRET"

risk:
  max_position_pct: 10.0      # Max 10% of capital per position
  max_exposure_pct: 30.0      # Max 30% total exposure
  max_daily_loss_pct: 5.0     # Halt if daily loss exceeds 5%
  max_drawdown_pct: 15.0      # Halt if drawdown exceeds 15%
  dvol_reduce_threshold: 60.0 # Reduce position sizes when DVOL > 60
  dvol_halt_threshold: 80.0   # Halt new trades when DVOL > 80

database:
  path: "data/bot.db"
```

**Step 6: Add config/ to .gitignore (protect secrets)**

Append to `.gitignore`:
```
# Config with secrets
config/settings.yaml
!config/settings.example.yaml
```

**Step 7: Commit**

```bash
git add src/config.py tests/unit/ config/settings.example.yaml .gitignore
git commit -m "feat: add configuration system with pydantic validation"
```

---

## Task 3: Database Schema and Connection

**Files:**
- Create: `src/persistence/__init__.py`
- Create: `src/persistence/database.py`
- Create: `src/persistence/models.py`
- Create: `tests/unit/test_database.py`

**Step 1: Write the failing test for database initialization**

Create `src/persistence/__init__.py`:
```python
"""Persistence layer for the trading bot."""
```

Create `tests/unit/test_database.py`:
```python
"""Tests for database operations."""

import pytest
from pathlib import Path

from src.persistence.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    return Database(str(db_path))


def test_database_creates_tables(db: Database) -> None:
    """Test that database creates all required tables."""
    db.initialize()

    # Check tables exist
    tables = db.get_tables()
    assert "trades" in tables
    assert "positions" in tables
    assert "market_snapshots" in tables
    assert "daily_performance" in tables
    assert "risk_events" in tables


def test_database_is_idempotent(db: Database) -> None:
    """Test that initializing twice doesn't fail."""
    db.initialize()
    db.initialize()  # Should not raise

    tables = db.get_tables()
    assert len(tables) == 5
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_database.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.persistence.database'"

**Step 3: Write minimal implementation**

Create `src/persistence/database.py`:
```python
"""SQLite database management."""

import sqlite3
from pathlib import Path


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            # Ensure parent directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def initialize(self) -> None:
        """Create database tables if they don't exist."""
        cursor = self.connection.cursor()

        # Trades table - individual orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                strategy_type TEXT NOT NULL,
                order_id TEXT UNIQUE,
                instrument TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fees REAL DEFAULT 0,
                status TEXT NOT NULL,
                opened_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP,
                pnl REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Positions table - strategy instances
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY,
                strategy_id TEXT UNIQUE NOT NULL,
                strategy_type TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT,
                entry_price REAL,
                max_profit REAL,
                max_loss REAL,
                current_pnl REAL,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                opened_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP,
                close_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Market snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY,
                btc_price REAL NOT NULL,
                dvol REAL,
                iv_rank REAL,
                iv_percentile REAL,
                rv_7d REAL,
                rv_30d REAL,
                iv_rv_spread REAL,
                term_structure_ratio REAL,
                rr_skew REAL,
                regime TEXT,
                active_strategy TEXT,
                timestamp TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Daily performance table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_performance (
                id INTEGER PRIMARY KEY,
                date DATE UNIQUE NOT NULL,
                starting_capital REAL,
                ending_capital REAL,
                pnl REAL,
                pnl_percent REAL,
                max_drawdown REAL,
                trades_opened INTEGER,
                trades_closed INTEGER,
                fees_paid REAL,
                pnl_wheel REAL DEFAULT 0,
                pnl_iron_condor REAL DEFAULT 0,
                pnl_vol_arb REAL DEFAULT 0,
                pnl_gamma_scalp REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Risk events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT,
                action_taken TEXT,
                timestamp TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON market_snapshots(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_performance(date)")

        self.connection.commit()

    def get_tables(self) -> list[str]:
        """Get list of tables in database."""
        cursor = self.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [row[0] for row in cursor.fetchall()]

    def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_database.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/persistence/ tests/unit/test_database.py
git commit -m "feat: add SQLite database with schema for trades, positions, snapshots"
```

---

## Task 4: Data Models (Pydantic)

**Files:**
- Create: `src/persistence/models.py`
- Create: `tests/unit/test_models.py`

**Step 1: Write the failing test for data models**

Create `tests/unit/test_models.py`:
```python
"""Tests for data models."""

import pytest
from datetime import datetime, timezone

from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus


def test_trade_creation() -> None:
    """Test creating a trade model."""
    trade = Trade(
        strategy_id="WHL-001",
        strategy_type="wheel",
        order_id="ORD-123",
        instrument="BTC-28MAR25-100000-P",
        side="sell",
        quantity=0.1,
        price=1500.0,
        status=TradeStatus.FILLED,
        opened_at=datetime.now(timezone.utc),
    )

    assert trade.strategy_id == "WHL-001"
    assert trade.status == TradeStatus.FILLED
    assert trade.pnl is None  # Not set yet


def test_position_with_greeks() -> None:
    """Test position model with Greeks."""
    position = Position(
        strategy_id="IC-001",
        strategy_type="iron_condor",
        status=PositionStatus.OPEN,
        phase="active",
        entry_price=97000.0,
        max_profit=500.0,
        max_loss=2000.0,
        delta=-0.03,
        gamma=0.002,
        theta=47.0,
        vega=-15.0,
        opened_at=datetime.now(timezone.utc),
    )

    assert position.delta == -0.03
    assert position.theta == 47.0


def test_market_snapshot() -> None:
    """Test market snapshot model."""
    snapshot = MarketSnapshot(
        btc_price=97432.50,
        dvol=52.3,
        iv_rank=0.67,
        rv_7d=48.2,
        rv_30d=45.1,
        iv_rv_spread=4.1,
        term_structure_ratio=1.05,
        rr_skew=-2.1,
        regime="high_iv",
        timestamp=datetime.now(timezone.utc),
    )

    assert snapshot.btc_price == 97432.50
    assert snapshot.regime == "high_iv"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.persistence.models'"

**Step 3: Write minimal implementation**

Create `src/persistence/models.py`:
```python
"""Data models for the trading bot."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradeStatus(str, Enum):
    """Status of a trade."""

    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionStatus(str, Enum):
    """Status of a position/strategy instance."""

    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"


class TradeSide(str, Enum):
    """Side of a trade."""

    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    """Individual trade/order."""

    id: Optional[int] = None
    strategy_id: str
    strategy_type: str
    order_id: Optional[str] = None
    instrument: str
    side: str
    quantity: float = Field(gt=0)
    price: float = Field(ge=0)
    fees: float = Field(default=0, ge=0)
    status: TradeStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None
    pnl: Optional[float] = None


class Position(BaseModel):
    """Strategy instance/position."""

    id: Optional[int] = None
    strategy_id: str
    strategy_type: str
    status: PositionStatus
    phase: Optional[str] = None
    entry_price: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    current_pnl: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None


class MarketSnapshot(BaseModel):
    """Point-in-time market data snapshot."""

    id: Optional[int] = None
    btc_price: float = Field(gt=0)
    dvol: Optional[float] = None
    iv_rank: Optional[float] = Field(default=None, ge=0, le=1)
    iv_percentile: Optional[float] = Field(default=None, ge=0, le=1)
    rv_7d: Optional[float] = None
    rv_30d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    term_structure_ratio: Optional[float] = None
    rr_skew: Optional[float] = None
    regime: Optional[str] = None
    active_strategy: Optional[str] = None
    timestamp: datetime


class DailyPerformance(BaseModel):
    """Daily P&L and metrics."""

    id: Optional[int] = None
    date: datetime
    starting_capital: Optional[float] = None
    ending_capital: Optional[float] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    max_drawdown: Optional[float] = None
    trades_opened: int = 0
    trades_closed: int = 0
    fees_paid: float = 0
    pnl_wheel: float = 0
    pnl_iron_condor: float = 0
    pnl_vol_arb: float = 0
    pnl_gamma_scalp: float = 0


class RiskEvent(BaseModel):
    """Risk event or circuit breaker trigger."""

    id: Optional[int] = None
    event_type: str
    severity: str  # info, warning, critical
    message: Optional[str] = None
    action_taken: Optional[str] = None
    timestamp: datetime
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/persistence/models.py tests/unit/test_models.py
git commit -m "feat: add pydantic data models for trades, positions, snapshots"
```

---

## Task 5: Deribit REST Client (Authentication)

**Files:**
- Create: `src/data/__init__.py`
- Create: `src/data/deribit_client.py`
- Create: `tests/unit/test_deribit_client.py`

**Step 1: Write the failing test for authentication**

Create `src/data/__init__.py`:
```python
"""Data layer for market data and exchange connectivity."""
```

Create `tests/unit/test_deribit_client.py`:
```python
"""Tests for Deribit API client."""

import pytest
from unittest.mock import AsyncMock, patch
from aioresponses import aioresponses

from src.data.deribit_client import DeribitClient


@pytest.fixture
def client() -> DeribitClient:
    """Create test client."""
    return DeribitClient(
        base_url="https://test.deribit.com",
        api_key="test_key",
        api_secret="test_secret",
    )


@pytest.mark.asyncio
async def test_authenticate_success(client: DeribitClient) -> None:
    """Test successful authentication."""
    with aioresponses() as mocked:
        mocked.get(
            "https://test.deribit.com/api/v2/public/auth",
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_deribit_client.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.deribit_client'"

**Step 3: Write minimal implementation**

Create `src/data/deribit_client.py`:
```python
"""Deribit REST API client."""

import hashlib
import hmac
import time
from typing import Any

import aiohttp


class DeribitError(Exception):
    """Deribit API error."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Deribit error {code}: {message}")


class DeribitClient:
    """Async client for Deribit REST API."""

    def __init__(
        self,
        base_url: str = "https://www.deribit.com",
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        """Initialize Deribit client.

        Args:
            base_url: Deribit API base URL.
            api_key: API key for authentication.
            api_secret: API secret for authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self.access_token is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        private: bool = False,
    ) -> Any:
        """Make API request.

        Args:
            method: HTTP method (GET, POST).
            endpoint: API endpoint path.
            params: Query parameters.
            private: Whether this is a private endpoint requiring auth.

        Returns:
            Response result.

        Raises:
            DeribitError: If API returns an error.
        """
        session = await self._get_session()
        url = f"{self.base_url}/api/v2{endpoint}"

        headers = {}
        if private and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        async with session.request(method, url, params=params, headers=headers) as response:
            data = await response.json()

            if "error" in data:
                error = data["error"]
                raise DeribitError(error.get("code", -1), error.get("message", "Unknown error"))

            return data.get("result")

    async def authenticate(self) -> None:
        """Authenticate with Deribit API.

        Uses client credentials grant type.
        """
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret,
        }

        result = await self._request("GET", "/public/auth", params)

        self.access_token = result["access_token"]
        self.refresh_token = result.get("refresh_token")

    async def get_index_price(self, index_name: str = "btc_usd") -> float:
        """Get current index price.

        Args:
            index_name: Index name (btc_usd, eth_usd).

        Returns:
            Current index price.
        """
        result = await self._request("GET", "/public/get_index_price", {"index_name": index_name})
        return result["index_price"]

    async def get_instruments(
        self,
        currency: str = "BTC",
        kind: str = "option",
        expired: bool = False,
    ) -> list[dict[str, Any]]:
        """Get available instruments.

        Args:
            currency: Currency (BTC, ETH).
            kind: Instrument kind (option, future).
            expired: Include expired instruments.

        Returns:
            List of instruments.
        """
        params = {
            "currency": currency,
            "kind": kind,
            "expired": str(expired).lower(),
        }
        return await self._request("GET", "/public/get_instruments", params)

    async def get_order_book(
        self,
        instrument_name: str,
        depth: int = 10,
    ) -> dict[str, Any]:
        """Get order book for instrument.

        Args:
            instrument_name: Instrument name.
            depth: Order book depth.

        Returns:
            Order book data with bids/asks.
        """
        params = {
            "instrument_name": instrument_name,
            "depth": depth,
        }
        return await self._request("GET", "/public/get_order_book", params)

    async def get_ticker(self, instrument_name: str) -> dict[str, Any]:
        """Get ticker data for instrument.

        Args:
            instrument_name: Instrument name.

        Returns:
            Ticker data including mark price, greeks, IV.
        """
        params = {"instrument_name": instrument_name}
        return await self._request("GET", "/public/ticker", params)

    async def get_book_summary_by_currency(
        self,
        currency: str = "BTC",
        kind: str = "option",
    ) -> list[dict[str, Any]]:
        """Get book summary for all instruments of a currency.

        Args:
            currency: Currency (BTC, ETH).
            kind: Instrument kind (option, future).

        Returns:
            List of book summaries.
        """
        params = {"currency": currency, "kind": kind}
        return await self._request("GET", "/public/get_book_summary_by_currency", params)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_deribit_client.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/data/ tests/unit/test_deribit_client.py
git commit -m "feat: add Deribit REST client with authentication and public endpoints"
```

---

## Task 6: Deribit REST Client (Private Endpoints)

**Files:**
- Modify: `src/data/deribit_client.py`
- Modify: `tests/unit/test_deribit_client.py`

**Step 1: Write the failing test for private endpoints**

Add to `tests/unit/test_deribit_client.py`:
```python
@pytest.mark.asyncio
async def test_get_account_summary(client: DeribitClient) -> None:
    """Test fetching account summary (private endpoint)."""
    with aioresponses() as mocked:
        # First authenticate
        mocked.get(
            "https://test.deribit.com/api/v2/public/auth",
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
            "https://test.deribit.com/api/v2/public/auth",
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_deribit_client.py::test_get_account_summary -v`
Expected: FAIL with "AttributeError: 'DeribitClient' object has no attribute 'get_account_summary'"

**Step 3: Add private endpoint methods to DeribitClient**

Add to `src/data/deribit_client.py` (inside the class):
```python
    async def get_account_summary(self, currency: str = "BTC") -> dict[str, Any]:
        """Get account summary.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Account summary with equity, balance, margin info.
        """
        params = {"currency": currency}
        return await self._request("GET", "/private/get_account_summary", params, private=True)

    async def get_positions(
        self,
        currency: str = "BTC",
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get open positions.

        Args:
            currency: Currency (BTC, ETH).
            kind: Filter by instrument kind (option, future).

        Returns:
            List of open positions with Greeks.
        """
        params: dict[str, Any] = {"currency": currency}
        if kind:
            params["kind"] = kind
        return await self._request("GET", "/private/get_positions", params, private=True)

    async def buy(
        self,
        instrument_name: str,
        amount: float,
        price: float | None = None,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """Place a buy order.

        Args:
            instrument_name: Instrument to buy.
            amount: Amount in contracts.
            price: Limit price (required for limit orders).
            order_type: Order type (limit, market).

        Returns:
            Order result.
        """
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type,
        }
        if price is not None:
            params["price"] = price
        return await self._request("GET", "/private/buy", params, private=True)

    async def sell(
        self,
        instrument_name: str,
        amount: float,
        price: float | None = None,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """Place a sell order.

        Args:
            instrument_name: Instrument to sell.
            amount: Amount in contracts.
            price: Limit price (required for limit orders).
            order_type: Order type (limit, market).

        Returns:
            Order result.
        """
        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": order_type,
        }
        if price is not None:
            params["price"] = price
        return await self._request("GET", "/private/sell", params, private=True)

    async def cancel(self, order_id: str) -> dict[str, Any]:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            Cancellation result.
        """
        params = {"order_id": order_id}
        return await self._request("GET", "/private/cancel", params, private=True)

    async def get_open_orders(
        self,
        currency: str = "BTC",
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get open orders.

        Args:
            currency: Currency (BTC, ETH).
            kind: Filter by instrument kind.

        Returns:
            List of open orders.
        """
        params: dict[str, Any] = {"currency": currency}
        if kind:
            params["kind"] = kind
        return await self._request("GET", "/private/get_open_orders_by_currency", params, private=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_deribit_client.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/data/deribit_client.py tests/unit/test_deribit_client.py
git commit -m "feat: add Deribit private endpoints for trading and positions"
```

---

## Task 7: DVOL Index Fetching

**Files:**
- Modify: `src/data/deribit_client.py`
- Modify: `tests/unit/test_deribit_client.py`

**Step 1: Write the failing test for DVOL**

Add to `tests/unit/test_deribit_client.py`:
```python
@pytest.mark.asyncio
async def test_get_volatility_index(client: DeribitClient) -> None:
    """Test fetching DVOL index."""
    with aioresponses() as mocked:
        mocked.get(
            "https://test.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=3600&start_timestamp=0&end_timestamp=9999999999999",
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_deribit_client.py::test_get_volatility_index -v`
Expected: FAIL with "AttributeError: 'DeribitClient' object has no attribute 'get_volatility_index'"

**Step 3: Add DVOL methods to DeribitClient**

Add to `src/data/deribit_client.py`:
```python
    async def get_volatility_index(
        self,
        currency: str = "BTC",
        resolution: int = 3600,
        start_timestamp: int = 0,
        end_timestamp: int = 9999999999999,
    ) -> list[list[float]]:
        """Get historical volatility index (DVOL) data.

        Args:
            currency: Currency (BTC, ETH).
            resolution: Candle resolution in seconds.
            start_timestamp: Start time in milliseconds.
            end_timestamp: End time in milliseconds.

        Returns:
            List of OHLC data [timestamp, open, high, low, close].
        """
        params = {
            "currency": currency,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        result = await self._request("GET", "/public/get_volatility_index_data", params)
        return result.get("data", [])

    async def get_current_dvol(self, currency: str = "BTC") -> float:
        """Get current DVOL value.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            Current DVOL value.
        """
        index_name = f"dvol_{currency.lower()}"
        result = await self._request("GET", "/public/get_index_price", {"index_name": index_name})
        return result["index_price"]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_deribit_client.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/data/deribit_client.py tests/unit/test_deribit_client.py
git commit -m "feat: add DVOL index fetching to Deribit client"
```

---

## Task 8: Repository Pattern for Database

**Files:**
- Create: `src/persistence/repositories.py`
- Create: `tests/unit/test_repositories.py`

**Step 1: Write the failing test for trade repository**

Create `tests/unit/test_repositories.py`:
```python
"""Tests for database repositories."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.persistence.database import Database
from src.persistence.repositories import TradeRepository, PositionRepository, SnapshotRepository
from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create initialized test database."""
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    return db


@pytest.fixture
def trade_repo(db: Database) -> TradeRepository:
    return TradeRepository(db)


@pytest.fixture
def position_repo(db: Database) -> PositionRepository:
    return PositionRepository(db)


@pytest.fixture
def snapshot_repo(db: Database) -> SnapshotRepository:
    return SnapshotRepository(db)


def test_trade_repository_save_and_get(trade_repo: TradeRepository) -> None:
    """Test saving and retrieving a trade."""
    trade = Trade(
        strategy_id="WHL-001",
        strategy_type="wheel",
        order_id="ORD-123",
        instrument="BTC-28MAR25-100000-P",
        side="sell",
        quantity=0.1,
        price=1500.0,
        status=TradeStatus.FILLED,
        opened_at=datetime.now(timezone.utc),
    )

    trade_id = trade_repo.save(trade)
    assert trade_id > 0

    retrieved = trade_repo.get_by_id(trade_id)
    assert retrieved is not None
    assert retrieved.strategy_id == "WHL-001"
    assert retrieved.order_id == "ORD-123"


def test_trade_repository_get_by_strategy(trade_repo: TradeRepository) -> None:
    """Test retrieving trades by strategy ID."""
    now = datetime.now(timezone.utc)

    trade_repo.save(Trade(
        strategy_id="WHL-001", strategy_type="wheel", instrument="BTC-P",
        side="sell", quantity=0.1, price=1500.0, status=TradeStatus.FILLED, opened_at=now,
    ))
    trade_repo.save(Trade(
        strategy_id="WHL-001", strategy_type="wheel", instrument="BTC-C",
        side="sell", quantity=0.1, price=1200.0, status=TradeStatus.FILLED, opened_at=now,
    ))
    trade_repo.save(Trade(
        strategy_id="IC-001", strategy_type="iron_condor", instrument="BTC-P",
        side="sell", quantity=0.2, price=800.0, status=TradeStatus.FILLED, opened_at=now,
    ))

    wheel_trades = trade_repo.get_by_strategy("WHL-001")
    assert len(wheel_trades) == 2


def test_position_repository_save_and_update(position_repo: PositionRepository) -> None:
    """Test saving and updating a position."""
    position = Position(
        strategy_id="IC-001",
        strategy_type="iron_condor",
        status=PositionStatus.OPEN,
        delta=-0.03,
        theta=47.0,
        opened_at=datetime.now(timezone.utc),
    )

    pos_id = position_repo.save(position)
    assert pos_id > 0

    # Update PnL
    position_repo.update_pnl(pos_id, current_pnl=187.50)

    retrieved = position_repo.get_by_id(pos_id)
    assert retrieved is not None
    assert retrieved.current_pnl == 187.50


def test_snapshot_repository_get_latest(snapshot_repo: SnapshotRepository) -> None:
    """Test retrieving latest snapshot."""
    t1 = datetime(2026, 1, 18, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 18, 10, 5, 0, tzinfo=timezone.utc)

    snapshot_repo.save(MarketSnapshot(
        btc_price=97000.0, dvol=50.0, regime="neutral", timestamp=t1,
    ))
    snapshot_repo.save(MarketSnapshot(
        btc_price=97500.0, dvol=52.0, regime="high_iv", timestamp=t2,
    ))

    latest = snapshot_repo.get_latest()
    assert latest is not None
    assert latest.btc_price == 97500.0
    assert latest.regime == "high_iv"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_repositories.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.persistence.repositories'"

**Step 3: Write minimal implementation**

Create `src/persistence/repositories.py`:
```python
"""Database repositories for CRUD operations."""

from datetime import datetime
from typing import Optional

from src.persistence.database import Database
from src.persistence.models import (
    Trade, Position, MarketSnapshot, DailyPerformance, RiskEvent,
    TradeStatus, PositionStatus,
)


class TradeRepository:
    """Repository for trade operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, trade: Trade) -> int:
        """Save a trade and return its ID."""
        cursor = self.db.connection.cursor()
        cursor.execute("""
            INSERT INTO trades (
                strategy_id, strategy_type, order_id, instrument, side,
                quantity, price, fees, status, opened_at, closed_at, pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.strategy_id, trade.strategy_type, trade.order_id, trade.instrument,
            trade.side, trade.quantity, trade.price, trade.fees, trade.status.value,
            trade.opened_at.isoformat(),
            trade.closed_at.isoformat() if trade.closed_at else None,
            trade.pnl,
        ))
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_by_id(self, trade_id: int) -> Optional[Trade]:
        """Get trade by ID."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_trade(row)

    def get_by_strategy(self, strategy_id: str) -> list[Trade]:
        """Get all trades for a strategy."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM trades WHERE strategy_id = ?", (strategy_id,))
        return [self._row_to_trade(row) for row in cursor.fetchall()]

    def _row_to_trade(self, row: dict) -> Trade:
        """Convert database row to Trade model."""
        return Trade(
            id=row["id"],
            strategy_id=row["strategy_id"],
            strategy_type=row["strategy_type"],
            order_id=row["order_id"],
            instrument=row["instrument"],
            side=row["side"],
            quantity=row["quantity"],
            price=row["price"],
            fees=row["fees"],
            status=TradeStatus(row["status"]),
            opened_at=datetime.fromisoformat(row["opened_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            pnl=row["pnl"],
        )


class PositionRepository:
    """Repository for position operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, position: Position) -> int:
        """Save a position and return its ID."""
        cursor = self.db.connection.cursor()
        cursor.execute("""
            INSERT INTO positions (
                strategy_id, strategy_type, status, phase, entry_price,
                max_profit, max_loss, current_pnl, delta, gamma, theta, vega,
                opened_at, closed_at, close_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.strategy_id, position.strategy_type, position.status.value,
            position.phase, position.entry_price, position.max_profit, position.max_loss,
            position.current_pnl, position.delta, position.gamma, position.theta, position.vega,
            position.opened_at.isoformat(),
            position.closed_at.isoformat() if position.closed_at else None,
            position.close_reason,
        ))
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_position(row)

    def get_open(self) -> list[Position]:
        """Get all open positions."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM positions WHERE status = ?", (PositionStatus.OPEN.value,))
        return [self._row_to_position(row) for row in cursor.fetchall()]

    def update_pnl(self, position_id: int, current_pnl: float) -> None:
        """Update position's current P&L."""
        cursor = self.db.connection.cursor()
        cursor.execute("UPDATE positions SET current_pnl = ? WHERE id = ?", (current_pnl, position_id))
        self.db.connection.commit()

    def update_greeks(
        self,
        position_id: int,
        delta: float,
        gamma: float,
        theta: float,
        vega: float,
    ) -> None:
        """Update position Greeks."""
        cursor = self.db.connection.cursor()
        cursor.execute("""
            UPDATE positions SET delta = ?, gamma = ?, theta = ?, vega = ? WHERE id = ?
        """, (delta, gamma, theta, vega, position_id))
        self.db.connection.commit()

    def close(self, position_id: int, close_reason: str, final_pnl: float) -> None:
        """Close a position."""
        cursor = self.db.connection.cursor()
        cursor.execute("""
            UPDATE positions
            SET status = ?, closed_at = ?, close_reason = ?, current_pnl = ?
            WHERE id = ?
        """, (PositionStatus.CLOSED.value, datetime.utcnow().isoformat(), close_reason, final_pnl, position_id))
        self.db.connection.commit()

    def _row_to_position(self, row: dict) -> Position:
        """Convert database row to Position model."""
        return Position(
            id=row["id"],
            strategy_id=row["strategy_id"],
            strategy_type=row["strategy_type"],
            status=PositionStatus(row["status"]),
            phase=row["phase"],
            entry_price=row["entry_price"],
            max_profit=row["max_profit"],
            max_loss=row["max_loss"],
            current_pnl=row["current_pnl"],
            delta=row["delta"],
            gamma=row["gamma"],
            theta=row["theta"],
            vega=row["vega"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            close_reason=row["close_reason"],
        )


class SnapshotRepository:
    """Repository for market snapshot operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, snapshot: MarketSnapshot) -> int:
        """Save a market snapshot and return its ID."""
        cursor = self.db.connection.cursor()
        cursor.execute("""
            INSERT INTO market_snapshots (
                btc_price, dvol, iv_rank, iv_percentile, rv_7d, rv_30d,
                iv_rv_spread, term_structure_ratio, rr_skew, regime,
                active_strategy, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.btc_price, snapshot.dvol, snapshot.iv_rank, snapshot.iv_percentile,
            snapshot.rv_7d, snapshot.rv_30d, snapshot.iv_rv_spread, snapshot.term_structure_ratio,
            snapshot.rr_skew, snapshot.regime, snapshot.active_strategy, snapshot.timestamp.isoformat(),
        ))
        self.db.connection.commit()
        return cursor.lastrowid or 0

    def get_latest(self) -> Optional[MarketSnapshot]:
        """Get the most recent snapshot."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def get_since(self, since: datetime) -> list[MarketSnapshot]:
        """Get snapshots since a given time."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM market_snapshots WHERE timestamp >= ? ORDER BY timestamp",
            (since.isoformat(),)
        )
        return [self._row_to_snapshot(row) for row in cursor.fetchall()]

    def _row_to_snapshot(self, row: dict) -> MarketSnapshot:
        """Convert database row to MarketSnapshot model."""
        return MarketSnapshot(
            id=row["id"],
            btc_price=row["btc_price"],
            dvol=row["dvol"],
            iv_rank=row["iv_rank"],
            iv_percentile=row["iv_percentile"],
            rv_7d=row["rv_7d"],
            rv_30d=row["rv_30d"],
            iv_rv_spread=row["iv_rv_spread"],
            term_structure_ratio=row["term_structure_ratio"],
            rr_skew=row["rr_skew"],
            regime=row["regime"],
            active_strategy=row["active_strategy"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_repositories.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/persistence/repositories.py tests/unit/test_repositories.py
git commit -m "feat: add repository pattern for trades, positions, snapshots"
```

---

## Task 9: Integration Test with Real Schema

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_full_pipeline.py`

**Step 1: Write integration test**

Create `tests/integration/__init__.py`:
```python
"""Integration tests."""
```

Create `tests/integration/test_full_pipeline.py`:
```python
"""Integration tests for full data pipeline."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_settings, Settings
from src.persistence.database import Database
from src.persistence.repositories import TradeRepository, PositionRepository, SnapshotRepository
from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Create test settings."""
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(f"""
deribit:
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"
database:
  path: "{tmp_path / 'test.db'}"
""")
    return load_settings(config_file)


@pytest.fixture
def db(settings: Settings) -> Database:
    """Create initialized database from settings."""
    db = Database(settings.database.path)
    db.initialize()
    return db


def test_full_wheel_cycle(db: Database) -> None:
    """Test recording a complete wheel strategy cycle."""
    trade_repo = TradeRepository(db)
    position_repo = PositionRepository(db)
    snapshot_repo = SnapshotRepository(db)
    now = datetime.now(timezone.utc)

    # 1. Record market snapshot at entry
    snapshot_repo.save(MarketSnapshot(
        btc_price=97000.0,
        dvol=48.5,
        iv_rank=0.55,
        rv_30d=42.0,
        iv_rv_spread=6.5,
        regime="neutral",
        timestamp=now,
    ))

    # 2. Open wheel position
    pos_id = position_repo.save(Position(
        strategy_id="WHL-001",
        strategy_type="wheel",
        status=PositionStatus.OPEN,
        phase="csp",  # Cash-secured put phase
        entry_price=97000.0,
        max_profit=1500.0,
        delta=-0.25,
        theta=35.0,
        opened_at=now,
    ))

    # 3. Record the CSP trade
    trade_repo.save(Trade(
        strategy_id="WHL-001",
        strategy_type="wheel",
        order_id="ORD-001",
        instrument="BTC-28MAR25-92000-P",
        side="sell",
        quantity=0.1,
        price=1500.0,
        status=TradeStatus.FILLED,
        opened_at=now,
    ))

    # 4. Update position P&L as time passes
    position_repo.update_pnl(pos_id, current_pnl=750.0)  # 50% profit

    # 5. Close position when target reached
    position_repo.close(pos_id, close_reason="50% profit target", final_pnl=750.0)

    # Verify final state
    position = position_repo.get_by_id(pos_id)
    assert position is not None
    assert position.status == PositionStatus.CLOSED
    assert position.current_pnl == 750.0
    assert position.close_reason == "50% profit target"

    trades = trade_repo.get_by_strategy("WHL-001")
    assert len(trades) == 1

    latest_snapshot = snapshot_repo.get_latest()
    assert latest_snapshot is not None
    assert latest_snapshot.regime == "neutral"
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_full_pipeline.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (should be ~12 tests)

**Step 4: Commit**

```bash
git add tests/integration/
git commit -m "test: add integration test for full wheel strategy cycle"
```

---

## Task 10: Wire Up Main Entry Point

**Files:**
- Modify: `src/main.py`

**Step 1: Update main.py to initialize components**

Replace `src/main.py` with:
```python
"""Entry point for the crypto options trading bot."""

import asyncio
import logging
from pathlib import Path

from src.config import load_settings
from src.persistence.database import Database
from src.data.deribit_client import DeribitClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    logger.info("Crypto Options Bot starting...")

    # Load configuration
    config_path = Path("config/settings.yaml")
    if not config_path.exists():
        logger.warning("No config/settings.yaml found, using defaults")
    settings = load_settings(config_path if config_path.exists() else None)

    # Initialize database
    logger.info(f"Initializing database at {settings.database.path}")
    db = Database(settings.database.path)
    db.initialize()
    logger.info("Database initialized")

    # Initialize Deribit client
    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    try:
        # Test connection by fetching index price
        price = await client.get_index_price("btc_usd")
        logger.info(f"Connected to Deribit. BTC price: ${price:,.2f}")

        # Fetch DVOL
        dvol = await client.get_current_dvol("BTC")
        logger.info(f"Current DVOL: {dvol:.1f}")

        logger.info("Bot initialized successfully. Ready for Phase 2 implementation.")

    except Exception as e:
        logger.error(f"Failed to connect to Deribit: {e}")
    finally:
        await client.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Test manual run (requires internet)**

Run: `python -m src.main`
Expected: Logs showing "Crypto Options Bot starting..." and either successful price fetch or connection error (both are valid for this phase)

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: wire up main entry point with config, database, and client initialization"
```

---

## Task 11: Final Verification and Cleanup

**Step 1: Run full test suite with coverage**

Run: `pytest --cov=src --cov-report=term-missing -v`
Expected: All tests pass, coverage report shows coverage for src/

**Step 2: Run type checking**

Run: `mypy src/`
Expected: No errors (or only minor ones to fix)

**Step 3: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors (or minor formatting to fix)

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: phase 1 foundation complete - scaffolding, config, database, deribit client"
```

---

## Summary

Phase 1 creates the foundation:

| Component | Files | Purpose |
|-----------|-------|---------|
| **Scaffolding** | pyproject.toml, requirements*.txt | Python packaging and dependencies |
| **Configuration** | src/config.py, config/*.yaml | Pydantic-validated settings |
| **Database** | src/persistence/database.py | SQLite with 5 tables |
| **Models** | src/persistence/models.py | Pydantic data models |
| **Repositories** | src/persistence/repositories.py | CRUD operations |
| **Deribit Client** | src/data/deribit_client.py | REST API (auth, trading, DVOL) |
| **Entry Point** | src/main.py | Initializes all components |

**Next Phase:** Phase 2 will add the volatility calculator and regime detector, building on this foundation.
