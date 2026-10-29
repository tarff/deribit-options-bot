"""Data models for the live dashboard."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class LiveMarketData:
    """Live market data for dashboard display.

    Attributes:
        btc_price: Current underlying spot price (USD).
        dvol: Deribit Volatility Index.
        iv_rank: IV Rank (0-1).
        regime: Current market regime string.
        timestamp: When data was fetched.
    """

    btc_price: float
    dvol: Optional[float]
    iv_rank: Optional[float]
    regime: str
    timestamp: datetime


@dataclass
class LivePosition:
    """Live position data with Greeks.

    Attributes:
        instrument: Instrument name (e.g., BTC-28MAR25-80000-C).
        size: Position size (positive=long, negative=short).
        direction: Position direction (buy/sell).
        average_price: Average entry price.
        mark_price: Current mark price.
        pnl: Unrealized P&L in USD.
        delta: Position delta.
        gamma: Position gamma.
        theta: Position theta (daily).
        vega: Position vega.
    """

    instrument: str
    size: float
    direction: str
    average_price: float
    mark_price: float
    pnl: float
    delta: float
    gamma: float
    theta: float
    vega: float


@dataclass
class AccountInfo:
    """Account summary information.

    Values are in the account's settlement currency:
    - Inverse accounts: values in crypto (BTC/ETH)
    - Linear (USDC) accounts: values already in USD

    Attributes:
        equity: Total account equity (crypto or USDC).
        balance: Available balance (crypto or USDC).
        margin_balance: Margin balance (crypto or USDC).
        initial_margin: Initial margin used.
        maintenance_margin: Maintenance margin required.
        equity_usd: Equity in USD (same as equity for USDC accounts).
    """

    equity: float
    balance: float
    margin_balance: float
    initial_margin: float
    maintenance_margin: float
    equity_usd: Optional[float] = None
