# Phase 6: Backtesting + DVOL Emergency Close

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add DVOL > 100 emergency position close, build backtesting framework, configure paper trading.

**Architecture:** EmergencyManager monitors for extreme DVOL and generates CLOSE signals for short vol positions. BacktestEngine replays historical data through strategies with simulated execution. Paper trading uses Deribit testnet.

**Tech Stack:** Python 3.11, pytest, numpy, existing Deribit client

---

## Batch 1: DVOL > 100 Emergency Close

### Task 1: Add EmergencyManager

**Files:**
- Create: `src/risk/emergency_manager.py`
- Test: `tests/unit/test_emergency_manager.py`

**Step 1: Write the failing test**

```python
"""Tests for emergency manager."""

import pytest
from datetime import datetime, timezone

from src.risk.emergency_manager import EmergencyManager, EmergencyConfig
from src.data.market_metrics import MarketMetrics
from src.brain.signal import StrategyType


@pytest.fixture
def emergency_config() -> EmergencyConfig:
    """Create emergency config."""
    return EmergencyConfig(
        dvol_emergency_threshold=100.0,
    )


@pytest.fixture
def extreme_metrics() -> MarketMetrics:
    """DVOL > 100 crisis metrics."""
    return MarketMetrics(
        btc_price=85000.0,
        dvol=105.0,
        iv_rank=0.99,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def normal_metrics() -> MarketMetrics:
    """Normal market conditions."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )


def test_is_emergency_true_when_dvol_extreme(
    emergency_config: EmergencyConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test emergency detected when DVOL > 100."""
    manager = EmergencyManager(emergency_config)

    assert manager.is_emergency(extreme_metrics) is True


def test_is_emergency_false_when_dvol_normal(
    emergency_config: EmergencyConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test no emergency in normal conditions."""
    manager = EmergencyManager(emergency_config)

    assert manager.is_emergency(normal_metrics) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_emergency_manager.py -v`
Expected: FAIL with "No module named 'src.risk.emergency_manager'"

**Step 3: Write minimal implementation**

```python
"""Emergency manager for extreme market conditions."""

from dataclasses import dataclass

from src.data.market_metrics import MarketMetrics


@dataclass
class EmergencyConfig:
    """Configuration for emergency manager.

    Attributes:
        dvol_emergency_threshold: DVOL level triggering emergency close (default 100).
    """

    dvol_emergency_threshold: float = 100.0


class EmergencyManager:
    """Manages emergency position closures during extreme conditions.

    Triggers active position closure (not just halt) when DVOL > 100.
    This is more severe than CircuitBreaker's DVOL >= 80 halt.
    """

    def __init__(self, config: EmergencyConfig) -> None:
        """Initialize emergency manager.

        Args:
            config: Emergency configuration.
        """
        self.config = config

    def is_emergency(self, metrics: MarketMetrics) -> bool:
        """Check if emergency conditions exist.

        Args:
            metrics: Current market metrics.

        Returns:
            True if DVOL exceeds emergency threshold.
        """
        if metrics.dvol is None:
            return False

        return metrics.dvol > self.config.dvol_emergency_threshold
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_emergency_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/risk/emergency_manager.py tests/unit/test_emergency_manager.py
git commit -m "feat: add emergency manager with DVOL > 100 detection"
```

---

### Task 2: Add Short Vol Position Identification

**Files:**
- Modify: `src/risk/emergency_manager.py`
- Test: `tests/unit/test_emergency_manager.py`

**Step 1: Add failing test**

```python
from src.persistence.models import Position, PositionStatus


@pytest.fixture
def short_vol_positions() -> list[Position]:
    """Mix of short vol and other positions."""
    now = datetime.now(timezone.utc)
    return [
        Position(
            strategy_id="vol-001",
            strategy_type="vol_arb",
            status=PositionStatus.OPEN,
            phase="sell_vol",  # SHORT vol
            opened_at=now,
        ),
        Position(
            strategy_id="ic-001",
            strategy_type="iron_condor",
            status=PositionStatus.OPEN,
            phase=None,  # Iron condor is short vol
            opened_at=now,
        ),
        Position(
            strategy_id="vol-002",
            strategy_type="vol_arb",
            status=PositionStatus.OPEN,
            phase="buy_vol",  # LONG vol - don't close
            opened_at=now,
        ),
        Position(
            strategy_id="whl-001",
            strategy_type="wheel",
            status=PositionStatus.OPEN,
            phase="csp",  # Wheel - don't close
            opened_at=now,
        ),
    ]


def test_identify_short_vol_positions(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
) -> None:
    """Test identifying positions to close in emergency."""
    manager = EmergencyManager(emergency_config)

    to_close = manager.identify_short_vol_positions(short_vol_positions)

    # Should identify vol_arb sell_vol and iron_condor
    assert len(to_close) == 2
    strategy_ids = [p.strategy_id for p in to_close]
    assert "vol-001" in strategy_ids  # sell_vol
    assert "ic-001" in strategy_ids   # iron condor
    assert "vol-002" not in strategy_ids  # buy_vol is long, keep
    assert "whl-001" not in strategy_ids  # wheel is different risk
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_emergency_manager.py::test_identify_short_vol_positions -v`
Expected: FAIL with "has no attribute 'identify_short_vol_positions'"

**Step 3: Add implementation**

```python
from src.persistence.models import Position, PositionStatus

# Add to EmergencyManager class:

# Short vol strategy types that should be closed in emergency
SHORT_VOL_STRATEGIES = {"iron_condor"}
# Vol arb with sell_vol phase is also short vol
VOL_ARB_SHORT_PHASE = "sell_vol"

def identify_short_vol_positions(
    self,
    positions: list[Position],
) -> list[Position]:
    """Identify short vol positions that should be closed.

    Short vol positions:
    - Iron Condor (always short vol)
    - Vol Arb with phase="sell_vol"

    Args:
        positions: All open positions.

    Returns:
        List of positions to close.
    """
    to_close: list[Position] = []

    for pos in positions:
        if pos.status != PositionStatus.OPEN:
            continue

        # Iron condor is always short vol
        if pos.strategy_type == "iron_condor":
            to_close.append(pos)
            continue

        # Vol arb with sell_vol phase
        if pos.strategy_type == "vol_arb" and pos.phase == self.VOL_ARB_SHORT_PHASE:
            to_close.append(pos)

    return to_close
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_emergency_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/risk/emergency_manager.py tests/unit/test_emergency_manager.py
git commit -m "feat: add short vol position identification for emergency close"
```

---

### Task 3: Generate Emergency Close Signals

**Files:**
- Modify: `src/risk/emergency_manager.py`
- Test: `tests/unit/test_emergency_manager.py`

**Step 1: Add failing test**

```python
from src.brain.signal import TradeSignal, SignalAction, StrategyType


def test_generate_close_signals(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
    extreme_metrics: MarketMetrics,
) -> None:
    """Test generating CLOSE signals for short vol positions."""
    manager = EmergencyManager(emergency_config)

    signals = manager.check_emergency(extreme_metrics, short_vol_positions)

    # Should generate 2 close signals
    assert len(signals) == 2

    for signal in signals:
        assert signal.action == SignalAction.CLOSE
        assert "DVOL emergency" in signal.reason.lower() or "emergency" in signal.reason.lower()


def test_no_signals_when_not_emergency(
    emergency_config: EmergencyConfig,
    short_vol_positions: list[Position],
    normal_metrics: MarketMetrics,
) -> None:
    """Test no signals in normal conditions."""
    manager = EmergencyManager(emergency_config)

    signals = manager.check_emergency(normal_metrics, short_vol_positions)

    assert len(signals) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_emergency_manager.py::test_generate_close_signals -v`
Expected: FAIL with "has no attribute 'check_emergency'"

**Step 3: Add implementation**

```python
from src.brain.signal import TradeSignal, SignalAction, StrategyType

# Add to EmergencyManager class:

def check_emergency(
    self,
    metrics: MarketMetrics,
    positions: list[Position],
) -> list[TradeSignal]:
    """Check for emergency and generate close signals if needed.

    Args:
        metrics: Current market metrics.
        positions: All open positions.

    Returns:
        List of CLOSE signals for short vol positions, empty if no emergency.
    """
    if not self.is_emergency(metrics):
        return []

    to_close = self.identify_short_vol_positions(positions)

    signals: list[TradeSignal] = []
    for pos in to_close:
        signal = TradeSignal(
            strategy_type=StrategyType(pos.strategy_type),
            action=SignalAction.CLOSE,
            contracts=[],  # Actual contracts resolved by execution layer
            direction="buy",  # Closing short = buy back
            quantity=0.0,  # Full position close
            reason=f"DVOL emergency {metrics.dvol:.0f} > {self.config.dvol_emergency_threshold}: closing {pos.strategy_id}",
        )
        signals.append(signal)

    return signals
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_emergency_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/risk/emergency_manager.py tests/unit/test_emergency_manager.py
git commit -m "feat: add emergency close signal generation for DVOL > 100"
```

---

### Task 4: Update Risk __init__ Export

**Files:**
- Modify: `src/risk/__init__.py`

**Step 1: Update exports**

```python
"""Risk management components."""

from src.risk.circuit_breaker import (
    BreakerConfig,
    BreakerEvent,
    BreakerStatus,
    CircuitBreaker,
)
from src.risk.emergency_manager import EmergencyConfig, EmergencyManager
from src.risk.position_sizer import PositionSizer, SizingConfig, SizingResult
from src.risk.risk_manager import RiskConfig, RiskManager, ValidationResult

__all__ = [
    "BreakerConfig",
    "BreakerEvent",
    "BreakerStatus",
    "CircuitBreaker",
    "EmergencyConfig",
    "EmergencyManager",
    "PositionSizer",
    "RiskConfig",
    "RiskManager",
    "SizingConfig",
    "SizingResult",
    "ValidationResult",
]
```

**Step 2: Run tests**

Run: `pytest tests/unit/test_emergency_manager.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/risk/__init__.py
git commit -m "chore: export EmergencyManager from risk module"
```

---

## Batch 2: Backtesting Framework

### Task 5: Historical Data Fetcher

**Files:**
- Create: `src/backtest/data_fetcher.py`
- Create: `src/backtest/__init__.py`
- Test: `tests/unit/test_backtest_data_fetcher.py`

**Step 1: Write failing test**

```python
"""Tests for backtest data fetcher."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.backtest.data_fetcher import HistoricalDataFetcher, HistoricalBar


@pytest.fixture
def mock_client() -> MagicMock:
    """Create mock Deribit client."""
    client = MagicMock()
    client.get_tradingview_chart_data = AsyncMock(return_value={
        "ticks": [1704067200000, 1704153600000],  # 2024-01-01, 2024-01-02
        "open": [42000.0, 42500.0],
        "high": [43000.0, 43500.0],
        "low": [41500.0, 42000.0],
        "close": [42500.0, 43000.0],
        "volume": [1000.0, 1200.0],
    })
    client.get_volatility_index = AsyncMock(return_value=[
        [1704067200000, 55.0, 58.0, 54.0, 56.0],  # DVOL OHLC
        [1704153600000, 56.0, 60.0, 55.0, 58.0],
    ])
    return client


@pytest.mark.asyncio
async def test_fetch_price_history(mock_client: MagicMock) -> None:
    """Test fetching historical price bars."""
    fetcher = HistoricalDataFetcher(mock_client)

    bars = await fetcher.fetch_price_history(
        instrument="BTC-PERPETUAL",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 3, tzinfo=timezone.utc),
        resolution="1D",
    )

    assert len(bars) == 2
    assert bars[0].close == 42500.0
    assert bars[1].close == 43000.0


@pytest.mark.asyncio
async def test_fetch_dvol_history(mock_client: MagicMock) -> None:
    """Test fetching historical DVOL."""
    fetcher = HistoricalDataFetcher(mock_client)

    dvol_bars = await fetcher.fetch_dvol_history(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 3, tzinfo=timezone.utc),
    )

    assert len(dvol_bars) == 2
    assert dvol_bars[0].close == 56.0  # DVOL close
    assert dvol_bars[1].close == 58.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_backtest_data_fetcher.py -v`
Expected: FAIL with "No module named 'src.backtest'"

**Step 3: Write implementation**

Create `src/backtest/__init__.py`:
```python
"""Backtesting framework."""
```

Create `src/backtest/data_fetcher.py`:
```python
"""Historical data fetcher for backtesting."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.data.deribit_client import DeribitClient


@dataclass
class HistoricalBar:
    """Single OHLCV bar.

    Attributes:
        timestamp: Bar timestamp (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Trading volume.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class HistoricalDataFetcher:
    """Fetches historical data from Deribit for backtesting."""

    def __init__(self, client: DeribitClient) -> None:
        """Initialize fetcher.

        Args:
            client: Deribit API client.
        """
        self.client = client

    async def fetch_price_history(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        resolution: str = "1D",
    ) -> list[HistoricalBar]:
        """Fetch historical price bars.

        Args:
            instrument: Instrument name (e.g., BTC-PERPETUAL).
            start: Start datetime (UTC).
            end: End datetime (UTC).
            resolution: Candle resolution (1D, 1, 60, etc).

        Returns:
            List of HistoricalBar objects.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        data = await self.client.get_tradingview_chart_data(
            instrument_name=instrument,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms,
        )

        return self._parse_ohlcv(data)

    async def fetch_dvol_history(
        self,
        start: datetime,
        end: datetime,
        currency: str = "BTC",
        resolution: int = 86400,  # Daily
    ) -> list[HistoricalBar]:
        """Fetch historical DVOL data.

        Args:
            start: Start datetime (UTC).
            end: End datetime (UTC).
            currency: Currency (BTC, ETH).
            resolution: Resolution in seconds (default 1 day).

        Returns:
            List of HistoricalBar objects with DVOL as close.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        data = await self.client.get_volatility_index(
            currency=currency,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms,
        )

        bars: list[HistoricalBar] = []
        for row in data:
            # Row: [timestamp_ms, open, high, low, close]
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            bars.append(HistoricalBar(
                timestamp=ts,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=0.0,
            ))

        return bars

    def _parse_ohlcv(self, data: dict[str, Any]) -> list[HistoricalBar]:
        """Parse TradingView chart data response.

        Args:
            data: Response from get_tradingview_chart_data.

        Returns:
            List of HistoricalBar objects.
        """
        bars: list[HistoricalBar] = []

        ticks = data.get("ticks", [])
        opens = data.get("open", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        closes = data.get("close", [])
        volumes = data.get("volume", [0.0] * len(ticks))

        for i, tick in enumerate(ticks):
            ts = datetime.fromtimestamp(tick / 1000, tz=timezone.utc)
            bars.append(HistoricalBar(
                timestamp=ts,
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i] if i < len(volumes) else 0.0,
            ))

        return bars
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_backtest_data_fetcher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/backtest/__init__.py src/backtest/data_fetcher.py tests/unit/test_backtest_data_fetcher.py
git commit -m "feat: add historical data fetcher for backtesting"
```

---

### Task 6: Backtest Engine Core

**Files:**
- Create: `src/backtest/engine.py`
- Test: `tests/unit/test_backtest_engine.py`

**Step 1: Write failing test**

```python
"""Tests for backtest engine."""

import pytest
from datetime import datetime, timezone
from dataclasses import dataclass

from src.backtest.engine import BacktestEngine, BacktestConfig, BacktestResult
from src.backtest.data_fetcher import HistoricalBar
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def backtest_config() -> BacktestConfig:
    """Create backtest config."""
    return BacktestConfig(
        initial_capital=100000.0,
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 10, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_price_bars() -> list[HistoricalBar]:
    """Sample price history."""
    return [
        HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=42000.0, high=43000.0, low=41500.0, close=42500.0, volume=1000.0,
        ),
        HistoricalBar(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=42500.0, high=44000.0, low=42000.0, close=43500.0, volume=1200.0,
        ),
    ]


@pytest.fixture
def sample_dvol_bars() -> list[HistoricalBar]:
    """Sample DVOL history."""
    return [
        HistoricalBar(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=55.0, high=58.0, low=54.0, close=56.0, volume=0.0,
        ),
        HistoricalBar(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            open=56.0, high=60.0, low=55.0, close=58.0, volume=0.0,
        ),
    ]


def test_backtest_engine_initialization(backtest_config: BacktestConfig) -> None:
    """Test engine initializes correctly."""
    engine = BacktestEngine(backtest_config)

    assert engine.capital == backtest_config.initial_capital
    assert engine.positions == []


def test_build_metrics_from_bars(
    backtest_config: BacktestConfig,
    sample_price_bars: list[HistoricalBar],
    sample_dvol_bars: list[HistoricalBar],
) -> None:
    """Test building MarketMetrics from historical bars."""
    engine = BacktestEngine(backtest_config)

    metrics = engine.build_metrics(
        price_bar=sample_price_bars[0],
        dvol_bar=sample_dvol_bars[0],
    )

    assert metrics.btc_price == 42500.0  # close price
    assert metrics.dvol == 56.0  # DVOL close
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_backtest_engine.py -v`
Expected: FAIL with "No module named 'src.backtest.engine'"

**Step 3: Write implementation**

```python
"""Backtest engine for strategy validation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.backtest.data_fetcher import HistoricalBar
from src.data.market_metrics import MarketMetrics
from src.persistence.models import Position


@dataclass
class BacktestConfig:
    """Configuration for backtesting.

    Attributes:
        initial_capital: Starting capital in USD.
        start_date: Backtest start date.
        end_date: Backtest end date.
        commission_pct: Trading commission as percentage.
    """

    initial_capital: float = 100000.0
    start_date: datetime = field(default_factory=datetime.now)
    end_date: datetime = field(default_factory=datetime.now)
    commission_pct: float = 0.0005  # 0.05%


@dataclass
class BacktestResult:
    """Results from a backtest run.

    Attributes:
        total_return: Total return percentage.
        sharpe_ratio: Annualized Sharpe ratio.
        max_drawdown: Maximum drawdown percentage.
        win_rate: Percentage of winning trades.
        total_trades: Number of trades executed.
        final_capital: Ending capital.
    """

    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    final_capital: float = 0.0


class BacktestEngine:
    """Engine for running strategy backtests.

    Simulates trading by replaying historical data through
    the regime detector and strategies.
    """

    def __init__(self, config: BacktestConfig) -> None:
        """Initialize backtest engine.

        Args:
            config: Backtest configuration.
        """
        self.config = config
        self.capital = config.initial_capital
        self.peak_capital = config.initial_capital
        self.positions: list[Position] = []
        self.trades: list[dict] = []
        self.equity_curve: list[float] = []

    def build_metrics(
        self,
        price_bar: HistoricalBar,
        dvol_bar: Optional[HistoricalBar] = None,
        iv_rank: Optional[float] = None,
        rv_30d: Optional[float] = None,
    ) -> MarketMetrics:
        """Build MarketMetrics from historical bars.

        Args:
            price_bar: Price OHLCV bar.
            dvol_bar: DVOL OHLCV bar (optional).
            iv_rank: IV rank if available.
            rv_30d: 30-day realized vol if available.

        Returns:
            MarketMetrics for the bar timestamp.
        """
        dvol = dvol_bar.close if dvol_bar else None
        iv_rv_spread = None
        if dvol is not None and rv_30d is not None:
            iv_rv_spread = dvol - rv_30d

        return MarketMetrics(
            btc_price=price_bar.close,
            dvol=dvol,
            iv_rank=iv_rank,
            rv_30d=rv_30d,
            iv_rv_spread=iv_rv_spread,
            timestamp=price_bar.timestamp,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_backtest_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/backtest/engine.py tests/unit/test_backtest_engine.py
git commit -m "feat: add backtest engine core with config and metrics building"
```

---

### Task 7: Backtest Run Loop

**Files:**
- Modify: `src/backtest/engine.py`
- Test: `tests/unit/test_backtest_engine.py`

**Step 1: Add failing test**

```python
@pytest.mark.asyncio
async def test_run_backtest_returns_result(
    backtest_config: BacktestConfig,
    sample_price_bars: list[HistoricalBar],
    sample_dvol_bars: list[HistoricalBar],
) -> None:
    """Test running a backtest returns result."""
    engine = BacktestEngine(backtest_config)

    result = await engine.run(
        price_bars=sample_price_bars,
        dvol_bars=sample_dvol_bars,
    )

    assert isinstance(result, BacktestResult)
    assert result.final_capital == backtest_config.initial_capital  # No trades
    assert result.total_return == 0.0
    assert result.max_drawdown == 0.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_backtest_engine.py::test_run_backtest_returns_result -v`
Expected: FAIL with "has no attribute 'run'"

**Step 3: Add implementation**

```python
import numpy as np
from typing import Optional

# Add to BacktestEngine class:

async def run(
    self,
    price_bars: list[HistoricalBar],
    dvol_bars: list[HistoricalBar],
) -> BacktestResult:
    """Run backtest over historical data.

    Args:
        price_bars: Historical price bars.
        dvol_bars: Historical DVOL bars.

    Returns:
        BacktestResult with performance metrics.
    """
    # Align bars by timestamp
    dvol_by_ts = {bar.timestamp: bar for bar in dvol_bars}

    self.equity_curve = [self.capital]

    for price_bar in price_bars:
        dvol_bar = dvol_by_ts.get(price_bar.timestamp)
        metrics = self.build_metrics(price_bar, dvol_bar)

        # TODO: In full implementation, run through regime detector
        # and strategies here. For now, just track equity.

        self.equity_curve.append(self.capital)
        self.peak_capital = max(self.peak_capital, self.capital)

    return self._calculate_results()

def _calculate_results(self) -> BacktestResult:
    """Calculate backtest performance metrics.

    Returns:
        BacktestResult with calculated metrics.
    """
    if len(self.equity_curve) < 2:
        return BacktestResult(final_capital=self.capital)

    equity = np.array(self.equity_curve)
    returns = np.diff(equity) / equity[:-1]

    # Total return
    total_return = (self.capital - self.config.initial_capital) / self.config.initial_capital

    # Sharpe ratio (annualized, assuming daily bars)
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    max_dd = float(np.max(drawdown))

    # Win rate
    winning = sum(1 for t in self.trades if t.get("pnl", 0) > 0)
    win_rate = winning / len(self.trades) if self.trades else 0.0

    return BacktestResult(
        total_return=total_return,
        sharpe_ratio=float(sharpe),
        max_drawdown=max_dd,
        win_rate=win_rate,
        total_trades=len(self.trades),
        final_capital=self.capital,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_backtest_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/backtest/engine.py tests/unit/test_backtest_engine.py
git commit -m "feat: add backtest run loop with performance metrics"
```

---

### Task 8: Export Backtest Module

**Files:**
- Modify: `src/backtest/__init__.py`

**Step 1: Update exports**

```python
"""Backtesting framework."""

from src.backtest.data_fetcher import HistoricalBar, HistoricalDataFetcher
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "HistoricalBar",
    "HistoricalDataFetcher",
]
```

**Step 2: Run all backtest tests**

Run: `pytest tests/unit/test_backtest*.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/backtest/__init__.py
git commit -m "chore: export backtest module components"
```

---

## Batch 3: Paper Trading Configuration

### Task 9: Paper Trading Config

**Files:**
- Create: `config/settings.testnet.yaml`

**Step 1: Create testnet config**

```yaml
# Paper Trading Configuration - Deribit Testnet
# Use this for testing strategies without risking real capital

deribit:
  # Deribit testnet URL
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"
  # Get testnet API keys from: https://test.deribit.com/
  api_key: "${DERIBIT_TESTNET_API_KEY}"
  api_secret: "${DERIBIT_TESTNET_API_SECRET}"

risk:
  max_position_pct: 10.0
  max_exposure_pct: 30.0
  max_daily_loss_pct: 5.0
  max_drawdown_pct: 15.0
  dvol_reduce_threshold: 60.0
  dvol_halt_threshold: 80.0

emergency:
  dvol_emergency_threshold: 100.0

database:
  path: "data/paper_trading.db"
```

**Step 2: Commit**

```bash
git add config/settings.testnet.yaml
git commit -m "feat: add paper trading testnet configuration"
```

---

### Task 10: Final Verification

**Step 1: Run full test suite**

```bash
pytest --tb=short
```
Expected: All tests pass

**Step 2: Run mypy**

```bash
mypy src/
```
Expected: Success: no issues found

**Step 3: Run ruff**

```bash
ruff check src/ tests/
```
Expected: All checks passed

**Step 4: Final commit**

```bash
git add .
git commit -m "chore: Phase 6 complete - backtest framework and DVOL emergency close"
```

---

## Summary

| Batch | Tasks | Components |
|-------|-------|------------|
| 1 | 1-4 | EmergencyManager (DVOL > 100 close) |
| 2 | 5-8 | BacktestEngine, HistoricalDataFetcher |
| 3 | 9-10 | Paper trading config, verification |

**New Files:**
```
src/risk/emergency_manager.py
src/backtest/__init__.py
src/backtest/data_fetcher.py
src/backtest/engine.py
config/settings.testnet.yaml
tests/unit/test_emergency_manager.py
tests/unit/test_backtest_data_fetcher.py
tests/unit/test_backtest_engine.py
```

**Test Count:** ~12 new tests
