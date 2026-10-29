"""Tests for database operations."""

import pytest
from collections.abc import Generator
from pathlib import Path

from src.persistence.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    yield database
    database.close()


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
    assert "historical_data" in tables
    assert "position_contracts" in tables
    assert "paper_trading_state" in tables


def test_database_is_idempotent(db: Database) -> None:
    """Test that initializing twice doesn't fail."""
    db.initialize()
    db.initialize()  # Should not raise

    tables = db.get_tables()
    assert len(tables) == 8
