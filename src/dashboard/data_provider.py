"""Data provider for dashboard visualizations."""

from datetime import datetime, timedelta, timezone
from typing import Any

from src.persistence.database import Database
from src.persistence.repositories import (
    HistoricalDataRepository,
    PositionRepository,
    PositionContractRepository,
    SnapshotRepository,
    TradeRepository,
)
from src.persistence.models import HistoricalDataPoint


# Default time windows for dashboard views.
# These are UI defaults chosen for typical dashboard use cases:
# - 365 days: Shows ~1 year of market history, good balance of context vs load time
# - 30 days: Recent regime activity, aligns with monthly review cycles
DEFAULT_HISTORICAL_DAYS = 365
DEFAULT_REGIME_DAYS = 30


class DashboardDataProvider:
    """Provides data for dashboard visualizations.

    Aggregates data from multiple repositories and provides methods
    tailored for dashboard display needs.
    """

    def __init__(self, db: Database) -> None:
        """Initialize with database connection.

        Args:
            db: Database instance (must be initialized).
        """
        self.db = db
        self.historical_repo = HistoricalDataRepository(db)
        self.position_repo = PositionRepository(db)
        self.contract_repo = PositionContractRepository(db)
        self.snapshot_repo = SnapshotRepository(db)
        self.trade_repo = TradeRepository(db)

    def get_historical_data(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[HistoricalDataPoint]:
        """Get historical BTC price and DVOL data.

        Args:
            start: Start datetime. Defaults to 365 days ago.
            end: End datetime. Defaults to now.

        Returns:
            List of HistoricalDataPoint sorted by timestamp.
        """
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=DEFAULT_HISTORICAL_DAYS)
        if end is None:
            end = datetime.now(timezone.utc)
        return self.historical_repo.get_range(start, end)

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Get currently open positions as dictionaries.

        Aggregates Greeks from position contracts if position Greeks are not set.

        Returns:
            List of position dictionaries with relevant fields for display.
        """
        positions = self.position_repo.get_open()
        result = []

        for p in positions:
            # Get Greeks from position, or aggregate from contracts
            delta = p.delta
            gamma = p.gamma
            theta = p.theta
            vega = p.vega

            # If position Greeks are None, aggregate from contracts
            if delta is None or gamma is None:
                contracts = self.contract_repo.get_by_strategy_id(p.strategy_id)
                if contracts:
                    delta = sum(c.delta or 0 for c in contracts)
                    gamma = sum(c.gamma or 0 for c in contracts)
                    theta = sum(c.theta or 0 for c in contracts)
                    vega = sum(c.vega or 0 for c in contracts)

            result.append({
                "strategy_id": p.strategy_id,
                "strategy_type": p.strategy_type,
                "entry_price": p.entry_price,
                "current_pnl": p.current_pnl,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "opened_at": p.opened_at,
            })

        return result

    def get_latest_market_state(self) -> dict[str, Any] | None:
        """Get latest market snapshot.

        Returns:
            Dictionary with market state or None if no snapshots exist.
        """
        snapshot = self.snapshot_repo.get_latest()
        if snapshot:
            return {
                "btc_price": snapshot.btc_price,
                "dvol": snapshot.dvol,
                "iv_rank": snapshot.iv_rank,
                "regime": snapshot.regime,
                "timestamp": snapshot.timestamp,
            }
        return None

    def get_regime_distribution(
        self,
        start: datetime | None = None,
    ) -> dict[str, int]:
        """Get count of snapshots per regime.

        Args:
            start: Start datetime. Defaults to 30 days ago.

        Returns:
            Dictionary mapping regime name to count.
        """
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=DEFAULT_REGIME_DAYS)

        snapshots = self.snapshot_repo.get_since(start)
        distribution: dict[str, int] = {}
        for s in snapshots:
            regime = s.regime or "unknown"
            distribution[regime] = distribution.get(regime, 0) + 1
        return distribution

    def get_historical_data_count(self) -> int:
        """Get total number of historical data points.

        Returns:
            Count of historical data records.
        """
        return self.historical_repo.count()

    def get_historical_date_range(self) -> tuple[datetime | None, datetime | None]:
        """Get the date range of historical data.

        Uses efficient SQL MIN/MAX query instead of loading all records.

        Returns:
            Tuple of (earliest_timestamp, latest_timestamp) or (None, None) if empty.
        """
        return self.historical_repo.get_date_bounds()

    def get_closed_positions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get closed positions as dictionaries.

        Args:
            limit: Maximum number of positions to return.

        Returns:
            List of position dictionaries with relevant fields for display.
        """
        positions = self.position_repo.get_closed(limit)
        return [
            {
                "id": p.id,
                "strategy_id": p.strategy_id,
                "strategy_type": p.strategy_type,
                "status": p.status.value,
                "entry_price": p.entry_price,
                "pnl": p.current_pnl,
                "close_reason": p.close_reason,
                "opened_at": p.opened_at,
                "closed_at": p.closed_at,
                "duration_days": (p.closed_at - p.opened_at).days if p.closed_at else None,
            }
            for p in positions
        ]

    def get_trade_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get trade history as dictionaries.

        Args:
            limit: Maximum number of trades to return.

        Returns:
            List of trade dictionaries with relevant fields for display.
        """
        trades = self.trade_repo.get_all(limit)
        return [
            {
                "id": t.id,
                "strategy_id": t.strategy_id,
                "strategy_type": t.strategy_type,
                "instrument": t.instrument,
                "side": t.side.value,
                "quantity": t.quantity,
                "price": t.price,
                "fees": t.fees,
                "status": t.status.value,
                "pnl": t.pnl,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in trades
        ]

    def get_trade_stats(self) -> dict[str, Any]:
        """Get trading statistics summary.

        Returns:
            Dictionary with trading statistics.
        """
        positions = self.position_repo.get_closed(limit=1000)

        if not positions:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "avg_duration_days": 0.0,
                "by_strategy": {},
            }

        pnls = [p.current_pnl or 0.0 for p in positions]
        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p < 0]

        durations = [
            (p.closed_at - p.opened_at).days
            for p in positions
            if p.closed_at
        ]

        # Group by strategy type
        by_strategy: dict[str, dict[str, float]] = {}
        for p in positions:
            st = p.strategy_type
            if st not in by_strategy:
                by_strategy[st] = {"count": 0, "pnl": 0.0, "wins": 0}
            by_strategy[st]["count"] += 1
            by_strategy[st]["pnl"] += p.current_pnl or 0.0
            if (p.current_pnl or 0) > 0:
                by_strategy[st]["wins"] += 1

        return {
            "total_trades": len(positions),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(positions) if positions else 0.0,
            "total_pnl": sum(pnls),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
            "avg_duration_days": sum(durations) / len(durations) if durations else 0.0,
            "by_strategy": by_strategy,
        }

    def get_position_count(self) -> dict[str, int]:
        """Get position counts.

        Returns:
            Dictionary with open and closed position counts.
        """
        return {
            "open": len(self.position_repo.get_open()),
            "closed": self.position_repo.count_closed(),
            "total": self.position_repo.count(),
        }

    def get_trade_count(self) -> int:
        """Get total trade count.

        Returns:
            Number of trades in database.
        """
        return self.trade_repo.count()
