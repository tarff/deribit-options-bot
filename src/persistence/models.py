"""Data models for the trading bot."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

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
    side: TradeSide
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
    iv_rank: Optional[float] = Field(default=None, ge=0)
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
    severity: Literal["info", "warning", "critical"]
    message: Optional[str] = None
    action_taken: Optional[str] = None
    timestamp: datetime


class HistoricalDataPoint(BaseModel):
    """Historical market data point for backtesting and analysis."""

    id: Optional[int] = None
    timestamp: datetime
    btc_price: float = Field(gt=0)
    btc_open: float = Field(gt=0)
    btc_high: float = Field(gt=0)
    btc_low: float = Field(gt=0)
    btc_volume: float = Field(ge=0)
    dvol: float = Field(gt=0)
    dvol_open: float = Field(gt=0)
    dvol_high: float = Field(gt=0)
    dvol_low: float = Field(gt=0)


class PositionContract(BaseModel):
    """Option contract leg within a position."""

    id: Optional[int] = None
    strategy_id: str
    instrument_name: str
    strike: float
    expiry: datetime
    option_type: str  # 'call' or 'put'
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mark_price: Optional[float] = None
    quantity: float = 1.0
    direction: str = "long"  # 'long' or 'short'


class PaperTradingState(BaseModel):
    """Paper trading state for persistence across restarts."""

    id: int = 1  # Single row table
    capital: float = Field(ge=0.0)
    peak_capital: float = Field(ge=0.0)
    daily_pnl: float = 0.0
    current_day: Optional[datetime] = None
    updated_at: Optional[datetime] = None
