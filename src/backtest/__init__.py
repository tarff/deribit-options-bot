"""Backtesting framework."""

from src.backtest.data_fetcher import HistoricalBar, HistoricalDataFetcher
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.backtest.option_chain_generator import (
    SyntheticChainConfig,
    SyntheticOptionChainGenerator,
)
from src.backtest.position_tracker import BacktestPosition, ClosedTrade, PositionTracker

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestPosition",
    "BacktestResult",
    "ClosedTrade",
    "HistoricalBar",
    "HistoricalDataFetcher",
    "PositionTracker",
    "SyntheticChainConfig",
    "SyntheticOptionChainGenerator",
]
