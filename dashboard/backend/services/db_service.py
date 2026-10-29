"""
Database Service

Provides access to the bot's SQLite database for historical data.
"""

import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional
from contextlib import contextmanager

from services.config_loader import get_configured_database_path


class DatabaseService:
    """Service for accessing the trading bot's SQLite database."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = get_configured_database_path()
        self.db_path = db_path
        self._lock = threading.Lock()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections (thread-safe)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def get_trades(
        self,
        limit: int = 100,
        offset: int = 0,
        strategy_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch trades from the database."""
        # Column mapping: actual schema → expected by frontend
        # created_at → timestamp, instrument → instrument_name, fees → fee
        query = """
            SELECT
                id,
                created_at as timestamp,
                instrument as instrument_name,
                side,
                quantity,
                price,
                fees as fee,
                pnl,
                strategy_type
            FROM trades
            WHERE 1=1
        """
        params: list[Any] = []

        if strategy_type:
            query += " AND strategy_type = ?"
            params.append(strategy_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            print(f"Database error fetching trades: {e}")
            return []

    def get_positions(self, status: str = "open") -> list[dict[str, Any]]:
        """Fetch positions from the database.

        Joins positions with position_contracts to get instrument details.
        """
        # Get positions with their contracts
        query = """
            SELECT
                p.id,
                p.strategy_id,
                p.strategy_type,
                p.status,
                p.phase,
                p.entry_price,
                p.max_profit,
                p.max_loss,
                p.current_pnl,
                p.delta,
                p.gamma,
                p.theta,
                p.vega,
                p.opened_at,
                p.closed_at,
                p.close_reason
            FROM positions p
            WHERE 1=1
        """
        params: list[Any] = []

        if status == "open":
            query += " AND p.status = 'open'"
        elif status == "closed":
            query += " AND p.status = 'closed'"

        query += " ORDER BY p.opened_at DESC"

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                positions = [dict(row) for row in cursor.fetchall()]

                # Get contracts for each position
                for pos in positions:
                    cursor = conn.execute(
                        """
                        SELECT instrument_name, strike, expiry, option_type,
                               quantity, direction
                        FROM position_contracts
                        WHERE strategy_id = ?
                        """,
                        [pos["strategy_id"]],
                    )
                    pos["contracts"] = [dict(row) for row in cursor.fetchall()]

                return positions
        except sqlite3.Error as e:
            print(f"Database error fetching positions: {e}")
            return []

    def get_market_snapshots(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch historical market snapshots."""
        query = """
            SELECT
                timestamp,
                btc_price,
                dvol,
                iv_rank,
                rv_30d as realized_vol,
                regime
            FROM market_snapshots
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            LIMIT ?
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    query,
                    [start_time.isoformat(), end_time.isoformat(), limit],
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            print(f"Database error fetching snapshots: {e}")
            return []

    def get_trade_stats(self) -> dict[str, Any]:
        """Calculate aggregate trade statistics."""
        query = """
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                SUM(pnl) as total_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss
            FROM trades
            WHERE pnl IS NOT NULL
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(query)
                row = cursor.fetchone()

                if row is None:
                    return self._empty_stats()

                total = row["total_trades"] or 0
                winning = row["winning_trades"] or 0
                losing = row["losing_trades"] or 0
                total_pnl = row["total_pnl"] or 0
                avg_win = row["avg_win"] or 0
                avg_loss = row["avg_loss"] or 0

                # Calculate profit factor
                gross_profit = self._get_gross_profit(conn)
                gross_loss = abs(self._get_gross_loss(conn))
                profit_factor = (
                    gross_profit / gross_loss if gross_loss > 0 else float("inf")
                )

                return {
                    "total_trades": total,
                    "winning_trades": winning,
                    "losing_trades": losing,
                    "win_rate": (winning / total * 100) if total > 0 else 0,
                    "total_pnl": total_pnl,
                    "avg_win": avg_win,
                    "avg_loss": avg_loss,
                    "profit_factor": min(profit_factor, 999.99),
                }

        except sqlite3.Error as e:
            print(f"Database error calculating stats: {e}")
            return self._empty_stats()

    def _get_gross_profit(self, conn: sqlite3.Connection) -> float:
        """Get sum of all profitable trades."""
        cursor = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE pnl > 0"
        )
        return cursor.fetchone()[0]

    def _get_gross_loss(self, conn: sqlite3.Connection) -> float:
        """Get sum of all losing trades."""
        cursor = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE pnl < 0"
        )
        return cursor.fetchone()[0]

    def _empty_stats(self) -> dict[str, Any]:
        """Return empty stats structure."""
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
        }

    def get_historical_prices(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch historical price/DVOL data from historical_data table.

        Returns OHLCV data for price and DVOL.
        """
        query = """
            SELECT
                timestamp,
                btc_price as close,
                btc_open as open,
                btc_high as high,
                btc_low as low,
                btc_volume as volume,
                dvol,
                dvol_open,
                dvol_high,
                dvol_low
            FROM historical_data
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    query,
                    [start_time.isoformat(), end_time.isoformat()],
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            print(f"Database error fetching historical prices: {e}")
            return []

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    [table_name],
                )
                return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
