# Phase 3: Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement four trading strategies (Wheel, Iron Condor, Volatility Arbitrage, Gamma Scalping) with a unified interface and strategy selection system.

**Architecture:** Each strategy implements a common base interface with `evaluate()` returning signals and `manage()` handling position management. A StrategySelector maps regimes to strategies. Option selection helpers find appropriate strikes/expiries from the order book.

**Tech Stack:** Python 3.11+, Pydantic, async/await, dataclasses, existing DeribitClient

---

## Overview

| Task | Component | Description |
|------|-----------|-------------|
| 1 | Signal Models | Trade signal and option contract data structures |
| 2 | Option Selector | Helper to find strikes by delta/expiry |
| 3 | Base Strategy | Abstract interface for all strategies |
| 4 | Strategy Selector | Regime → Strategy mapping |
| 5 | Wheel Strategy | CSP → covered call cycle |
| 6 | Iron Condor Strategy | 4-leg defined risk spread |
| 7 | Volatility Arbitrage | ATM straddle with delta hedge signals |
| 8 | Gamma Scalping | Long straddle with scalp signals |
| 9 | Strategy Integration Tests | End-to-end tests with mocked data |
| 10 | Final Verification | Tests, mypy, ruff, coverage |

**Suggested Batches:**
- Batch 1: Tasks 1-4 (Foundation: signals, option selector, base strategy, selector)
- Batch 2: Tasks 5-6 (Yield strategies: Wheel, Iron Condor)
- Batch 3: Tasks 7-8 (Alpha strategies: Vol Arb, Gamma Scalp)
- Batch 4: Tasks 9-10 (Integration tests, final verification)

---

## Task 1: Signal Models

**Files:**
- Create: `src/brain/signal.py`
- Create: `tests/unit/test_signal.py`

### Step 1: Write the failing test

```python
"""Tests for trading signal models."""

import pytest
from datetime import datetime, timezone

from src.brain.signal import (
    OptionContract,
    TradeSignal,
    SignalAction,
    StrategyType,
)


def test_option_contract_creation() -> None:
    """Test OptionContract with all fields."""
    contract = OptionContract(
        instrument_name="BTC-31JAN26-95000-P",
        strike=95000.0,
        expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        gamma=0.00012,
        theta=-45.0,
        vega=120.0,
        iv=52.3,
        bid=0.0320,
        ask=0.0340,
        mark_price=0.0330,
    )

    assert contract.strike == 95000.0
    assert contract.option_type == "put"
    assert contract.delta == -0.25


def test_option_contract_mid_price() -> None:
    """Test mid price calculation."""
    contract = OptionContract(
        instrument_name="BTC-31JAN26-95000-P",
        strike=95000.0,
        expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        bid=0.0320,
        ask=0.0340,
    )

    assert contract.mid_price == pytest.approx(0.0330, abs=0.0001)


def test_trade_signal_creation() -> None:
    """Test TradeSignal for opening a position."""
    signal = TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-95000-P",
                strike=95000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0320,
                ask=0.0340,
            )
        ],
        direction="sell",
        quantity=0.1,
        reason="IV Rank 67%, regime NEUTRAL, wheel entry",
    )

    assert signal.strategy_type == StrategyType.WHEEL
    assert signal.action == SignalAction.OPEN
    assert len(signal.contracts) == 1


def test_trade_signal_total_premium() -> None:
    """Test premium calculation for multi-leg signal."""
    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0150,
                ask=0.0170,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-88000-P",
                strike=88000.0,
                expiry=datetime(2026, 1, 31, 8, 0, tzinfo=timezone.utc),
                option_type="put",
                bid=0.0050,
                ask=0.0060,
            ),
        ],
        direction="sell",
        quantity=0.1,
        legs_direction=["sell", "buy"],  # Sell 92k, buy 88k
        reason="Iron condor put spread",
    )

    # Net credit = sell 92k (0.016 mid) - buy 88k (0.0055 mid) = 0.0105
    assert signal.net_premium is not None
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_signal.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.brain.signal'"

### Step 3: Write minimal implementation

```python
"""Trading signal models for strategy execution."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalAction(str, Enum):
    """Action type for a trade signal."""

    OPEN = "open"
    CLOSE = "close"
    ADJUST = "adjust"
    HEDGE = "hedge"


class StrategyType(str, Enum):
    """Strategy types."""

    WHEEL = "wheel"
    IRON_CONDOR = "iron_condor"
    VOL_ARB = "vol_arb"
    GAMMA_SCALP = "gamma_scalp"


@dataclass
class OptionContract:
    """Option contract details from order book.

    Attributes:
        instrument_name: Deribit instrument name (e.g., BTC-31JAN26-95000-P).
        strike: Strike price in USD.
        expiry: Expiration datetime (UTC).
        option_type: 'call' or 'put'.
        delta: Option delta (-1 to 1).
        gamma: Option gamma.
        theta: Option theta (daily decay).
        vega: Option vega.
        iv: Implied volatility (percentage).
        bid: Best bid price (BTC).
        ask: Best ask price (BTC).
        mark_price: Mark price (BTC).
    """

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

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate mid price from bid/ask."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.mark_price


@dataclass
class TradeSignal:
    """Signal to execute a trade.

    Attributes:
        strategy_type: Which strategy generated this signal.
        action: OPEN, CLOSE, ADJUST, or HEDGE.
        contracts: List of option contracts involved.
        direction: Overall direction ('buy' or 'sell').
        quantity: Position size in BTC.
        legs_direction: Per-leg direction for multi-leg strategies.
        reason: Human-readable reason for signal.
        target_delta: Target delta for hedging signals.
        max_loss: Maximum loss for the position.
        max_profit: Maximum profit for the position.
    """

    strategy_type: StrategyType
    action: SignalAction
    contracts: list[OptionContract]
    direction: str  # 'buy' or 'sell' overall
    quantity: float
    legs_direction: Optional[list[str]] = None
    reason: str = ""
    target_delta: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None

    @property
    def net_premium(self) -> Optional[float]:
        """Calculate net premium for the signal.

        Positive = credit received, Negative = debit paid.
        """
        if not self.contracts:
            return None

        directions = self.legs_direction or [self.direction] * len(self.contracts)

        total = 0.0
        for contract, leg_dir in zip(self.contracts, directions):
            mid = contract.mid_price
            if mid is None:
                return None
            if leg_dir == "sell":
                total += mid
            else:
                total -= mid

        return total
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_signal.py -v`
Expected: PASS (4 tests)

### Step 5: Commit

```bash
git add src/brain/signal.py tests/unit/test_signal.py
git commit -m "feat: add signal models for strategy execution"
```

---

## Task 2: Option Selector

**Files:**
- Create: `src/data/option_selector.py`
- Create: `tests/unit/test_option_selector.py`

### Step 1: Write the failing test

```python
"""Tests for option selection helpers."""

import pytest
from datetime import datetime, timezone, timedelta

from src.data.option_selector import OptionSelector
from src.brain.signal import OptionContract


@pytest.fixture
def sample_options() -> list[OptionContract]:
    """Create sample option chain for testing."""
    base_expiry = datetime.now(timezone.utc) + timedelta(days=30)

    return [
        # Puts at various strikes
        OptionContract(
            instrument_name="BTC-30JAN26-90000-P",
            strike=90000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.15,
            bid=0.0080,
            ask=0.0090,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-92000-P",
            strike=92000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.20,
            bid=0.0120,
            ask=0.0135,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-95000-P",
            strike=95000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.30,
            bid=0.0200,
            ask=0.0220,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-97000-P",
            strike=97000.0,
            expiry=base_expiry,
            option_type="put",
            delta=-0.45,
            bid=0.0350,
            ask=0.0380,
        ),
        # Calls at various strikes
        OptionContract(
            instrument_name="BTC-30JAN26-100000-C",
            strike=100000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.45,
            bid=0.0340,
            ask=0.0370,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-103000-C",
            strike=103000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.30,
            bid=0.0180,
            ask=0.0200,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-105000-C",
            strike=105000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.20,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-30JAN26-108000-C",
            strike=108000.0,
            expiry=base_expiry,
            option_type="call",
            delta=0.12,
            bid=0.0050,
            ask=0.0060,
        ),
    ]


def test_find_put_by_delta(sample_options: list[OptionContract]) -> None:
    """Test finding put option by target delta."""
    selector = OptionSelector(sample_options)

    # Find put with delta closest to -0.25
    put = selector.find_by_delta(target_delta=-0.25, option_type="put")

    assert put is not None
    assert put.option_type == "put"
    # Should find the -0.20 or -0.30 delta put
    assert put.delta is not None
    assert -0.35 <= put.delta <= -0.15


def test_find_call_by_delta(sample_options: list[OptionContract]) -> None:
    """Test finding call option by target delta."""
    selector = OptionSelector(sample_options)

    # Find call with delta closest to 0.25
    call = selector.find_by_delta(target_delta=0.25, option_type="call")

    assert call is not None
    assert call.option_type == "call"
    assert call.delta is not None
    assert 0.15 <= call.delta <= 0.35


def test_find_atm_straddle(sample_options: list[OptionContract]) -> None:
    """Test finding ATM put and call for straddle."""
    selector = OptionSelector(sample_options)

    # Find ATM options (delta ~0.50)
    put = selector.find_by_delta(target_delta=-0.50, option_type="put")
    call = selector.find_by_delta(target_delta=0.50, option_type="call")

    assert put is not None
    assert call is not None
    # Should be closest to ATM
    assert abs(put.delta or 0) >= 0.40
    assert abs(call.delta or 0) >= 0.40


def test_find_protective_wing(sample_options: list[OptionContract]) -> None:
    """Test finding OTM option for protection."""
    selector = OptionSelector(sample_options)

    # Find far OTM put (delta ~-0.10)
    wing = selector.find_by_delta(target_delta=-0.10, option_type="put")

    assert wing is not None
    assert wing.option_type == "put"
    # Should be the most OTM put


def test_filter_by_dte(sample_options: list[OptionContract]) -> None:
    """Test filtering options by days to expiry."""
    # Add some options with different expiries
    near_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    far_expiry = datetime.now(timezone.utc) + timedelta(days=60)

    mixed_options = sample_options + [
        OptionContract(
            instrument_name="BTC-7JAN26-95000-P",
            strike=95000.0,
            expiry=near_expiry,
            option_type="put",
            delta=-0.30,
            bid=0.0100,
            ask=0.0110,
        ),
        OptionContract(
            instrument_name="BTC-15MAR26-95000-P",
            strike=95000.0,
            expiry=far_expiry,
            option_type="put",
            delta=-0.35,
            bid=0.0400,
            ask=0.0420,
        ),
    ]

    selector = OptionSelector(mixed_options)

    # Filter for 20-40 DTE
    filtered = selector.filter_by_dte(min_dte=20, max_dte=40)

    assert len(filtered.options) == len(sample_options)  # Only the 30 DTE options


def test_find_returns_none_if_no_match(sample_options: list[OptionContract]) -> None:
    """Test returns None when no options match criteria."""
    selector = OptionSelector(sample_options)

    # Try to find a put with very low delta (doesn't exist)
    result = selector.find_by_delta(target_delta=-0.01, option_type="put")

    # Should return closest match or None depending on threshold
    # With our sample, should return the -0.15 delta put as closest
    assert result is None or (result.delta is not None and result.delta > -0.10)
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_option_selector.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.data.option_selector'"

### Step 3: Write minimal implementation

```python
"""Option selection helpers for finding appropriate strikes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.brain.signal import OptionContract


@dataclass
class OptionSelector:
    """Helper for selecting options from a chain.

    Filters and finds options by delta, strike, DTE, etc.
    """

    options: list[OptionContract]

    def find_by_delta(
        self,
        target_delta: float,
        option_type: str,
        max_delta_diff: float = 0.10,
    ) -> Optional[OptionContract]:
        """Find option closest to target delta.

        Args:
            target_delta: Target delta (negative for puts, positive for calls).
            option_type: 'put' or 'call'.
            max_delta_diff: Maximum allowed difference from target.

        Returns:
            Option closest to target delta, or None if none within threshold.
        """
        candidates = [
            opt for opt in self.options
            if opt.option_type == option_type and opt.delta is not None
        ]

        if not candidates:
            return None

        # Sort by distance from target delta
        candidates.sort(key=lambda o: abs((o.delta or 0) - target_delta))

        best = candidates[0]
        if abs((best.delta or 0) - target_delta) <= max_delta_diff:
            return best

        return None

    def find_by_strike(
        self,
        target_strike: float,
        option_type: str,
    ) -> Optional[OptionContract]:
        """Find option at exact strike.

        Args:
            target_strike: Target strike price.
            option_type: 'put' or 'call'.

        Returns:
            Option at strike, or None if not found.
        """
        for opt in self.options:
            if opt.option_type == option_type and opt.strike == target_strike:
                return opt
        return None

    def find_strike_near_price(
        self,
        price: float,
        option_type: str,
        otm_percent: float = 0.0,
    ) -> Optional[OptionContract]:
        """Find option with strike at specified OTM percentage.

        Args:
            price: Current underlying price.
            option_type: 'put' or 'call'.
            otm_percent: How far OTM (e.g., 0.05 = 5% OTM).

        Returns:
            Closest option to target strike.
        """
        if option_type == "put":
            target_strike = price * (1 - otm_percent)
        else:
            target_strike = price * (1 + otm_percent)

        candidates = [
            opt for opt in self.options
            if opt.option_type == option_type
        ]

        if not candidates:
            return None

        # Find closest to target strike
        candidates.sort(key=lambda o: abs(o.strike - target_strike))
        return candidates[0]

    def filter_by_dte(
        self,
        min_dte: int = 0,
        max_dte: int = 365,
    ) -> "OptionSelector":
        """Filter options by days to expiry.

        Args:
            min_dte: Minimum days to expiry.
            max_dte: Maximum days to expiry.

        Returns:
            New OptionSelector with filtered options.
        """
        now = datetime.now(timezone.utc)

        filtered = []
        for opt in self.options:
            dte = (opt.expiry - now).days
            if min_dte <= dte <= max_dte:
                filtered.append(opt)

        return OptionSelector(filtered)

    def filter_by_type(self, option_type: str) -> "OptionSelector":
        """Filter options by type (put/call).

        Args:
            option_type: 'put' or 'call'.

        Returns:
            New OptionSelector with filtered options.
        """
        filtered = [opt for opt in self.options if opt.option_type == option_type]
        return OptionSelector(filtered)

    def get_puts(self) -> list[OptionContract]:
        """Get all put options sorted by strike descending."""
        puts = [opt for opt in self.options if opt.option_type == "put"]
        puts.sort(key=lambda o: o.strike, reverse=True)
        return puts

    def get_calls(self) -> list[OptionContract]:
        """Get all call options sorted by strike ascending."""
        calls = [opt for opt in self.options if opt.option_type == "call"]
        calls.sort(key=lambda o: o.strike)
        return calls
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_option_selector.py -v`
Expected: PASS (6 tests)

### Step 5: Commit

```bash
git add src/data/option_selector.py tests/unit/test_option_selector.py
git commit -m "feat: add option selector for finding strikes by delta"
```

---

## Task 3: Base Strategy Interface

**Files:**
- Create: `src/strategies/__init__.py`
- Create: `src/strategies/base.py`
- Create: `tests/unit/test_strategy_base.py`

### Step 1: Write the failing test

```python
"""Tests for base strategy interface."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.strategies.base import BaseStrategy, StrategyConfig, StrategyState
from src.brain.signal import TradeSignal, SignalAction, StrategyType
from src.data.market_metrics import MarketMetrics


class MockStrategy(BaseStrategy):
    """Concrete implementation for testing."""

    def __init__(self, config: StrategyConfig) -> None:
        super().__init__(config)
        self._should_signal = False
        self._signal: TradeSignal | None = None

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.WHEEL

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list,
    ) -> TradeSignal | None:
        if self._should_signal:
            return self._signal
        return None

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list,
    ) -> TradeSignal | None:
        return None

    def set_signal(self, signal: TradeSignal) -> None:
        self._should_signal = True
        self._signal = signal


def test_strategy_config_defaults() -> None:
    """Test StrategyConfig with defaults."""
    config = StrategyConfig(
        name="test_strategy",
        enabled=True,
    )

    assert config.max_position_size == 0.10
    assert config.target_dte_min == 30
    assert config.target_dte_max == 45
    assert config.profit_target == 0.50


def test_strategy_config_custom() -> None:
    """Test StrategyConfig with custom values."""
    config = StrategyConfig(
        name="iron_condor",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=21,
        target_dte_max=35,
        profit_target=0.40,
    )

    assert config.max_position_size == 0.05
    assert config.target_dte_min == 21


def test_strategy_state_initial() -> None:
    """Test StrategyState initial values."""
    state = StrategyState()

    assert state.is_active is False
    assert state.position_id is None
    assert state.entry_time is None


def test_base_strategy_initialization() -> None:
    """Test BaseStrategy initialization."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)

    assert strategy.config.name == "test"
    assert strategy.state.is_active is False


@pytest.mark.asyncio
async def test_base_strategy_can_open_when_inactive() -> None:
    """Test can_open returns True when no position."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)

    assert strategy.can_open() is True


@pytest.mark.asyncio
async def test_base_strategy_cannot_open_when_active() -> None:
    """Test can_open returns False when position exists."""
    config = StrategyConfig(name="test", enabled=True)
    strategy = MockStrategy(config)
    strategy.state.is_active = True
    strategy.state.position_id = "test-123"

    assert strategy.can_open() is False


@pytest.mark.asyncio
async def test_base_strategy_cannot_open_when_disabled() -> None:
    """Test can_open returns False when strategy disabled."""
    config = StrategyConfig(name="test", enabled=False)
    strategy = MockStrategy(config)

    assert strategy.can_open() is False
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_strategy_base.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategies'"

### Step 3: Write minimal implementation

Create `src/strategies/__init__.py`:

```python
"""Strategies package for trading strategy implementations."""
```

Create `src/strategies/base.py`:

```python
"""Base strategy interface and common components."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.brain.signal import TradeSignal, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@dataclass
class StrategyConfig:
    """Configuration for a strategy.

    Attributes:
        name: Strategy identifier.
        enabled: Whether strategy is active.
        max_position_size: Maximum position size as fraction of capital.
        target_dte_min: Minimum days to expiry for entries.
        target_dte_max: Maximum days to expiry for entries.
        profit_target: Close at this fraction of max profit (e.g., 0.50).
        loss_limit: Close at this fraction of max loss (e.g., 2.0 = 200%).
        target_delta: Target delta for option selection.
    """

    name: str
    enabled: bool
    max_position_size: float = 0.10
    target_dte_min: int = 30
    target_dte_max: int = 45
    profit_target: float = 0.50
    loss_limit: float = 2.0
    target_delta: float = 0.25


@dataclass
class StrategyState:
    """Runtime state for a strategy instance.

    Attributes:
        is_active: Whether strategy has an open position.
        position_id: ID of current position (if active).
        phase: Current phase (strategy-specific, e.g., 'csp', 'covered_call').
        entry_time: When position was opened.
        entry_price: Underlying price at entry.
        premium_received: Total premium collected.
        current_pnl: Current unrealized P&L.
        contracts: Active option contracts.
    """

    is_active: bool = False
    position_id: Optional[str] = None
    phase: Optional[str] = None
    entry_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    premium_received: float = 0.0
    current_pnl: float = 0.0
    contracts: list[OptionContract] = field(default_factory=list)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Strategies implement two main methods:
    - evaluate(): Check for new entry signals when no position exists
    - manage(): Check for exit/adjustment signals when position is open
    """

    def __init__(self, config: StrategyConfig) -> None:
        """Initialize strategy with configuration.

        Args:
            config: Strategy configuration.
        """
        self.config = config
        self.state = StrategyState()

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        """Return the strategy type enum value."""
        pass

    @abstractmethod
    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate market for entry signals.

        Called when strategy has no open position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            TradeSignal to open position, or None.
        """
        pass

    @abstractmethod
    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing position.

        Called when strategy has an open position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            TradeSignal to close/adjust, or None.
        """
        pass

    def can_open(self) -> bool:
        """Check if strategy can open a new position.

        Returns:
            True if enabled and no active position.
        """
        return self.config.enabled and not self.state.is_active

    def activate(self, position_id: str, entry_price: float, phase: str = "") -> None:
        """Mark strategy as having an active position.

        Args:
            position_id: Unique position identifier.
            entry_price: Underlying price at entry.
            phase: Initial phase (optional).
        """
        self.state.is_active = True
        self.state.position_id = position_id
        self.state.entry_time = datetime.now()
        self.state.entry_price = entry_price
        self.state.phase = phase

    def deactivate(self) -> None:
        """Mark strategy as having no active position."""
        self.state = StrategyState()

    def update_pnl(self, current_pnl: float) -> None:
        """Update current P&L.

        Args:
            current_pnl: Current unrealized P&L.
        """
        self.state.current_pnl = current_pnl
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_strategy_base.py -v`
Expected: PASS (7 tests)

### Step 5: Commit

```bash
git add src/strategies/__init__.py src/strategies/base.py tests/unit/test_strategy_base.py
git commit -m "feat: add base strategy interface with config and state"
```

---

## Task 4: Strategy Selector

**Files:**
- Create: `src/brain/strategy_selector.py`
- Create: `tests/unit/test_strategy_selector.py`

### Step 1: Write the failing test

```python
"""Tests for strategy selector."""

import pytest

from src.brain.strategy_selector import StrategySelector
from src.brain.regime_detector import MarketRegime
from src.brain.signal import StrategyType


def test_selector_returns_wheel_for_neutral() -> None:
    """Test Wheel strategy selected for NEUTRAL regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.NEUTRAL)

    assert result == StrategyType.WHEEL


def test_selector_returns_iron_condor_for_high_iv() -> None:
    """Test Iron Condor selected for HIGH_IV_OVERPRICED regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.HIGH_IV_OVERPRICED)

    assert result == StrategyType.IRON_CONDOR


def test_selector_returns_iron_condor_for_high_stress() -> None:
    """Test Iron Condor selected for HIGH_STRESS (defined risk only)."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.HIGH_STRESS)

    assert result == StrategyType.IRON_CONDOR


def test_selector_returns_gamma_scalp_for_low_iv() -> None:
    """Test Gamma Scalp selected for LOW_IV_UNDERPRICED regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.LOW_IV_UNDERPRICED)

    assert result == StrategyType.GAMMA_SCALP


def test_selector_returns_gamma_scalp_for_volatile_fair() -> None:
    """Test Gamma Scalp selected for VOLATILE_FAIR regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.VOLATILE_FAIR)

    assert result == StrategyType.GAMMA_SCALP


def test_selector_returns_none_for_extreme_fear() -> None:
    """Test no strategy for EXTREME_FEAR regime."""
    selector = StrategySelector()

    result = selector.select(MarketRegime.EXTREME_FEAR)

    assert result is None


def test_selector_get_allowed_strategies() -> None:
    """Test getting all allowed strategies for a regime."""
    selector = StrategySelector()

    # Neutral allows wheel and iron condor
    allowed = selector.get_allowed(MarketRegime.NEUTRAL)

    assert StrategyType.WHEEL in allowed
    # Iron condor also allowed as fallback


def test_selector_is_strategy_allowed() -> None:
    """Test checking if specific strategy is allowed."""
    selector = StrategySelector()

    # Wheel allowed in neutral
    assert selector.is_allowed(StrategyType.WHEEL, MarketRegime.NEUTRAL) is True

    # Wheel not allowed in extreme fear
    assert selector.is_allowed(StrategyType.WHEEL, MarketRegime.EXTREME_FEAR) is False

    # Gamma scalp allowed in low IV
    assert selector.is_allowed(StrategyType.GAMMA_SCALP, MarketRegime.LOW_IV_UNDERPRICED) is True
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_strategy_selector.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.brain.strategy_selector'"

### Step 3: Write minimal implementation

```python
"""Strategy selector based on market regime."""

from typing import Optional

from src.brain.regime_detector import MarketRegime
from src.brain.signal import StrategyType


class StrategySelector:
    """Maps market regimes to appropriate strategies.

    Strategy selection rules:
    - NEUTRAL: Wheel (steady yield)
    - HIGH_IV_OVERPRICED: Iron Condor (sell premium)
    - HIGH_STRESS: Iron Condor (defined risk only)
    - LOW_IV_UNDERPRICED: Gamma Scalp (buy cheap options)
    - VOLATILE_FAIR: Gamma Scalp (profit from oscillation)
    - EXTREME_FEAR: None (no trading)
    """

    # Primary strategy for each regime
    REGIME_TO_STRATEGY: dict[MarketRegime, Optional[StrategyType]] = {
        MarketRegime.NEUTRAL: StrategyType.WHEEL,
        MarketRegime.HIGH_IV_OVERPRICED: StrategyType.IRON_CONDOR,
        MarketRegime.HIGH_STRESS: StrategyType.IRON_CONDOR,
        MarketRegime.LOW_IV_UNDERPRICED: StrategyType.GAMMA_SCALP,
        MarketRegime.VOLATILE_FAIR: StrategyType.GAMMA_SCALP,
        MarketRegime.EXTREME_FEAR: None,
    }

    # All allowed strategies per regime (primary + alternatives)
    REGIME_ALLOWED: dict[MarketRegime, list[StrategyType]] = {
        MarketRegime.NEUTRAL: [StrategyType.WHEEL, StrategyType.IRON_CONDOR],
        MarketRegime.HIGH_IV_OVERPRICED: [StrategyType.IRON_CONDOR, StrategyType.VOL_ARB],
        MarketRegime.HIGH_STRESS: [StrategyType.IRON_CONDOR],
        MarketRegime.LOW_IV_UNDERPRICED: [StrategyType.GAMMA_SCALP, StrategyType.VOL_ARB],
        MarketRegime.VOLATILE_FAIR: [StrategyType.GAMMA_SCALP],
        MarketRegime.EXTREME_FEAR: [],
    }

    def select(self, regime: MarketRegime) -> Optional[StrategyType]:
        """Select primary strategy for regime.

        Args:
            regime: Current market regime.

        Returns:
            Recommended strategy type, or None if should not trade.
        """
        return self.REGIME_TO_STRATEGY.get(regime)

    def get_allowed(self, regime: MarketRegime) -> list[StrategyType]:
        """Get all allowed strategies for regime.

        Args:
            regime: Current market regime.

        Returns:
            List of allowed strategy types.
        """
        return self.REGIME_ALLOWED.get(regime, [])

    def is_allowed(self, strategy: StrategyType, regime: MarketRegime) -> bool:
        """Check if strategy is allowed in regime.

        Args:
            strategy: Strategy to check.
            regime: Current market regime.

        Returns:
            True if strategy is allowed.
        """
        return strategy in self.get_allowed(regime)
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_strategy_selector.py -v`
Expected: PASS (8 tests)

### Step 5: Commit

```bash
git add src/brain/strategy_selector.py tests/unit/test_strategy_selector.py
git commit -m "feat: add strategy selector mapping regimes to strategies"
```

---

## Task 5: Wheel Strategy

**Files:**
- Create: `src/strategies/wheel.py`
- Create: `tests/unit/test_wheel_strategy.py`

### Step 1: Write the failing test

```python
"""Tests for Wheel strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.wheel import WheelStrategy
from src.strategies.base import StrategyConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def wheel_config() -> StrategyConfig:
    """Create Wheel strategy config."""
    return StrategyConfig(
        name="wheel",
        enabled=True,
        max_position_size=0.10,
        target_dte_min=30,
        target_dte_max=45,
        profit_target=0.50,
        target_delta=0.25,
    )


@pytest.fixture
def sample_metrics() -> MarketMetrics:
    """Create sample market metrics."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        rv_30d=48.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create sample option chain."""
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    return [
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.18,
            iv=50.0,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,
            iv=51.0,
            bid=0.0150,
            ask=0.0165,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-95000-P",
            strike=95000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.35,
            iv=52.0,
            bid=0.0220,
            ask=0.0240,
        ),
        # Calls for covered call phase
        OptionContract(
            instrument_name="BTC-31JAN26-100000-C",
            strike=100000.0,
            expiry=expiry,
            option_type="call",
            delta=0.35,
            iv=52.0,
            bid=0.0200,
            ask=0.0220,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-103000-C",
            strike=103000.0,
            expiry=expiry,
            option_type="call",
            delta=0.25,
            iv=51.0,
            bid=0.0140,
            ask=0.0155,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-105000-C",
            strike=105000.0,
            expiry=expiry,
            option_type="call",
            delta=0.18,
            iv=50.0,
            bid=0.0090,
            ask=0.0105,
        ),
    ]


@pytest.mark.asyncio
async def test_wheel_evaluate_generates_csp_signal(
    wheel_config: StrategyConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel generates sell put signal when conditions met."""
    strategy = WheelStrategy(wheel_config)

    signal = await strategy.evaluate(sample_metrics, sample_option_chain)

    assert signal is not None
    assert signal.strategy_type == StrategyType.WHEEL
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "sell"
    assert len(signal.contracts) == 1
    assert signal.contracts[0].option_type == "put"
    # Should select put with delta closest to -0.25
    assert signal.contracts[0].delta is not None
    assert -0.30 <= signal.contracts[0].delta <= -0.20


@pytest.mark.asyncio
async def test_wheel_evaluate_requires_minimum_iv_rank(
    wheel_config: StrategyConfig,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel requires IV Rank > 30% for entry."""
    strategy = WheelStrategy(wheel_config)
    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=35.0,
        iv_rank=0.20,  # Below 30% threshold
        rv_30d=40.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_iv_metrics, sample_option_chain)

    assert signal is None


@pytest.mark.asyncio
async def test_wheel_manage_closes_at_profit_target(
    wheel_config: StrategyConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel closes position at 50% profit."""
    strategy = WheelStrategy(wheel_config)

    # Simulate active position
    strategy.state.is_active = True
    strategy.state.position_id = "wheel-001"
    strategy.state.phase = "csp"
    strategy.state.premium_received = 0.0160  # Entry premium
    strategy.state.contracts = [sample_option_chain[1]]  # 92k put

    # Current price is much lower (profitable)
    sample_option_chain[1].bid = 0.0070
    sample_option_chain[1].ask = 0.0080

    signal = await strategy.manage(sample_metrics, sample_option_chain)

    # Profit = 0.016 - 0.0075 = 0.0085 (53% of premium)
    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "profit" in signal.reason.lower()


@pytest.mark.asyncio
async def test_wheel_phase_transition_to_covered_call(
    wheel_config: StrategyConfig,
    sample_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Wheel transitions from CSP to covered call on assignment."""
    strategy = WheelStrategy(wheel_config)

    # Simulate assignment by setting phase to covered_call
    strategy.state.is_active = True
    strategy.state.position_id = "wheel-001"
    strategy.state.phase = "covered_call"
    strategy.state.entry_price = 92000.0  # Assignment price

    signal = await strategy.evaluate(sample_metrics, sample_option_chain)

    # Should generate sell call signal
    assert signal is not None
    assert signal.direction == "sell"
    assert len(signal.contracts) == 1
    assert signal.contracts[0].option_type == "call"


def test_wheel_strategy_type() -> None:
    """Test strategy type property."""
    config = StrategyConfig(name="wheel", enabled=True)
    strategy = WheelStrategy(config)

    assert strategy.strategy_type == StrategyType.WHEEL
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_wheel_strategy.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategies.wheel'"

### Step 3: Write minimal implementation

```python
"""Wheel strategy implementation.

The Wheel is a yield strategy that cycles between:
1. Selling cash-secured puts (CSP) until assigned
2. Selling covered calls on assigned shares until called away

Entry: IV Rank > 30%, NEUTRAL or HIGH_IV regime
Exit: 50% profit target, assignment, or regime shift
"""

from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector


class WheelStrategy(BaseStrategy):
    """Wheel strategy: CSP → Covered Call cycle.

    Phases:
    - 'csp': Selling cash-secured puts
    - 'covered_call': Selling covered calls after assignment
    """

    # Minimum IV Rank to enter (need decent premium)
    MIN_IV_RANK = 0.30

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.WHEEL

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry or phase transition signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open position or transition phase.
        """
        # If in covered call phase, generate sell call signal
        if self.state.is_active and self.state.phase == "covered_call":
            return self._generate_covered_call_signal(metrics, option_chain)

        # Otherwise, check for new CSP entry
        if not self.can_open():
            return None

        # Check IV conditions
        if metrics.iv_rank is None or metrics.iv_rank < self.MIN_IV_RANK:
            return None

        return self._generate_csp_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing position.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to close/adjust, or None.
        """
        if not self.state.is_active or not self.state.contracts:
            return None

        # Check profit target
        current_value = self._get_current_option_value(option_chain)
        if current_value is not None:
            profit_pct = (self.state.premium_received - current_value) / self.state.premium_received

            if profit_pct >= self.config.profit_target:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",  # Buy back the sold option
                    quantity=self.config.max_position_size,
                    reason=f"Profit target reached: {profit_pct:.1%} >= {self.config.profit_target:.1%}",
                )

        return None

    def _generate_csp_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate sell put signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to sell put, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
        )

        # Find put with target delta (~0.25 OTM)
        put = selector.find_by_delta(
            target_delta=-self.config.target_delta,
            option_type="put",
            max_delta_diff=0.10,
        )

        if put is None:
            return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[put],
            direction="sell",
            quantity=self.config.max_position_size,
            reason=f"Wheel CSP entry: IV Rank {metrics.iv_rank:.1%}, delta {put.delta}",
        )

    def _generate_covered_call_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate sell call signal for covered call phase.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to sell call, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
        )

        # Find call with target delta (~0.25 OTM)
        # Strike should be at or above entry price
        call = selector.find_by_delta(
            target_delta=self.config.target_delta,
            option_type="call",
            max_delta_diff=0.10,
        )

        if call is None:
            return None

        # Ensure strike is at or above assignment price
        if self.state.entry_price and call.strike < self.state.entry_price:
            # Find a call with higher strike
            call = selector.find_strike_near_price(
                price=self.state.entry_price,
                option_type="call",
                otm_percent=0.05,
            )
            if call is None:
                return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[call],
            direction="sell",
            quantity=self.config.max_position_size,
            reason=f"Wheel covered call: strike {call.strike}, delta {call.delta}",
        )

    def _get_current_option_value(
        self,
        option_chain: list[OptionContract],
    ) -> Optional[float]:
        """Get current value of held option.

        Args:
            option_chain: Current option chain.

        Returns:
            Current mid price of held option, or None.
        """
        if not self.state.contracts:
            return None

        held = self.state.contracts[0]
        selector = OptionSelector(option_chain)

        # Find same option in current chain
        current = selector.find_by_strike(held.strike, held.option_type)
        if current is None:
            return None

        return current.mid_price
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_wheel_strategy.py -v`
Expected: PASS (5 tests)

### Step 5: Commit

```bash
git add src/strategies/wheel.py tests/unit/test_wheel_strategy.py
git commit -m "feat: add Wheel strategy with CSP and covered call phases"
```

---

## Task 6: Iron Condor Strategy

**Files:**
- Create: `src/strategies/iron_condor.py`
- Create: `tests/unit/test_iron_condor_strategy.py`

### Step 1: Write the failing test

```python
"""Tests for Iron Condor strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.iron_condor import IronCondorStrategy, IronCondorConfig
from src.strategies.base import StrategyConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def ic_config() -> IronCondorConfig:
    """Create Iron Condor strategy config."""
    return IronCondorConfig(
        name="iron_condor",
        enabled=True,
        max_position_size=0.10,
        target_dte_min=30,
        target_dte_max=45,
        profit_target=0.50,
        short_delta=0.15,
        wing_width_pct=0.05,
    )


@pytest.fixture
def high_iv_metrics() -> MarketMetrics:
    """Create high IV market metrics."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=58.0,
        iv_rank=0.65,
        iv_rv_spread=12.0,
        rv_30d=46.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create sample option chain for iron condor."""
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    return [
        # Puts (from OTM to ATM)
        OptionContract(
            instrument_name="BTC-31JAN26-85000-P",
            strike=85000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
            bid=0.0020,
            ask=0.0025,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-88000-P",
            strike=88000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.08,
            bid=0.0040,
            ask=0.0050,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.12,
            bid=0.0070,
            ask=0.0085,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.16,
            bid=0.0110,
            ask=0.0125,
        ),
        # Calls (from ATM to OTM)
        OptionContract(
            instrument_name="BTC-31JAN26-102000-C",
            strike=102000.0,
            expiry=expiry,
            option_type="call",
            delta=0.16,
            bid=0.0100,
            ask=0.0115,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-105000-C",
            strike=105000.0,
            expiry=expiry,
            option_type="call",
            delta=0.10,
            bid=0.0060,
            ask=0.0072,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-108000-C",
            strike=108000.0,
            expiry=expiry,
            option_type="call",
            delta=0.06,
            bid=0.0030,
            ask=0.0040,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-110000-C",
            strike=110000.0,
            expiry=expiry,
            option_type="call",
            delta=0.04,
            bid=0.0018,
            ask=0.0025,
        ),
    ]


@pytest.mark.asyncio
async def test_iron_condor_generates_4_leg_signal(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor generates 4-leg signal."""
    strategy = IronCondorStrategy(ic_config)

    signal = await strategy.evaluate(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.strategy_type == StrategyType.IRON_CONDOR
    assert signal.action == SignalAction.OPEN
    assert len(signal.contracts) == 4
    assert signal.legs_direction is not None
    assert len(signal.legs_direction) == 4

    # Verify structure: sell put, buy put, sell call, buy call
    put_legs = [c for c in signal.contracts if c.option_type == "put"]
    call_legs = [c for c in signal.contracts if c.option_type == "call"]
    assert len(put_legs) == 2
    assert len(call_legs) == 2


@pytest.mark.asyncio
async def test_iron_condor_requires_high_iv_rank(
    ic_config: IronCondorConfig,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor requires IV Rank > 50%."""
    strategy = IronCondorStrategy(ic_config)
    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.35,  # Below 50%
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_iv_metrics, sample_option_chain)

    assert signal is None


@pytest.mark.asyncio
async def test_iron_condor_max_profit_and_loss(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor calculates max profit and loss."""
    strategy = IronCondorStrategy(ic_config)

    signal = await strategy.evaluate(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.max_profit is not None
    assert signal.max_profit > 0
    assert signal.max_loss is not None
    assert signal.max_loss > 0


@pytest.mark.asyncio
async def test_iron_condor_closes_at_profit_target(
    ic_config: IronCondorConfig,
    high_iv_metrics: MarketMetrics,
    sample_option_chain: list[OptionContract],
) -> None:
    """Test Iron Condor closes at 50% profit."""
    strategy = IronCondorStrategy(ic_config)

    # Set up active position
    strategy.state.is_active = True
    strategy.state.position_id = "ic-001"
    strategy.state.premium_received = 0.0100  # Net credit
    strategy.state.contracts = sample_option_chain[:4]

    # Simulate options decayed significantly
    for opt in sample_option_chain:
        opt.bid = (opt.bid or 0) * 0.4
        opt.ask = (opt.ask or 0) * 0.4

    signal = await strategy.manage(high_iv_metrics, sample_option_chain)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE


def test_iron_condor_strategy_type() -> None:
    """Test strategy type property."""
    config = IronCondorConfig(name="ic", enabled=True)
    strategy = IronCondorStrategy(config)

    assert strategy.strategy_type == StrategyType.IRON_CONDOR
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_iron_condor_strategy.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategies.iron_condor'"

### Step 3: Write minimal implementation

```python
"""Iron Condor strategy implementation.

Iron Condor is a defined-risk premium selling strategy:
- Sell OTM put spread (bull put spread)
- Sell OTM call spread (bear call spread)
- Profit from time decay when price stays in range

Entry: IV Rank > 50%, HIGH_IV_OVERPRICED or HIGH_STRESS regime
Exit: 50% profit, short strike breached, or DTE < 7
"""

from dataclasses import dataclass
from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector


@dataclass
class IronCondorConfig(StrategyConfig):
    """Configuration specific to Iron Condor strategy.

    Attributes:
        short_delta: Target delta for short strikes (default 0.15).
        wing_width_pct: Width between short and long strikes as % (default 0.05).
    """

    short_delta: float = 0.15
    wing_width_pct: float = 0.05


class IronCondorStrategy(BaseStrategy):
    """Iron Condor: Sell OTM put spread + call spread.

    Structure:
    - Buy OTM put (protection)
    - Sell OTM put (credit)
    - Sell OTM call (credit)
    - Buy OTM call (protection)
    """

    # Minimum IV Rank for entry
    MIN_IV_RANK = 0.50

    def __init__(self, config: IronCondorConfig) -> None:
        super().__init__(config)
        self.ic_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.IRON_CONDOR

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open iron condor, or None.
        """
        if not self.can_open():
            return None

        # Check IV conditions
        if metrics.iv_rank is None or metrics.iv_rank < self.MIN_IV_RANK:
            return None

        return self._generate_iron_condor_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage existing iron condor.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to close, or None.
        """
        if not self.state.is_active:
            return None

        # Check profit target
        current_value = self._get_current_spread_value(option_chain)
        if current_value is not None and self.state.premium_received > 0:
            profit_pct = (self.state.premium_received - current_value) / self.state.premium_received

            if profit_pct >= self.config.profit_target:
                return TradeSignal(
                    strategy_type=self.strategy_type,
                    action=SignalAction.CLOSE,
                    contracts=self.state.contracts,
                    direction="buy",
                    quantity=self.config.max_position_size,
                    legs_direction=["buy", "sell", "buy", "sell"],  # Reverse of open
                    reason=f"Profit target: {profit_pct:.1%}",
                )

        return None

    def _generate_iron_condor_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate 4-leg iron condor signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal with 4 contracts, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
        )

        # Find short put (delta ~ -0.15)
        short_put = selector.find_by_delta(
            target_delta=-self.ic_config.short_delta,
            option_type="put",
            max_delta_diff=0.05,
        )
        if short_put is None:
            return None

        # Find long put (further OTM, delta ~ -0.05)
        long_put = selector.find_by_delta(
            target_delta=-self.ic_config.short_delta + 0.10,
            option_type="put",
            max_delta_diff=0.05,
        )
        if long_put is None:
            return None

        # Find short call (delta ~ 0.15)
        short_call = selector.find_by_delta(
            target_delta=self.ic_config.short_delta,
            option_type="call",
            max_delta_diff=0.05,
        )
        if short_call is None:
            return None

        # Find long call (further OTM, delta ~ 0.05)
        long_call = selector.find_by_delta(
            target_delta=self.ic_config.short_delta - 0.10,
            option_type="call",
            max_delta_diff=0.05,
        )
        if long_call is None:
            return None

        contracts = [short_put, long_put, short_call, long_call]
        legs_direction = ["sell", "buy", "sell", "buy"]

        # Calculate max profit (net credit) and max loss
        net_credit = self._calculate_net_credit(contracts, legs_direction)
        max_loss = self._calculate_max_loss(contracts, net_credit)

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=contracts,
            direction="sell",
            quantity=self.config.max_position_size,
            legs_direction=legs_direction,
            reason=f"Iron condor: IV Rank {metrics.iv_rank:.1%}, short deltas ±{self.ic_config.short_delta}",
            max_profit=net_credit,
            max_loss=max_loss,
        )

    def _calculate_net_credit(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
    ) -> float:
        """Calculate net credit received.

        Args:
            contracts: The 4 contracts.
            legs_direction: Direction for each leg.

        Returns:
            Net credit (positive = credit).
        """
        total = 0.0
        for contract, direction in zip(contracts, legs_direction):
            mid = contract.mid_price or 0
            if direction == "sell":
                total += mid
            else:
                total -= mid
        return total

    def _calculate_max_loss(
        self,
        contracts: list[OptionContract],
        net_credit: float,
    ) -> float:
        """Calculate maximum loss.

        Max loss = width of widest spread - net credit

        Args:
            contracts: The 4 contracts.
            net_credit: Net credit received.

        Returns:
            Maximum loss.
        """
        # Put spread width
        put_width = abs(contracts[0].strike - contracts[1].strike)
        # Call spread width
        call_width = abs(contracts[3].strike - contracts[2].strike)

        max_spread_width = max(put_width, call_width)
        # Convert to BTC terms (approximate)
        width_in_btc = max_spread_width / contracts[0].strike

        return width_in_btc - net_credit

    def _get_current_spread_value(
        self,
        option_chain: list[OptionContract],
    ) -> Optional[float]:
        """Get current value of the spread.

        Args:
            option_chain: Current option chain.

        Returns:
            Current value to close the spread.
        """
        if len(self.state.contracts) != 4:
            return None

        selector = OptionSelector(option_chain)
        total = 0.0

        legs_direction = ["sell", "buy", "sell", "buy"]

        for contract, direction in zip(self.state.contracts, legs_direction):
            current = selector.find_by_strike(contract.strike, contract.option_type)
            if current is None:
                return None
            mid = current.mid_price or 0
            # To close: buy back what we sold, sell what we bought
            if direction == "sell":
                total += mid  # Cost to buy back
            else:
                total -= mid  # Credit from selling
        return total
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_iron_condor_strategy.py -v`
Expected: PASS (5 tests)

### Step 5: Commit

```bash
git add src/strategies/iron_condor.py tests/unit/test_iron_condor_strategy.py
git commit -m "feat: add Iron Condor strategy with 4-leg signal generation"
```

---

## Task 7: Volatility Arbitrage Strategy

**Files:**
- Create: `src/strategies/vol_arb.py`
- Create: `tests/unit/test_vol_arb_strategy.py`

### Step 1: Write the failing test

```python
"""Tests for Volatility Arbitrage strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.vol_arb import VolArbStrategy, VolArbConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def vol_arb_config() -> VolArbConfig:
    """Create Vol Arb strategy config."""
    return VolArbConfig(
        name="vol_arb",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=14,
        target_dte_max=30,
        profit_target=0.30,
        iv_rv_threshold_sell=15.0,
        iv_rv_threshold_buy=-10.0,
        delta_hedge_threshold=0.10,
    )


@pytest.fixture
def high_iv_spread_metrics() -> MarketMetrics:
    """Create metrics with high IV-RV spread (sell vol opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=60.0,
        iv_rank=0.70,
        iv_rv_spread=18.0,  # IV > RV by 18 points
        rv_30d=42.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def low_iv_spread_metrics() -> MarketMetrics:
    """Create metrics with low IV-RV spread (buy vol opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=38.0,
        iv_rank=0.20,
        iv_rv_spread=-12.0,  # IV < RV by 12 points
        rv_30d=50.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_atm_options() -> list[OptionContract]:
    """Create ATM options for straddle."""
    expiry = datetime.now(timezone.utc) + timedelta(days=21)
    return [
        OptionContract(
            instrument_name="BTC-21JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            gamma=0.00015,
            theta=-85.0,
            vega=150.0,
            iv=60.0,
            bid=0.0450,
            ask=0.0480,
        ),
        OptionContract(
            instrument_name="BTC-21JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.52,
            gamma=0.00015,
            theta=-85.0,
            vega=150.0,
            iv=60.0,
            bid=0.0440,
            ask=0.0470,
        ),
    ]


@pytest.mark.asyncio
async def test_vol_arb_sell_vol_signal(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb generates sell straddle when IV overpriced."""
    strategy = VolArbStrategy(vol_arb_config)

    signal = await strategy.evaluate(high_iv_spread_metrics, sample_atm_options)

    assert signal is not None
    assert signal.strategy_type == StrategyType.VOL_ARB
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "sell"
    assert len(signal.contracts) == 2  # Put + Call
    assert "sell" in signal.reason.lower()


@pytest.mark.asyncio
async def test_vol_arb_buy_vol_signal(
    vol_arb_config: VolArbConfig,
    low_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb generates buy straddle when IV underpriced."""
    strategy = VolArbStrategy(vol_arb_config)

    signal = await strategy.evaluate(low_iv_spread_metrics, sample_atm_options)

    assert signal is not None
    assert signal.direction == "buy"
    assert "buy" in signal.reason.lower()


@pytest.mark.asyncio
async def test_vol_arb_hedge_signal_when_delta_exceeds_threshold(
    vol_arb_config: VolArbConfig,
    high_iv_spread_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb generates hedge signal when delta too large."""
    strategy = VolArbStrategy(vol_arb_config)

    # Simulate active position with delta drift
    strategy.state.is_active = True
    strategy.state.position_id = "va-001"
    strategy.state.contracts = sample_atm_options

    # Price moved, delta is now 0.15 (exceeds 0.10 threshold)
    sample_atm_options[0].delta = -0.35  # Put delta increased
    sample_atm_options[1].delta = 0.50   # Call delta stayed

    signal = await strategy.manage(high_iv_spread_metrics, sample_atm_options)

    # Should generate hedge signal
    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.target_delta is not None


@pytest.mark.asyncio
async def test_vol_arb_no_signal_neutral_spread(
    vol_arb_config: VolArbConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Vol Arb no signal when IV-RV spread near zero."""
    strategy = VolArbStrategy(vol_arb_config)
    neutral_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        iv_rv_spread=3.0,  # Near zero
        rv_30d=47.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(neutral_metrics, sample_atm_options)

    assert signal is None


def test_vol_arb_strategy_type() -> None:
    """Test strategy type property."""
    config = VolArbConfig(name="va", enabled=True)
    strategy = VolArbStrategy(config)

    assert strategy.strategy_type == StrategyType.VOL_ARB
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_vol_arb_strategy.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategies.vol_arb'"

### Step 3: Write minimal implementation

```python
"""Volatility Arbitrage strategy implementation.

Vol Arb trades the IV-RV spread:
- Sell ATM straddle when IV >> RV (IV overpriced)
- Buy ATM straddle when IV << RV (IV underpriced)
- Delta hedge to remain neutral

Entry: |IV-RV spread| > threshold
Exit: Spread normalizes, profit target, or time limit
"""

from dataclasses import dataclass
from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector


@dataclass
class VolArbConfig(StrategyConfig):
    """Configuration specific to Vol Arb strategy.

    Attributes:
        iv_rv_threshold_sell: IV-RV spread above this → sell vol.
        iv_rv_threshold_buy: IV-RV spread below this → buy vol.
        delta_hedge_threshold: Rebalance when |delta| exceeds this.
    """

    iv_rv_threshold_sell: float = 15.0
    iv_rv_threshold_buy: float = -10.0
    delta_hedge_threshold: float = 0.10


class VolArbStrategy(BaseStrategy):
    """Volatility Arbitrage: Trade IV-RV spread with delta hedging.

    Modes:
    - 'sell_vol': Short ATM straddle (IV overpriced)
    - 'buy_vol': Long ATM straddle (IV underpriced)
    """

    def __init__(self, config: VolArbConfig) -> None:
        super().__init__(config)
        self.va_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.VOL_ARB

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal based on IV-RV spread.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to open straddle, or None.
        """
        if not self.can_open():
            return None

        if metrics.iv_rv_spread is None:
            return None

        # Check for sell vol opportunity
        if metrics.iv_rv_spread > self.va_config.iv_rv_threshold_sell:
            return self._generate_straddle_signal(metrics, option_chain, "sell")

        # Check for buy vol opportunity
        if metrics.iv_rv_spread < self.va_config.iv_rv_threshold_buy:
            return self._generate_straddle_signal(metrics, option_chain, "buy")

        return None

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage position - check for hedge or exit signals.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to hedge, close, or None.
        """
        if not self.state.is_active:
            return None

        # Calculate current portfolio delta
        portfolio_delta = self._calculate_portfolio_delta()

        # Check if hedge needed
        if abs(portfolio_delta) > self.va_config.delta_hedge_threshold:
            return TradeSignal(
                strategy_type=self.strategy_type,
                action=SignalAction.HEDGE,
                contracts=[],
                direction="sell" if portfolio_delta > 0 else "buy",
                quantity=abs(portfolio_delta),
                target_delta=0.0,
                reason=f"Delta hedge: portfolio delta {portfolio_delta:.3f}",
            )

        # Check if spread normalized (exit condition)
        if metrics.iv_rv_spread is not None:
            if self.state.phase == "sell_vol" and metrics.iv_rv_spread < 5:
                return self._generate_close_signal("IV-RV spread normalized")
            if self.state.phase == "buy_vol" and metrics.iv_rv_spread > -5:
                return self._generate_close_signal("IV-RV spread normalized")

        return None

    def _generate_straddle_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
        direction: str,
    ) -> Optional[TradeSignal]:
        """Generate ATM straddle signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.
            direction: 'buy' or 'sell'.

        Returns:
            Signal to open straddle, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for target DTE
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
        )

        # Find ATM put (delta ~ -0.50)
        atm_put = selector.find_by_delta(
            target_delta=-0.50,
            option_type="put",
            max_delta_diff=0.10,
        )
        if atm_put is None:
            return None

        # Find ATM call (delta ~ 0.50)
        atm_call = selector.find_by_delta(
            target_delta=0.50,
            option_type="call",
            max_delta_diff=0.10,
        )
        if atm_call is None:
            return None

        mode = "sell_vol" if direction == "sell" else "buy_vol"

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[atm_put, atm_call],
            direction=direction,
            quantity=self.config.max_position_size,
            legs_direction=[direction, direction],
            reason=f"Vol arb {direction}: IV-RV spread {metrics.iv_rv_spread:.1f}",
        )

    def _generate_close_signal(self, reason: str) -> TradeSignal:
        """Generate close signal.

        Args:
            reason: Reason for closing.

        Returns:
            Close signal.
        """
        close_direction = "buy" if self.state.phase == "sell_vol" else "sell"

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=self.state.contracts,
            direction=close_direction,
            quantity=self.config.max_position_size,
            reason=reason,
        )

    def _calculate_portfolio_delta(self) -> float:
        """Calculate total portfolio delta.

        Returns:
            Sum of deltas for all contracts.
        """
        total_delta = 0.0
        for contract in self.state.contracts:
            if contract.delta is not None:
                total_delta += contract.delta
        return total_delta
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_vol_arb_strategy.py -v`
Expected: PASS (5 tests)

### Step 5: Commit

```bash
git add src/strategies/vol_arb.py tests/unit/test_vol_arb_strategy.py
git commit -m "feat: add Volatility Arbitrage strategy with delta hedging"
```

---

## Task 8: Gamma Scalping Strategy

**Files:**
- Create: `src/strategies/gamma_scalp.py`
- Create: `tests/unit/test_gamma_scalp_strategy.py`

### Step 1: Write the failing test

```python
"""Tests for Gamma Scalping strategy implementation."""

import pytest
from datetime import datetime, timezone, timedelta

from src.strategies.gamma_scalp import GammaScalpStrategy, GammaScalpConfig
from src.brain.signal import SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def gamma_config() -> GammaScalpConfig:
    """Create Gamma Scalp strategy config."""
    return GammaScalpConfig(
        name="gamma_scalp",
        enabled=True,
        max_position_size=0.05,
        target_dte_min=14,
        target_dte_max=21,
        profit_target=0.20,
        min_rv=40.0,
        scalp_threshold=0.10,
    )


@pytest.fixture
def volatile_metrics() -> MarketMetrics:
    """Create metrics with high RV (scalping opportunity)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=48.0,
        iv_rank=0.25,
        iv_rv_spread=-5.0,
        rv_7d=55.0,  # High short-term RV
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_atm_options() -> list[OptionContract]:
    """Create ATM options for straddle."""
    expiry = datetime.now(timezone.utc) + timedelta(days=14)
    return [
        OptionContract(
            instrument_name="BTC-14JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.48,
            gamma=0.00018,
            theta=-95.0,
            vega=130.0,
            iv=48.0,
            bid=0.0380,
            ask=0.0410,
        ),
        OptionContract(
            instrument_name="BTC-14JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.52,
            gamma=0.00018,
            theta=-95.0,
            vega=130.0,
            iv=48.0,
            bid=0.0370,
            ask=0.0400,
        ),
    ]


@pytest.mark.asyncio
async def test_gamma_scalp_entry_signal(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp generates buy straddle signal."""
    strategy = GammaScalpStrategy(gamma_config)

    signal = await strategy.evaluate(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.strategy_type == StrategyType.GAMMA_SCALP
    assert signal.action == SignalAction.OPEN
    assert signal.direction == "buy"
    assert len(signal.contracts) == 2


@pytest.mark.asyncio
async def test_gamma_scalp_requires_minimum_rv(
    gamma_config: GammaScalpConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp requires RV > 40%."""
    strategy = GammaScalpStrategy(gamma_config)
    low_rv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=45.0,
        iv_rank=0.30,
        rv_7d=30.0,  # Below threshold
        rv_30d=32.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.evaluate(low_rv_metrics, sample_atm_options)

    assert signal is None


@pytest.mark.asyncio
async def test_gamma_scalp_hedge_signal(
    gamma_config: GammaScalpConfig,
    volatile_metrics: MarketMetrics,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp generates scalp signal when delta exceeds threshold."""
    strategy = GammaScalpStrategy(gamma_config)

    # Simulate active position
    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options

    # Price moved up, delta is now positive
    sample_atm_options[0].delta = -0.35
    sample_atm_options[1].delta = 0.65
    # Net delta = 0.30

    signal = await strategy.manage(volatile_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.HEDGE
    assert signal.direction == "sell"  # Sell BTC to reduce positive delta


@pytest.mark.asyncio
async def test_gamma_scalp_exit_when_rv_drops(
    gamma_config: GammaScalpConfig,
    sample_atm_options: list[OptionContract],
) -> None:
    """Test Gamma Scalp exits when RV drops below IV."""
    strategy = GammaScalpStrategy(gamma_config)

    strategy.state.is_active = True
    strategy.state.position_id = "gs-001"
    strategy.state.contracts = sample_atm_options

    # RV dropped, no longer favorable
    low_rv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.40,
        rv_7d=35.0,  # RV dropped below IV
        rv_30d=38.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await strategy.manage(low_rv_metrics, sample_atm_options)

    assert signal is not None
    assert signal.action == SignalAction.CLOSE
    assert "rv" in signal.reason.lower()


def test_gamma_scalp_strategy_type() -> None:
    """Test strategy type property."""
    config = GammaScalpConfig(name="gs", enabled=True)
    strategy = GammaScalpStrategy(config)

    assert strategy.strategy_type == StrategyType.GAMMA_SCALP
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_gamma_scalp_strategy.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.strategies.gamma_scalp'"

### Step 3: Write minimal implementation

```python
"""Gamma Scalping strategy implementation.

Gamma Scalping profits from high realized volatility:
- Buy ATM straddle (long gamma)
- Continuously hedge delta to lock in profits from price oscillations
- Theta decays but is offset by scalping profits if RV > IV

Entry: RV > 40%, LOW_IV or VOLATILE_FAIR regime
Exit: RV < IV for 3 days, 7 DTE, or scalp P&L < theta
"""

from dataclasses import dataclass
from typing import Optional

from src.strategies.base import BaseStrategy, StrategyConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics
from src.data.option_selector import OptionSelector


@dataclass
class GammaScalpConfig(StrategyConfig):
    """Configuration specific to Gamma Scalp strategy.

    Attributes:
        min_rv: Minimum RV (7d) required for entry.
        scalp_threshold: Delta threshold to trigger scalp trade.
        exit_dte: Exit when DTE falls below this.
    """

    min_rv: float = 40.0
    scalp_threshold: float = 0.10
    exit_dte: int = 7


class GammaScalpStrategy(BaseStrategy):
    """Gamma Scalping: Long straddle with continuous delta hedging.

    Profits from price oscillations when RV exceeds IV.
    """

    def __init__(self, config: GammaScalpConfig) -> None:
        super().__init__(config)
        self.gs_config = config

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.GAMMA_SCALP

    async def evaluate(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Evaluate for entry signal based on RV.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to buy straddle, or None.
        """
        if not self.can_open():
            return None

        # Check RV conditions
        if metrics.rv_7d is None or metrics.rv_7d < self.gs_config.min_rv:
            return None

        return self._generate_straddle_signal(metrics, option_chain)

    async def manage(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Manage position - scalp delta or exit.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to scalp, close, or None.
        """
        if not self.state.is_active:
            return None

        # Check exit condition: RV dropped below threshold
        if metrics.rv_7d is not None and metrics.rv_7d < self.gs_config.min_rv:
            return self._generate_close_signal(
                f"RV dropped to {metrics.rv_7d:.1f}% (below {self.gs_config.min_rv}%)"
            )

        # Check for scalp opportunity
        portfolio_delta = self._calculate_portfolio_delta()

        if abs(portfolio_delta) > self.gs_config.scalp_threshold:
            return TradeSignal(
                strategy_type=self.strategy_type,
                action=SignalAction.HEDGE,
                contracts=[],
                direction="sell" if portfolio_delta > 0 else "buy",
                quantity=abs(portfolio_delta),
                target_delta=0.0,
                reason=f"Gamma scalp: delta {portfolio_delta:.3f} exceeds threshold",
            )

        return None

    def _generate_straddle_signal(
        self,
        metrics: MarketMetrics,
        option_chain: list[OptionContract],
    ) -> Optional[TradeSignal]:
        """Generate buy straddle signal.

        Args:
            metrics: Current market metrics.
            option_chain: Available options.

        Returns:
            Signal to buy straddle, or None.
        """
        selector = OptionSelector(option_chain)

        # Filter for shorter DTE (more gamma)
        selector = selector.filter_by_dte(
            min_dte=self.config.target_dte_min,
            max_dte=self.config.target_dte_max,
        )

        # Find ATM put
        atm_put = selector.find_by_delta(
            target_delta=-0.50,
            option_type="put",
            max_delta_diff=0.10,
        )
        if atm_put is None:
            return None

        # Find ATM call
        atm_call = selector.find_by_delta(
            target_delta=0.50,
            option_type="call",
            max_delta_diff=0.10,
        )
        if atm_call is None:
            return None

        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.OPEN,
            contracts=[atm_put, atm_call],
            direction="buy",
            quantity=self.config.max_position_size,
            legs_direction=["buy", "buy"],
            reason=f"Gamma scalp entry: RV(7d) {metrics.rv_7d:.1f}%",
        )

    def _generate_close_signal(self, reason: str) -> TradeSignal:
        """Generate close signal.

        Args:
            reason: Reason for closing.

        Returns:
            Close signal.
        """
        return TradeSignal(
            strategy_type=self.strategy_type,
            action=SignalAction.CLOSE,
            contracts=self.state.contracts,
            direction="sell",
            quantity=self.config.max_position_size,
            reason=reason,
        )

    def _calculate_portfolio_delta(self) -> float:
        """Calculate total portfolio delta.

        Returns:
            Sum of deltas for all contracts.
        """
        total_delta = 0.0
        for contract in self.state.contracts:
            if contract.delta is not None:
                total_delta += contract.delta
        return total_delta
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_gamma_scalp_strategy.py -v`
Expected: PASS (5 tests)

### Step 5: Commit

```bash
git add src/strategies/gamma_scalp.py tests/unit/test_gamma_scalp_strategy.py
git commit -m "feat: add Gamma Scalping strategy with delta scalping"
```

---

## Task 9: Strategy Integration Tests

**Files:**
- Create: `tests/integration/test_strategy_integration.py`

### Step 1: Write the integration test

```python
"""Integration tests for strategy execution flow."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer
from src.brain.regime_detector import MarketRegime, RegimeDetector
from src.brain.strategy_selector import StrategySelector
from src.brain.signal import StrategyType, OptionContract
from src.strategies.wheel import WheelStrategy
from src.strategies.iron_condor import IronCondorStrategy, IronCondorConfig
from src.strategies.vol_arb import VolArbStrategy, VolArbConfig
from src.strategies.gamma_scalp import GammaScalpStrategy, GammaScalpConfig
from src.strategies.base import StrategyConfig


@pytest.fixture
def sample_option_chain() -> list[OptionContract]:
    """Create comprehensive option chain for testing."""
    expiry = datetime.now(timezone.utc) + timedelta(days=35)
    options = []

    # Generate puts from 85k to 100k
    for strike in range(85000, 101000, 3000):
        delta = -0.05 - (100000 - strike) / 100000 * 0.45
        options.append(OptionContract(
            instrument_name=f"BTC-31JAN26-{strike}-P",
            strike=float(strike),
            expiry=expiry,
            option_type="put",
            delta=delta,
            gamma=0.00012,
            theta=-50.0,
            vega=100.0,
            iv=52.0,
            bid=0.01 + (100000 - strike) / 100000 * 0.05,
            ask=0.012 + (100000 - strike) / 100000 * 0.05,
        ))

    # Generate calls from 97k to 115k
    for strike in range(97000, 116000, 3000):
        delta = 0.50 - (strike - 97000) / 100000 * 0.45
        options.append(OptionContract(
            instrument_name=f"BTC-31JAN26-{strike}-C",
            strike=float(strike),
            expiry=expiry,
            option_type="call",
            delta=max(0.05, delta),
            gamma=0.00012,
            theta=-50.0,
            vega=100.0,
            iv=52.0,
            bid=0.01 + max(0, (100000 - strike) / 100000 * 0.05),
            ask=0.012 + max(0, (100000 - strike) / 100000 * 0.05),
        ))

    return options


@pytest.mark.asyncio
async def test_regime_to_strategy_flow(sample_option_chain: list[OptionContract]) -> None:
    """Test complete flow: regime detection → strategy selection → signal generation."""
    selector = StrategySelector()

    # Test NEUTRAL regime → Wheel strategy
    regime = MarketRegime.NEUTRAL
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.WHEEL

    # Create and evaluate Wheel strategy
    wheel = WheelStrategy(StrategyConfig(name="wheel", enabled=True))
    from src.data.market_metrics import MarketMetrics

    neutral_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        rv_30d=48.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await wheel.evaluate(neutral_metrics, sample_option_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.WHEEL


@pytest.mark.asyncio
async def test_high_iv_regime_iron_condor(sample_option_chain: list[OptionContract]) -> None:
    """Test HIGH_IV regime triggers Iron Condor."""
    selector = StrategySelector()
    from src.data.market_metrics import MarketMetrics

    regime = MarketRegime.HIGH_IV_OVERPRICED
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.IRON_CONDOR

    # Create and evaluate Iron Condor
    config = IronCondorConfig(name="ic", enabled=True)
    ic = IronCondorStrategy(config)

    high_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=62.0,
        iv_rank=0.72,
        iv_rv_spread=15.0,
        rv_30d=47.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await ic.evaluate(high_iv_metrics, sample_option_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.IRON_CONDOR
    assert len(signal.contracts) == 4


@pytest.mark.asyncio
async def test_low_iv_regime_gamma_scalp(sample_option_chain: list[OptionContract]) -> None:
    """Test LOW_IV regime triggers Gamma Scalp."""
    selector = StrategySelector()
    from src.data.market_metrics import MarketMetrics

    regime = MarketRegime.LOW_IV_UNDERPRICED
    strategy_type = selector.select(regime)
    assert strategy_type == StrategyType.GAMMA_SCALP

    # Create and evaluate Gamma Scalp
    config = GammaScalpConfig(name="gs", enabled=True, target_dte_min=20, target_dte_max=40)
    gs = GammaScalpStrategy(config)

    low_iv_metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=38.0,
        iv_rank=0.18,
        iv_rv_spread=-12.0,
        rv_7d=52.0,
        rv_30d=50.0,
        timestamp=datetime.now(timezone.utc),
    )

    signal = await gs.evaluate(low_iv_metrics, sample_option_chain)
    assert signal is not None
    assert signal.strategy_type == StrategyType.GAMMA_SCALP
    assert signal.direction == "buy"


@pytest.mark.asyncio
async def test_extreme_fear_no_strategy() -> None:
    """Test EXTREME_FEAR regime returns no strategy."""
    selector = StrategySelector()

    regime = MarketRegime.EXTREME_FEAR
    strategy_type = selector.select(regime)

    assert strategy_type is None


@pytest.mark.asyncio
async def test_multiple_strategies_can_coexist(sample_option_chain: list[OptionContract]) -> None:
    """Test that multiple strategies can be instantiated and evaluated."""
    from src.data.market_metrics import MarketMetrics

    strategies = [
        WheelStrategy(StrategyConfig(name="wheel", enabled=True)),
        IronCondorStrategy(IronCondorConfig(name="ic", enabled=True)),
        VolArbStrategy(VolArbConfig(name="va", enabled=True)),
        GammaScalpStrategy(GammaScalpConfig(name="gs", enabled=True, target_dte_min=20, target_dte_max=40)),
    ]

    # Metrics that could trigger multiple strategies
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=55.0,
        iv_rank=0.55,
        iv_rv_spread=10.0,
        rv_7d=48.0,
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )

    signals = []
    for strategy in strategies:
        signal = await strategy.evaluate(metrics, sample_option_chain)
        if signal:
            signals.append(signal)

    # At least one strategy should generate a signal
    assert len(signals) >= 1
```

### Step 2: Run test to verify it passes

Run: `pytest tests/integration/test_strategy_integration.py -v`
Expected: PASS (5 tests)

### Step 3: Commit

```bash
git add tests/integration/test_strategy_integration.py
git commit -m "test: add strategy integration tests"
```

---

## Task 10: Final Verification

**Files:**
- No new files, verification only

### Step 1: Run all tests

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass (60+ tests)

### Step 2: Run mypy type checking

```bash
mypy src/ --ignore-missing-imports
```

Expected: Success (0 errors)

### Step 3: Run ruff linting

```bash
ruff check src/ tests/
```

Expected: All checks passed

### Step 4: Check test coverage

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

Expected: Coverage > 80%

### Step 5: Commit final state

```bash
git add -A
git commit -m "chore: Phase 3 complete - strategy implementations"
```

---

## Summary

Phase 3 implements the four core trading strategies:

| Strategy | Entry Condition | Signal Type |
|----------|----------------|-------------|
| Wheel | NEUTRAL, IV Rank > 30% | Sell CSP / Covered Call |
| Iron Condor | HIGH_IV, IV Rank > 50% | 4-leg spread |
| Vol Arb | IV-RV spread > ±15 | ATM straddle + hedge |
| Gamma Scalp | LOW_IV/VOLATILE, RV > 40% | Buy straddle + scalp |

**Key Components:**
- `src/brain/signal.py` - TradeSignal, OptionContract models
- `src/data/option_selector.py` - Find options by delta/strike
- `src/strategies/base.py` - BaseStrategy interface
- `src/brain/strategy_selector.py` - Regime → Strategy mapping
- `src/strategies/wheel.py` - Wheel implementation
- `src/strategies/iron_condor.py` - Iron Condor implementation
- `src/strategies/vol_arb.py` - Vol Arb implementation
- `src/strategies/gamma_scalp.py` - Gamma Scalp implementation

**Next Phase (Phase 4):** Risk & Execution
- Position sizing (Half Kelly)
- Delta hedger
- Circuit breakers
- Order execution engine
