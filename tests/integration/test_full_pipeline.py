"""Integration tests for full data pipeline."""

import pytest
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_settings, Settings
from src.persistence.database import Database
from src.persistence.repositories import TradeRepository, PositionRepository, SnapshotRepository
from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus, TradeSide


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Create test settings."""
    config_file = tmp_path / "settings.yaml"
    db_path = (tmp_path / "test.db").as_posix()
    config_file.write_text(f"""
deribit:
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"
database:
  path: "{db_path}"
""")
    return load_settings(config_file)


@pytest.fixture
def db(settings: Settings) -> Generator[Database, None, None]:
    """Create initialized database from settings."""
    database = Database(settings.database.path)
    database.initialize()
    yield database
    database.close()


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
        side=TradeSide.SELL,
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
