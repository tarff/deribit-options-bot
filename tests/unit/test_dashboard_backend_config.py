"""Tests for dashboard backend configuration selection."""

import sqlite3
import sys
from pathlib import Path

import pytest


BACKEND_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


def test_dashboard_config_uses_explicit_env_path(tmp_path: Path, monkeypatch) -> None:
    """Dashboard config loader should honor an explicit config path."""
    config_path = tmp_path / "settings.mainnet.yaml"
    config_path.write_text(
        """
database:
  path: data/mainnet.db
trading:
  currency: ETH
""".strip()
    )
    monkeypatch.setenv("OPTIONS_BOT_CONFIG", str(config_path))

    from services.config_loader import load_dashboard_config

    config = load_dashboard_config()

    assert config["database"]["path"] == "data/mainnet.db"


def test_database_service_uses_configured_database_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """DatabaseService default path should come from selected config."""
    config_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "mainnet.db"
    config_path.write_text(f"database:\n  path: {db_path}\n")
    monkeypatch.setenv("OPTIONS_BOT_CONFIG", str(config_path))
    monkeypatch.delenv("VEGA_DB_PATH", raising=False)

    from services.db_service import DatabaseService

    service = DatabaseService()

    assert service.db_path == str(db_path)


@pytest.mark.asyncio
async def test_bot_positions_uses_configured_database_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Bot positions endpoint should use the selected configured database."""
    db_path = tmp_path / "bot.db"
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(f"database:\n  path: {db_path}\n")
    monkeypatch.setenv("OPTIONS_BOT_CONFIG", str(config_path))
    monkeypatch.delenv("VEGA_DB_PATH", raising=False)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE positions (
                strategy_id TEXT,
                strategy_type TEXT,
                status TEXT,
                opened_at TEXT,
                entry_price REAL,
                current_pnl REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE position_contracts (
                strategy_id TEXT,
                instrument_name TEXT,
                strike REAL,
                expiry TEXT,
                option_type TEXT,
                direction TEXT,
                quantity REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO positions
                (strategy_id, strategy_type, status, opened_at, entry_price, current_pnl)
            VALUES ('wheel-1', 'wheel', 'open', '2026-01-01T00:00:00Z', 2500, 0)
            """
        )

    from routers.positions import get_bot_positions

    result = await get_bot_positions()

    assert result["db_path"] == str(db_path)
    assert result["positions"][0]["strategy_type"] == "wheel"


def test_strategy_breakdown_uses_persisted_lowercase_strategy_types() -> None:
    """Stats breakdown should match strategy_type values persisted by the bot."""
    from routers.stats import _get_strategy_breakdown

    class FakeDb:
        def get_trades(self, limit: int, strategy_type: str):
            if strategy_type == "wheel":
                return [{"pnl": 2.0}, {"pnl": -1.0}]
            return []

    breakdown = _get_strategy_breakdown(FakeDb())

    assert breakdown["wheel"]["trades"] == 2


@pytest.mark.asyncio
async def test_trades_by_strategy_uses_persisted_lowercase_strategy_type(
    monkeypatch,
) -> None:
    """Trades by strategy should not uppercase lowercase enum values."""
    from routers import trades

    class FakeDb:
        strategy_type = ""

        def table_exists(self, table: str) -> bool:
            return table == "trades"

        def get_trades(self, limit: int, strategy_type: str):
            self.strategy_type = strategy_type
            return [{"strategy_type": strategy_type}]

    fake_db = FakeDb()
    monkeypatch.setattr(trades, "get_db_service", lambda: fake_db)

    result = await trades.get_trades_by_strategy("wheel")

    assert fake_db.strategy_type == "wheel"
    assert result == [{"strategy_type": "wheel"}]
