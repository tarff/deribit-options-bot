"""Tests for new persistence classes (PositionContractRepository, PaperTradingStateRepository)."""

import pytest
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from src.persistence.database import Database
from src.persistence.models import (
    PositionContract,
    PaperTradingState,
    Position,
    PositionStatus,
)
from src.persistence.repositories import (
    PositionContractRepository,
    PaperTradingStateRepository,
    PositionRepository,
)


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


def _create_parent_position(db: Database, strategy_id: str) -> None:
    """Create a parent position to satisfy FK constraints."""
    pos_repo = PositionRepository(db)
    pos_repo.save(Position(
        strategy_id=strategy_id,
        strategy_type="wheel",
        status=PositionStatus.OPEN,
        opened_at=datetime.now(timezone.utc),
    ))


class TestPositionContractRepository:
    """Tests for PositionContractRepository."""

    def test_save_and_get_by_strategy_id(self, db: Database) -> None:
        """Test saving and retrieving contracts by strategy_id."""
        _create_parent_position(db, "test123")
        repo = PositionContractRepository(db)
        now = datetime.now(timezone.utc)

        contract = PositionContract(
            strategy_id="test123",
            instrument_name="BTC-28MAR25-100000-C",
            strike=100000.0,
            expiry=now,
            option_type="call",
            delta=0.25,
            gamma=0.001,
            theta=-10.0,
            vega=50.0,
            iv=0.65,
            bid=0.05,
            ask=0.06,
            mark_price=0.055,
            quantity=1.0,
            direction="long",
        )

        # Save
        contract_id = repo.save(contract)
        assert contract_id > 0

        # Retrieve
        contracts = repo.get_by_strategy_id("test123")
        assert len(contracts) == 1
        assert contracts[0].instrument_name == "BTC-28MAR25-100000-C"
        assert contracts[0].strike == 100000.0
        assert contracts[0].delta == 0.25

    def test_save_batch(self, db: Database) -> None:
        """Test bulk saving contracts."""
        _create_parent_position(db, "batch123")
        repo = PositionContractRepository(db)
        now = datetime.now(timezone.utc)

        contracts = [
            PositionContract(
                strategy_id="batch123",
                instrument_name=f"BTC-28MAR25-{strike}-C",
                strike=float(strike),
                expiry=now,
                option_type="call",
            )
            for strike in [95000, 100000, 105000]
        ]

        count = repo.save_batch(contracts)
        assert count == 3

        retrieved = repo.get_by_strategy_id("batch123")
        assert len(retrieved) == 3

    def test_delete_by_strategy_id(self, db: Database) -> None:
        """Test deleting contracts by strategy_id."""
        _create_parent_position(db, "delete123")
        repo = PositionContractRepository(db)
        now = datetime.now(timezone.utc)

        # Save some contracts
        for i in range(3):
            contract = PositionContract(
                strategy_id="delete123",
                instrument_name=f"BTC-TEST-{i}",
                strike=100000.0,
                expiry=now,
                option_type="call",
            )
            repo.save(contract)

        # Verify saved
        assert len(repo.get_by_strategy_id("delete123")) == 3

        # Delete
        deleted = repo.delete_by_strategy_id("delete123")
        assert deleted == 3

        # Verify deleted
        assert len(repo.get_by_strategy_id("delete123")) == 0

    def test_get_nonexistent_strategy(self, db: Database) -> None:
        """Test getting contracts for nonexistent strategy."""
        repo = PositionContractRepository(db)
        contracts = repo.get_by_strategy_id("nonexistent")
        assert contracts == []


class TestPaperTradingStateRepository:
    """Tests for PaperTradingStateRepository."""

    def test_save_and_get(self, db: Database) -> None:
        """Test saving and retrieving state."""
        repo = PaperTradingStateRepository(db)
        now = datetime.now(timezone.utc)

        state = PaperTradingState(
            capital=50000.0,
            peak_capital=52000.0,
            daily_pnl=1500.0,
            current_day=now,
        )

        repo.save(state)

        retrieved = repo.get()
        assert retrieved is not None
        assert retrieved.capital == 50000.0
        assert retrieved.peak_capital == 52000.0
        assert retrieved.daily_pnl == 1500.0

    def test_save_overwrites_previous(self, db: Database) -> None:
        """Test that save replaces existing state."""
        repo = PaperTradingStateRepository(db)
        now = datetime.now(timezone.utc)

        # Save initial state
        state1 = PaperTradingState(
            capital=10000.0,
            peak_capital=10000.0,
            daily_pnl=0.0,
            current_day=now,
        )
        repo.save(state1)

        # Save new state
        state2 = PaperTradingState(
            capital=12000.0,
            peak_capital=12500.0,
            daily_pnl=2000.0,
            current_day=now,
        )
        repo.save(state2)

        # Should get latest
        retrieved = repo.get()
        assert retrieved is not None
        assert retrieved.capital == 12000.0
        assert retrieved.peak_capital == 12500.0

    def test_get_when_empty(self, db: Database) -> None:
        """Test getting state when table is empty."""
        repo = PaperTradingStateRepository(db)
        state = repo.get()
        assert state is None

    def test_update_capital(self, db: Database) -> None:
        """Test updating capital values."""
        repo = PaperTradingStateRepository(db)

        # Save initial state
        state = PaperTradingState(
            capital=10000.0,
            peak_capital=10000.0,
        )
        repo.save(state)

        # Update capital
        repo.update_capital(15000.0, 15000.0)

        retrieved = repo.get()
        assert retrieved is not None
        assert retrieved.capital == 15000.0
        assert retrieved.peak_capital == 15000.0

    def test_update_daily_pnl(self, db: Database) -> None:
        """Test updating daily PnL."""
        repo = PaperTradingStateRepository(db)
        now = datetime.now(timezone.utc)

        # Save initial state
        state = PaperTradingState(
            capital=10000.0,
            peak_capital=10000.0,
            daily_pnl=0.0,
        )
        repo.save(state)

        # Update daily PnL
        repo.update_daily_pnl(500.0, now)

        retrieved = repo.get()
        assert retrieved is not None
        assert retrieved.daily_pnl == 500.0


class TestPositionRepositoryNewMethods:
    """Tests for new PositionRepository methods."""

    def test_get_by_strategy_id(self, db: Database) -> None:
        """Test getting position by strategy_id."""
        repo = PositionRepository(db)
        now = datetime.now(timezone.utc)

        position = Position(
            strategy_id="unique_id_123",
            strategy_type="wheel",
            status=PositionStatus.OPEN,
            phase="open",
            entry_price=95000.0,
            opened_at=now,
        )
        repo.save(position)

        retrieved = repo.get_by_strategy_id("unique_id_123")
        assert retrieved is not None
        assert retrieved.strategy_id == "unique_id_123"
        assert retrieved.strategy_type == "wheel"
        assert retrieved.status == PositionStatus.OPEN

    def test_get_by_strategy_id_nonexistent(self, db: Database) -> None:
        """Test getting nonexistent position returns None."""
        repo = PositionRepository(db)
        result = repo.get_by_strategy_id("does_not_exist")
        assert result is None
