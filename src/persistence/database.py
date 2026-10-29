"""SQLite database management."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class Database:
    """SQLite database manager with thread-safe access."""

    def __init__(self, db_path: str) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection (thread-safe).

        Ensures foreign key constraints are enabled on every new connection
        (SQLite PRAGMA settings are per-connection, not persistent).
        """
        with self._lock:
            if self._connection is None:
                # Ensure parent directory exists
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
                self._connection.execute("PRAGMA foreign_keys = ON")
            return self._connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for atomic transactions.

        Yields a cursor. Commits on success, rolls back on exception.
        """
        with self._lock:
            cursor = self.connection.cursor()
            try:
                yield cursor
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

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

        # Historical data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT UNIQUE NOT NULL,
                btc_price REAL NOT NULL,
                btc_open REAL NOT NULL,
                btc_high REAL NOT NULL,
                btc_low REAL NOT NULL,
                btc_volume REAL NOT NULL,
                dvol REAL NOT NULL,
                dvol_open REAL NOT NULL,
                dvol_high REAL NOT NULL,
                dvol_low REAL NOT NULL
            )
        """)

        # Position contracts table - option legs for each position
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS position_contracts (
                id INTEGER PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                instrument_name TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TIMESTAMP NOT NULL,
                option_type TEXT NOT NULL,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                iv REAL,
                bid REAL,
                ask REAL,
                mark_price REAL,
                quantity REAL DEFAULT 1.0,
                direction TEXT DEFAULT 'long',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (strategy_id) REFERENCES positions(strategy_id)
            )
        """)

        # Paper trading state table - single row for capital tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS paper_trading_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                capital REAL NOT NULL,
                peak_capital REAL NOT NULL,
                daily_pnl REAL DEFAULT 0,
                current_day DATE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON market_snapshots(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_performance(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_timestamp ON historical_data(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_position_contracts_strategy ON position_contracts(strategy_id)")

        # Enable foreign key constraint enforcement
        cursor.execute("PRAGMA foreign_keys = ON")

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
