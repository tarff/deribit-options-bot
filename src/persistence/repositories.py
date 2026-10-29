"""Database repositories for CRUD operations."""

from datetime import datetime, timezone
from typing import Any, Optional
import logging

from src.persistence.database import Database
from src.persistence.models import (
    Trade, Position, MarketSnapshot, TradeStatus, PositionStatus, TradeSide,
    HistoricalDataPoint, PositionContract, PaperTradingState,
)

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime, field_name: str) -> datetime:
    """Ensure datetime is timezone-aware UTC for consistent storage.

    SQLite stores timestamps as ISO strings. Mixing timezone-aware and naive
    timestamps causes incorrect lexicographic comparisons. This function
    normalizes all datetimes to UTC.

    Args:
        dt: Datetime to validate.
        field_name: Field name for error messages.

    Returns:
        UTC datetime.

    Raises:
        ValueError: If datetime is naive (no timezone info).
    """
    if dt.tzinfo is None:
        raise ValueError(
            f"{field_name} must be timezone-aware. "
            f"Use datetime.replace(tzinfo=timezone.utc) or pass UTC datetime. "
            f"Got naive datetime: {dt}"
        )
    # Convert to UTC if different timezone
    return dt.astimezone(timezone.utc)


class TradeRepository:
    """Repository for trade operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, trade: Trade) -> int:
        """Save a trade and return its ID."""
        with self.db.transaction() as cursor:
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

    def get_all(self, limit: int = 100) -> list[Trade]:
        """Get all trades, most recent first.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of trades ordered by opened_at descending.
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_trade(row) for row in cursor.fetchall()]

    def get_closed(self, limit: int = 100) -> list[Trade]:
        """Get closed trades, most recent first.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of filled trades ordered by closed_at descending.
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM trades WHERE status = ? AND closed_at IS NOT NULL "
            "ORDER BY closed_at DESC LIMIT ?",
            (TradeStatus.FILLED.value, limit)
        )
        return [self._row_to_trade(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Get total number of trades."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades")
        row = cursor.fetchone()
        return row[0] if row else 0

    def _row_to_trade(self, row: dict[str, Any]) -> Trade:
        """Convert database row to Trade model."""
        return Trade(
            id=row["id"],
            strategy_id=row["strategy_id"],
            strategy_type=row["strategy_type"],
            order_id=row["order_id"],
            instrument=row["instrument"],
            side=TradeSide(row["side"]),
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
        with self.db.transaction() as cursor:
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

    def get_by_strategy_id(self, strategy_id: str) -> Optional[Position]:
        """Get position by strategy_id.

        Args:
            strategy_id: Unique strategy/position identifier.

        Returns:
            Position if found, None otherwise.
        """
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM positions WHERE strategy_id = ?", (strategy_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_position(row)

    def get_closed(self, limit: int = 100) -> list[Position]:
        """Get closed positions, most recent first.

        Args:
            limit: Maximum number of positions to return.

        Returns:
            List of closed positions ordered by closed_at descending.
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM positions WHERE status IN (?, ?) "
            "ORDER BY closed_at DESC LIMIT ?",
            (PositionStatus.CLOSED.value, PositionStatus.EXPIRED.value, limit)
        )
        return [self._row_to_position(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Get total number of positions."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM positions")
        row = cursor.fetchone()
        return row[0] if row else 0

    def count_closed(self) -> int:
        """Get number of closed positions."""
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM positions WHERE status IN (?, ?)",
            (PositionStatus.CLOSED.value, PositionStatus.EXPIRED.value)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def update_pnl(self, position_id: int, current_pnl: float) -> None:
        """Update position's current P&L."""
        with self.db.transaction() as cursor:
            cursor.execute("UPDATE positions SET current_pnl = ? WHERE id = ?", (current_pnl, position_id))

    def update_greeks(
        self,
        position_id: int,
        delta: float,
        gamma: float,
        theta: float,
        vega: float,
    ) -> None:
        """Update position Greeks."""
        with self.db.transaction() as cursor:
            cursor.execute("""
                UPDATE positions SET delta = ?, gamma = ?, theta = ?, vega = ? WHERE id = ?
            """, (delta, gamma, theta, vega, position_id))

    def close(self, position_id: int, close_reason: str, final_pnl: float) -> None:
        """Close a position."""
        with self.db.transaction() as cursor:
            cursor.execute("""
                UPDATE positions
                SET status = ?, closed_at = ?, close_reason = ?, current_pnl = ?
                WHERE id = ?
            """, (PositionStatus.CLOSED.value, datetime.now(timezone.utc).isoformat(), close_reason, final_pnl, position_id))

    def _row_to_position(self, row: dict[str, Any]) -> Position:
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
        with self.db.transaction() as cursor:
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

    def _row_to_snapshot(self, row: dict[str, Any]) -> MarketSnapshot:
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


class HistoricalDataRepository:
    """Repository for historical market data operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, point: HistoricalDataPoint) -> int:
        """Save a single historical data point and return its ID.

        Args:
            point: Data point to save. Timestamp must be timezone-aware.

        Returns:
            ID of saved record.

        Raises:
            ValueError: If timestamp is timezone-naive.
        """
        ts = _ensure_utc(point.timestamp, "point.timestamp")
        with self.db.transaction() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO historical_data (
                    timestamp, btc_price, btc_open, btc_high, btc_low, btc_volume,
                    dvol, dvol_open, dvol_high, dvol_low
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts.isoformat(),
                point.btc_price, point.btc_open, point.btc_high,
                point.btc_low, point.btc_volume,
                point.dvol, point.dvol_open, point.dvol_high, point.dvol_low,
            ))
            return cursor.lastrowid or 0

    def save_batch(self, points: list[HistoricalDataPoint]) -> int:
        """Bulk insert historical data points.

        Args:
            points: Data points to save. All timestamps must be timezone-aware.

        Returns:
            Number of records inserted.

        Raises:
            ValueError: If any timestamp is timezone-naive.
        """
        if not points:
            return 0

        data = [
            (
                _ensure_utc(p.timestamp, f"points[{i}].timestamp").isoformat(),
                p.btc_price, p.btc_open, p.btc_high, p.btc_low, p.btc_volume,
                p.dvol, p.dvol_open, p.dvol_high, p.dvol_low,
            )
            for i, p in enumerate(points)
        ]
        with self.db.transaction() as cursor:
            cursor.executemany("""
                INSERT OR REPLACE INTO historical_data (
                    timestamp, btc_price, btc_open, btc_high, btc_low, btc_volume,
                    dvol, dvol_open, dvol_high, dvol_low
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
        return len(points)

    def get_latest_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the most recent data point."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT MAX(timestamp) FROM historical_data")
        row = cursor.fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def get_range(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[HistoricalDataPoint]:
        """Get historical data within a date range.

        Args:
            start: Start datetime (inclusive). If None, no lower bound.
                Must be timezone-aware if provided.
            end: End datetime (inclusive). If None, no upper bound.
                Must be timezone-aware if provided.

        Returns:
            List of HistoricalDataPoint objects sorted by timestamp.

        Raises:
            ValueError: If start or end is timezone-naive.
        """
        cursor = self.db.connection.cursor()

        # Validate and normalize to UTC
        start_iso = _ensure_utc(start, "start").isoformat() if start else None
        end_iso = _ensure_utc(end, "end").isoformat() if end else None

        if start_iso and end_iso:
            cursor.execute(
                "SELECT * FROM historical_data WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_iso, end_iso)
            )
        elif start_iso:
            cursor.execute(
                "SELECT * FROM historical_data WHERE timestamp >= ? ORDER BY timestamp",
                (start_iso,)
            )
        elif end_iso:
            cursor.execute(
                "SELECT * FROM historical_data WHERE timestamp <= ? ORDER BY timestamp",
                (end_iso,)
            )
        else:
            cursor.execute("SELECT * FROM historical_data ORDER BY timestamp")

        return [self._row_to_point(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Get total number of historical data points."""
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM historical_data")
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_date_bounds(self) -> tuple[Optional[datetime], Optional[datetime]]:
        """Get the earliest and latest timestamps efficiently.

        Uses SQL MIN/MAX instead of loading all records.

        Returns:
            Tuple of (earliest_timestamp, latest_timestamp) or (None, None) if empty.
        """
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM historical_data")
        row = cursor.fetchone()
        if row and row[0] and row[1]:
            return (
                datetime.fromisoformat(row[0]),
                datetime.fromisoformat(row[1]),
            )
        return None, None

    def _row_to_point(self, row: dict[str, Any]) -> HistoricalDataPoint:
        """Convert database row to HistoricalDataPoint model."""
        return HistoricalDataPoint(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            btc_price=row["btc_price"],
            btc_open=row["btc_open"],
            btc_high=row["btc_high"],
            btc_low=row["btc_low"],
            btc_volume=row["btc_volume"],
            dvol=row["dvol"],
            dvol_open=row["dvol_open"],
            dvol_high=row["dvol_high"],
            dvol_low=row["dvol_low"],
        )


class PositionContractRepository:
    """Repository for position contract (option leg) operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, contract: PositionContract) -> int:
        """Save a position contract and return its ID."""
        with self.db.transaction() as cursor:
            cursor.execute("""
                INSERT INTO position_contracts (
                    strategy_id, instrument_name, strike, expiry, option_type,
                    delta, gamma, theta, vega, iv, bid, ask, mark_price,
                    quantity, direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                contract.strategy_id, contract.instrument_name, contract.strike,
                contract.expiry.isoformat(), contract.option_type,
                contract.delta, contract.gamma, contract.theta, contract.vega,
                contract.iv, contract.bid, contract.ask, contract.mark_price,
                contract.quantity, contract.direction,
            ))
            return cursor.lastrowid or 0

    def save_batch(self, contracts: list[PositionContract]) -> int:
        """Bulk insert position contracts.

        Args:
            contracts: List of contracts to save.

        Returns:
            Number of contracts inserted.
        """
        if not contracts:
            return 0

        data = [
            (
                c.strategy_id, c.instrument_name, c.strike,
                c.expiry.isoformat(), c.option_type,
                c.delta, c.gamma, c.theta, c.vega,
                c.iv, c.bid, c.ask, c.mark_price,
                c.quantity, c.direction,
            )
            for c in contracts
        ]
        with self.db.transaction() as cursor:
            cursor.executemany("""
                INSERT INTO position_contracts (
                    strategy_id, instrument_name, strike, expiry, option_type,
                    delta, gamma, theta, vega, iv, bid, ask, mark_price,
                    quantity, direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
        return len(contracts)

    def get_by_strategy_id(self, strategy_id: str) -> list[PositionContract]:
        """Get all contracts for a position.

        Args:
            strategy_id: Strategy/position identifier.

        Returns:
            List of PositionContract objects.
        """
        cursor = self.db.connection.cursor()
        cursor.execute(
            "SELECT * FROM position_contracts WHERE strategy_id = ?",
            (strategy_id,)
        )
        return [self._row_to_contract(row) for row in cursor.fetchall()]

    def delete_by_strategy_id(self, strategy_id: str) -> int:
        """Delete all contracts for a position.

        Args:
            strategy_id: Strategy/position identifier.

        Returns:
            Number of contracts deleted.
        """
        with self.db.transaction() as cursor:
            cursor.execute(
                "DELETE FROM position_contracts WHERE strategy_id = ?",
                (strategy_id,)
            )
            return cursor.rowcount

    def _row_to_contract(self, row: dict[str, Any]) -> PositionContract:
        """Convert database row to PositionContract model."""
        return PositionContract(
            id=row["id"],
            strategy_id=row["strategy_id"],
            instrument_name=row["instrument_name"],
            strike=row["strike"],
            expiry=datetime.fromisoformat(row["expiry"]),
            option_type=row["option_type"],
            delta=row["delta"],
            gamma=row["gamma"],
            theta=row["theta"],
            vega=row["vega"],
            iv=row["iv"],
            bid=row["bid"],
            ask=row["ask"],
            mark_price=row["mark_price"],
            quantity=row["quantity"],
            direction=row["direction"],
        )


class PaperTradingStateRepository:
    """Repository for paper trading state (single row table)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self) -> Optional[PaperTradingState]:
        """Get current paper trading state.

        Returns:
            PaperTradingState if exists, None otherwise.
        """
        cursor = self.db.connection.cursor()
        cursor.execute("SELECT * FROM paper_trading_state WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def save(self, state: PaperTradingState) -> None:
        """Save or update paper trading state.

        Uses INSERT OR REPLACE to handle both insert and update.

        Args:
            state: State to save.
        """
        with self.db.transaction() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO paper_trading_state (
                    id, capital, peak_capital, daily_pnl, current_day, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?)
            """, (
                state.capital,
                state.peak_capital,
                state.daily_pnl,
                state.current_day.isoformat() if state.current_day else None,
                datetime.now(timezone.utc).isoformat(),
            ))

    def update_capital(self, capital: float, peak_capital: float) -> None:
        """Update capital values.

        Args:
            capital: Current capital.
            peak_capital: Peak capital for drawdown tracking.
        """
        with self.db.transaction() as cursor:
            cursor.execute("""
                UPDATE paper_trading_state
                SET capital = ?, peak_capital = ?, updated_at = ?
                WHERE id = 1
            """, (capital, peak_capital, datetime.now(timezone.utc).isoformat()))

    def update_daily_pnl(self, daily_pnl: float, current_day: datetime) -> None:
        """Update daily PnL tracking.

        Args:
            daily_pnl: Current day's PnL.
            current_day: Current date.
        """
        with self.db.transaction() as cursor:
            cursor.execute("""
                UPDATE paper_trading_state
                SET daily_pnl = ?, current_day = ?, updated_at = ?
                WHERE id = 1
            """, (daily_pnl, current_day.isoformat(), datetime.now(timezone.utc).isoformat()))

    def _row_to_state(self, row: dict[str, Any]) -> PaperTradingState:
        """Convert database row to PaperTradingState model."""
        return PaperTradingState(
            id=row["id"],
            capital=row["capital"],
            peak_capital=row["peak_capital"],
            daily_pnl=row["daily_pnl"] or 0.0,
            current_day=datetime.fromisoformat(row["current_day"]) if row["current_day"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
