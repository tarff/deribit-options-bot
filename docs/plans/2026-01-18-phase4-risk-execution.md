# Phase 4: Risk & Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement position sizing (Half Kelly), risk management (limits & validation), delta hedging, and circuit breakers for the trading bot.

**Architecture:** RiskManager validates signals before execution. PositionSizer calculates optimal size using Half Kelly with DVOL-based regime adjustment. DeltaHedger monitors portfolio delta and generates hedge signals. CircuitBreaker halts trading on loss limits, DVOL spikes, or API errors.

**Tech Stack:** Python 3.11+, dataclasses, async/await, existing MarketMetrics and TradeSignal interfaces

---

## Overview

| Task | Component | Description |
|------|-----------|-------------|
| 1 | Position Sizer | Half Kelly sizing with regime adjustment |
| 2 | Risk Manager | Pre-trade validation, exposure limits |
| 3 | Delta Hedger | Portfolio delta calculation, hedge signals |
| 4 | Circuit Breaker | Daily loss, DVOL spike, API error triggers |
| 5 | Risk Integration Tests | End-to-end risk flow tests |
| 6 | Final Verification | Tests, mypy, ruff, coverage |

**Suggested Batches:**
- Batch 1: Tasks 1-2 (Position Sizer, Risk Manager)
- Batch 2: Tasks 3-4 (Delta Hedger, Circuit Breaker)
- Batch 3: Tasks 5-6 (Integration tests, verification)

---

## Task 1: Position Sizer

**Files:**
- Create: `src/risk/__init__.py`
- Create: `src/risk/position_sizer.py`
- Create: `tests/unit/test_position_sizer.py`

### Step 1: Write the failing test

```python
"""Tests for position sizer with Half Kelly criterion."""

import pytest
from datetime import datetime, timezone

from src.risk.position_sizer import PositionSizer, SizingConfig, SizingResult
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def sizer_config() -> SizingConfig:
    """Create position sizer config."""
    return SizingConfig(
        max_position_pct=0.10,  # 10% max per position
        max_total_exposure_pct=0.30,  # 30% max total
        base_win_rate=0.65,
        base_avg_win=0.02,
        base_avg_loss=0.01,
    )


@pytest.fixture
def normal_metrics() -> MarketMetrics:
    """Normal market conditions (DVOL < 60)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        iv_rank=0.45,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def stressed_metrics() -> MarketMetrics:
    """Stressed market (60 <= DVOL < 80)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=68.0,
        iv_rank=0.75,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def extreme_metrics() -> MarketMetrics:
    """Extreme fear (DVOL >= 80)."""
    return MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        iv_rank=0.92,
        timestamp=datetime.now(timezone.utc),
    )


def test_half_kelly_calculation(sizer_config: SizingConfig) -> None:
    """Test Half Kelly formula: f* = (p - q/b) / 2."""
    sizer = PositionSizer(sizer_config)

    # win_rate=0.65, avg_win=0.02, avg_loss=0.01
    # kelly = 0.65 - (0.35 / 2.0) = 0.65 - 0.175 = 0.475
    # half_kelly = 0.475 / 2 = 0.2375
    # capped at 0.10
    result = sizer.calculate_kelly()

    assert result == pytest.approx(0.10, abs=0.001)  # Capped at max


def test_size_position_normal_market(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test full size in normal market conditions."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, normal_metrics, current_exposure=0.0)

    assert result.size_btc > 0
    assert result.size_pct <= sizer_config.max_position_pct
    assert result.regime_multiplier == 1.0
    assert result.approved is True


def test_size_position_stressed_market_50pct_reduction(
    sizer_config: SizingConfig,
    stressed_metrics: MarketMetrics,
) -> None:
    """Test 50% size reduction when DVOL 60-80."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, stressed_metrics, current_exposure=0.0)

    assert result.regime_multiplier == 0.5
    assert result.size_pct <= sizer_config.max_position_pct * 0.5
    assert result.approved is True


def test_size_position_extreme_market_blocked(
    sizer_config: SizingConfig,
    extreme_metrics: MarketMetrics,
) -> None:
    """Test position blocked when DVOL >= 80."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    result = sizer.size_position(capital, extreme_metrics, current_exposure=0.0)

    assert result.approved is False
    assert result.size_btc == 0.0
    assert result.regime_multiplier == 0.0
    assert "extreme" in result.reason.lower()


def test_size_position_respects_exposure_limit(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position reduced when near exposure limit."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    # Already at 25% exposure, limit is 30%
    result = sizer.size_position(capital, normal_metrics, current_exposure=0.25)

    # Can only add 5% more
    assert result.size_pct <= 0.05
    assert result.approved is True


def test_size_position_blocked_at_exposure_limit(
    sizer_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test position blocked when at exposure limit."""
    sizer = PositionSizer(sizer_config)
    capital = 100000.0

    # Already at 30% exposure
    result = sizer.size_position(capital, normal_metrics, current_exposure=0.30)

    assert result.approved is False
    assert "exposure limit" in result.reason.lower()
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_position_sizer.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.risk'"

### Step 3: Write minimal implementation

```python
"""Position sizer using Half Kelly criterion with regime adjustment."""

from dataclasses import dataclass
from typing import Optional

from src.data.market_metrics import MarketMetrics


@dataclass
class SizingConfig:
    """Configuration for position sizing.

    Attributes:
        max_position_pct: Maximum single position as % of capital.
        max_total_exposure_pct: Maximum total exposure as % of capital.
        base_win_rate: Historical win rate for Kelly calculation.
        base_avg_win: Average win as % of position.
        base_avg_loss: Average loss as % of position.
    """

    max_position_pct: float = 0.10
    max_total_exposure_pct: float = 0.30
    base_win_rate: float = 0.65
    base_avg_win: float = 0.02
    base_avg_loss: float = 0.01


@dataclass
class SizingResult:
    """Result of position sizing calculation.

    Attributes:
        approved: Whether the position is allowed.
        size_pct: Position size as % of capital.
        size_btc: Position size in BTC.
        regime_multiplier: Multiplier applied for regime (1.0, 0.5, or 0.0).
        reason: Explanation if rejected or adjusted.
    """

    approved: bool
    size_pct: float
    size_btc: float
    regime_multiplier: float
    reason: str = ""


class PositionSizer:
    """Calculate position sizes using Half Kelly with regime adjustment.

    Regime adjustments:
    - DVOL < 60: Full size (multiplier 1.0)
    - DVOL 60-80: Half size (multiplier 0.5)
    - DVOL >= 80: No new positions (multiplier 0.0)
    """

    # DVOL thresholds
    DVOL_STRESSED = 60.0
    DVOL_EXTREME = 80.0

    def __init__(self, config: SizingConfig) -> None:
        """Initialize position sizer.

        Args:
            config: Sizing configuration.
        """
        self.config = config

    def calculate_kelly(self) -> float:
        """Calculate Half Kelly fraction.

        Kelly formula: f* = p - q/b
        Where:
            p = win probability
            q = loss probability (1 - p)
            b = win/loss ratio (avg_win / avg_loss)

        Returns:
            Half Kelly fraction, capped at max_position_pct.
        """
        p = self.config.base_win_rate
        q = 1.0 - p
        b = self.config.base_avg_win / self.config.base_avg_loss

        kelly = p - (q / b)
        half_kelly = kelly / 2.0

        # Cap at maximum position size
        return min(max(half_kelly, 0.0), self.config.max_position_pct)

    def get_regime_multiplier(self, metrics: MarketMetrics) -> float:
        """Get position size multiplier based on market regime.

        Args:
            metrics: Current market metrics.

        Returns:
            Multiplier: 1.0 (normal), 0.5 (stressed), 0.0 (extreme).
        """
        if metrics.dvol is None:
            return 1.0  # Default to normal if no DVOL

        if metrics.dvol >= self.DVOL_EXTREME:
            return 0.0
        elif metrics.dvol >= self.DVOL_STRESSED:
            return 0.5
        else:
            return 1.0

    def size_position(
        self,
        capital: float,
        metrics: MarketMetrics,
        current_exposure: float,
    ) -> SizingResult:
        """Calculate position size for a new trade.

        Args:
            capital: Total capital in USD.
            metrics: Current market metrics.
            current_exposure: Current exposure as fraction (0.0 to 1.0).

        Returns:
            SizingResult with approved flag and calculated size.
        """
        # Check regime
        regime_mult = self.get_regime_multiplier(metrics)

        if regime_mult == 0.0:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_btc=0.0,
                regime_multiplier=0.0,
                reason=f"Extreme fear: DVOL {metrics.dvol:.1f} >= {self.DVOL_EXTREME}",
            )

        # Check exposure limit
        remaining_exposure = self.config.max_total_exposure_pct - current_exposure

        if remaining_exposure <= 0:
            return SizingResult(
                approved=False,
                size_pct=0.0,
                size_btc=0.0,
                regime_multiplier=regime_mult,
                reason=f"Exposure limit: {current_exposure:.1%} >= {self.config.max_total_exposure_pct:.1%}",
            )

        # Calculate Kelly-based size
        base_size = self.calculate_kelly()

        # Apply regime multiplier
        adjusted_size = base_size * regime_mult

        # Cap at remaining exposure
        final_size = min(adjusted_size, remaining_exposure)

        # Convert to BTC
        size_usd = capital * final_size
        size_btc = size_usd / metrics.btc_price if metrics.btc_price > 0 else 0.0

        reason = ""
        if regime_mult < 1.0:
            reason = f"Stressed market: DVOL {metrics.dvol:.1f}, size reduced to {regime_mult:.0%}"

        return SizingResult(
            approved=True,
            size_pct=final_size,
            size_btc=size_btc,
            regime_multiplier=regime_mult,
            reason=reason,
        )
```

Also create the `__init__.py`:

```python
"""Risk management module."""

from src.risk.position_sizer import PositionSizer, SizingConfig, SizingResult

__all__ = ["PositionSizer", "SizingConfig", "SizingResult"]
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_position_sizer.py -v`
Expected: All 7 tests PASS

### Step 5: Commit

```bash
git add src/risk/ tests/unit/test_position_sizer.py
git commit -m "feat: add position sizer with Half Kelly and regime adjustment"
```

---

## Task 2: Risk Manager

**Files:**
- Create: `src/risk/risk_manager.py`
- Create: `tests/unit/test_risk_manager.py`
- Modify: `src/risk/__init__.py`

### Step 1: Write the failing test

```python
"""Tests for risk manager pre-trade validation."""

import pytest
from datetime import datetime, timezone

from src.risk.risk_manager import RiskManager, RiskConfig, ValidationResult
from src.risk.position_sizer import PositionSizer, SizingConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def risk_config() -> RiskConfig:
    """Create risk manager config."""
    return RiskConfig(
        max_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )


@pytest.fixture
def sizing_config() -> SizingConfig:
    """Create position sizer config."""
    return SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
    )


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create sample trade signal."""
    expiry = datetime.now(timezone.utc)
    return TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.25,
                bid=0.0150,
                ask=0.0165,
            )
        ],
        direction="sell",
        quantity=0.10,
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


def test_validate_signal_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal approved under normal conditions."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.0,
        open_positions=0,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    assert result.adjusted_quantity > 0


def test_validate_signal_rejected_max_positions(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when at max positions."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.20,
        open_positions=5,  # At limit
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "max positions" in result.reason.lower()


def test_validate_signal_rejected_daily_loss(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when daily loss exceeded."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=100000.0,
        current_exposure=0.10,
        open_positions=1,
        daily_pnl=-5500.0,  # -5.5% exceeds 5% limit
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "daily loss" in result.reason.lower()


def test_validate_signal_rejected_drawdown(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    sample_signal: TradeSignal,
    normal_metrics: MarketMetrics,
) -> None:
    """Test signal rejected when drawdown exceeded."""
    manager = RiskManager(risk_config, sizing_config)

    result = manager.validate_signal(
        signal=sample_signal,
        metrics=normal_metrics,
        capital=84000.0,  # 16% drawdown from peak
        current_exposure=0.10,
        open_positions=1,
        daily_pnl=0.0,
        peak_capital=100000.0,
    )

    assert result.approved is False
    assert "drawdown" in result.reason.lower()


def test_validate_close_signal_always_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    normal_metrics: MarketMetrics,
) -> None:
    """Test CLOSE signals are always approved (closing reduces risk)."""
    manager = RiskManager(risk_config, sizing_config)

    expiry = datetime.now(timezone.utc)
    close_signal = TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.CLOSE,  # Closing, not opening
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-92000-P",
                strike=92000.0,
                expiry=expiry,
                option_type="put",
            )
        ],
        direction="buy",
        quantity=0.10,
    )

    result = manager.validate_signal(
        signal=close_signal,
        metrics=normal_metrics,
        capital=84000.0,  # In drawdown
        current_exposure=0.30,  # At limit
        open_positions=5,  # At limit
        daily_pnl=-6000.0,  # Exceeds daily loss
        peak_capital=100000.0,
    )

    # CLOSE signals bypass risk checks
    assert result.approved is True


def test_can_trade_returns_false_on_halt(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
) -> None:
    """Test can_trade returns False when halted."""
    manager = RiskManager(risk_config, sizing_config)

    assert manager.can_trade() is True

    manager.halt("Test halt")

    assert manager.can_trade() is False
    assert manager.halt_reason == "Test halt"


def test_resume_trading(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
) -> None:
    """Test resume clears halt state."""
    manager = RiskManager(risk_config, sizing_config)

    manager.halt("Test halt")
    assert manager.can_trade() is False

    manager.resume()
    assert manager.can_trade() is True
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_risk_manager.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.risk.risk_manager'"

### Step 3: Write minimal implementation

```python
"""Risk manager for pre-trade validation and limits."""

from dataclasses import dataclass
from typing import Optional

from src.risk.position_sizer import PositionSizer, SizingConfig
from src.brain.signal import TradeSignal, SignalAction
from src.data.market_metrics import MarketMetrics


@dataclass
class RiskConfig:
    """Configuration for risk management.

    Attributes:
        max_positions: Maximum concurrent open positions.
        max_daily_loss_pct: Maximum daily loss as % of capital.
        max_drawdown_pct: Maximum drawdown from peak as % of peak.
    """

    max_positions: int = 5
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15


@dataclass
class ValidationResult:
    """Result of signal validation.

    Attributes:
        approved: Whether signal is approved.
        adjusted_quantity: Quantity after any adjustments.
        reason: Explanation if rejected or adjusted.
    """

    approved: bool
    adjusted_quantity: float
    reason: str = ""


class RiskManager:
    """Validates trade signals against risk limits.

    Checks:
    - Maximum open positions
    - Daily loss limit
    - Drawdown limit
    - Position sizing (via PositionSizer)
    """

    def __init__(self, config: RiskConfig, sizing_config: SizingConfig) -> None:
        """Initialize risk manager.

        Args:
            config: Risk configuration.
            sizing_config: Position sizing configuration.
        """
        self.config = config
        self.sizer = PositionSizer(sizing_config)
        self._halted = False
        self._halt_reason: Optional[str] = None

    @property
    def halt_reason(self) -> Optional[str]:
        """Get reason for current halt, if any."""
        return self._halt_reason

    def can_trade(self) -> bool:
        """Check if trading is currently allowed.

        Returns:
            False if halted, True otherwise.
        """
        return not self._halted

    def halt(self, reason: str) -> None:
        """Halt all trading.

        Args:
            reason: Reason for halt.
        """
        self._halted = True
        self._halt_reason = reason

    def resume(self) -> None:
        """Resume trading after halt."""
        self._halted = False
        self._halt_reason = None

    def validate_signal(
        self,
        signal: TradeSignal,
        metrics: MarketMetrics,
        capital: float,
        current_exposure: float,
        open_positions: int,
        daily_pnl: float,
        peak_capital: float,
    ) -> ValidationResult:
        """Validate a trade signal against risk limits.

        Args:
            signal: Trade signal to validate.
            metrics: Current market metrics.
            capital: Current capital in USD.
            current_exposure: Current exposure as fraction.
            open_positions: Number of open positions.
            daily_pnl: Today's realized + unrealized P&L.
            peak_capital: Peak capital for drawdown calculation.

        Returns:
            ValidationResult with approval status and adjusted quantity.
        """
        # CLOSE and HEDGE signals always approved (reduce risk)
        if signal.action in (SignalAction.CLOSE, SignalAction.HEDGE):
            return ValidationResult(
                approved=True,
                adjusted_quantity=signal.quantity,
                reason="Close/hedge signals always approved",
            )

        # Check if halted
        if not self.can_trade():
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Trading halted: {self._halt_reason}",
            )

        # Check max positions
        if open_positions >= self.config.max_positions:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Max positions reached: {open_positions}/{self.config.max_positions}",
            )

        # Check daily loss
        daily_loss_pct = abs(daily_pnl) / capital if capital > 0 and daily_pnl < 0 else 0
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Daily loss limit: {daily_loss_pct:.1%} >= {self.config.max_daily_loss_pct:.1%}",
            )

        # Check drawdown
        drawdown = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
        if drawdown >= self.config.max_drawdown_pct:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=f"Drawdown limit: {drawdown:.1%} >= {self.config.max_drawdown_pct:.1%}",
            )

        # Check position sizing
        sizing_result = self.sizer.size_position(capital, metrics, current_exposure)

        if not sizing_result.approved:
            return ValidationResult(
                approved=False,
                adjusted_quantity=0.0,
                reason=sizing_result.reason,
            )

        return ValidationResult(
            approved=True,
            adjusted_quantity=sizing_result.size_btc,
            reason=sizing_result.reason,
        )
```

Update `src/risk/__init__.py`:

```python
"""Risk management module."""

from src.risk.position_sizer import PositionSizer, SizingConfig, SizingResult
from src.risk.risk_manager import RiskManager, RiskConfig, ValidationResult

__all__ = [
    "PositionSizer",
    "SizingConfig",
    "SizingResult",
    "RiskManager",
    "RiskConfig",
    "ValidationResult",
]
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_risk_manager.py -v`
Expected: All 8 tests PASS

### Step 5: Commit

```bash
git add src/risk/risk_manager.py src/risk/__init__.py tests/unit/test_risk_manager.py
git commit -m "feat: add risk manager with pre-trade validation"
```

---

## Task 3: Delta Hedger

**Files:**
- Create: `src/execution/__init__.py`
- Create: `src/execution/delta_hedger.py`
- Create: `tests/unit/test_delta_hedger.py`

### Step 1: Write the failing test

```python
"""Tests for delta hedger."""

import pytest
from datetime import datetime, timezone

from src.execution.delta_hedger import DeltaHedger, HedgerConfig, HedgeSignal
from src.brain.signal import OptionContract, StrategyType


@pytest.fixture
def hedger_config() -> HedgerConfig:
    """Create hedger config."""
    return HedgerConfig(
        rebalance_threshold=0.10,
        hard_limit=0.15,
    )


@pytest.fixture
def sample_contracts() -> list[OptionContract]:
    """Create sample option contracts with deltas."""
    expiry = datetime.now(timezone.utc)
    return [
        # Short put: position delta = +0.25
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,
        ),
        # Short call: position delta = -0.20
        OptionContract(
            instrument_name="BTC-31JAN26-102000-C",
            strike=102000.0,
            expiry=expiry,
            option_type="call",
            delta=0.20,
        ),
    ]


def test_calculate_portfolio_delta_long(hedger_config: HedgerConfig) -> None:
    """Test portfolio delta calculation for long positions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.50,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.50,
        ),
    ]

    # Long straddle: position delta = sum of contract deltas
    delta = hedger.calculate_portfolio_delta(contracts, direction="buy")

    assert delta == pytest.approx(0.0, abs=0.01)


def test_calculate_portfolio_delta_short(hedger_config: HedgerConfig) -> None:
    """Test portfolio delta calculation for short positions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-97000-P",
            strike=97000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.50,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-97000-C",
            strike=97000.0,
            expiry=expiry,
            option_type="call",
            delta=0.50,
        ),
    ]

    # Short straddle: position delta = negative of sum of contract deltas
    delta = hedger.calculate_portfolio_delta(contracts, direction="sell")

    assert delta == pytest.approx(0.0, abs=0.01)


def test_needs_hedge_within_threshold(
    hedger_config: HedgerConfig,
    sample_contracts: list[OptionContract],
) -> None:
    """Test no hedge needed when delta within threshold."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.05, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=0.05)

    assert result is None


def test_needs_hedge_exceeds_threshold(hedger_config: HedgerConfig) -> None:
    """Test hedge needed when delta exceeds threshold."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.12, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=0.12)

    assert result is not None
    assert result.direction == "sell"  # Positive delta -> sell to reduce
    assert result.quantity == pytest.approx(0.12, abs=0.01)


def test_needs_hedge_negative_delta(hedger_config: HedgerConfig) -> None:
    """Test hedge for negative delta."""
    hedger = DeltaHedger(hedger_config)

    # Delta = -0.15, threshold = 0.10
    result = hedger.check_hedge_needed(portfolio_delta=-0.15)

    assert result is not None
    assert result.direction == "buy"  # Negative delta -> buy to reduce
    assert result.quantity == pytest.approx(0.15, abs=0.01)


def test_hard_limit_flag(hedger_config: HedgerConfig) -> None:
    """Test urgent flag when delta exceeds hard limit."""
    hedger = DeltaHedger(hedger_config)

    # Delta = 0.18, hard limit = 0.15
    result = hedger.check_hedge_needed(portfolio_delta=0.18)

    assert result is not None
    assert result.urgent is True


def test_add_existing_hedge(hedger_config: HedgerConfig) -> None:
    """Test accounting for existing hedge position."""
    hedger = DeltaHedger(hedger_config)

    # Portfolio delta 0.25, but we have -0.20 hedge, net = 0.05
    result = hedger.check_hedge_needed(
        portfolio_delta=0.25,
        existing_hedge_delta=-0.20,
    )

    # Net delta = 0.05, within threshold
    assert result is None


def test_calculate_portfolio_delta_with_legs(hedger_config: HedgerConfig) -> None:
    """Test delta calculation with per-leg directions."""
    hedger = DeltaHedger(hedger_config)

    expiry = datetime.now(timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-92000-P",
            strike=92000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-88000-P",
            strike=88000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
        ),
    ]
    legs_direction = ["sell", "buy"]  # Short 92k, long 88k

    # Short put @ -0.15: position delta = +0.15
    # Long put @ -0.05: position delta = -0.05
    # Net = +0.10
    delta = hedger.calculate_portfolio_delta_with_legs(contracts, legs_direction)

    assert delta == pytest.approx(0.10, abs=0.01)
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_delta_hedger.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.execution'"

### Step 3: Write minimal implementation

```python
"""Delta hedger for maintaining delta-neutral positions."""

from dataclasses import dataclass
from typing import Optional

from src.brain.signal import OptionContract


@dataclass
class HedgerConfig:
    """Configuration for delta hedger.

    Attributes:
        rebalance_threshold: Rebalance when |delta| exceeds this.
        hard_limit: Never let |delta| exceed this (urgent hedge).
    """

    rebalance_threshold: float = 0.10
    hard_limit: float = 0.15


@dataclass
class HedgeSignal:
    """Signal to execute a delta hedge.

    Attributes:
        direction: 'buy' or 'sell' BTC/perpetual.
        quantity: Amount of BTC to trade.
        target_delta: Target portfolio delta after hedge.
        urgent: True if delta exceeds hard limit.
        reason: Explanation for hedge.
    """

    direction: str
    quantity: float
    target_delta: float = 0.0
    urgent: bool = False
    reason: str = ""


class DeltaHedger:
    """Monitors portfolio delta and generates hedge signals.

    Uses perpetual futures for hedging (better liquidity than spot).
    """

    def __init__(self, config: HedgerConfig) -> None:
        """Initialize delta hedger.

        Args:
            config: Hedger configuration.
        """
        self.config = config

    def calculate_portfolio_delta(
        self,
        contracts: list[OptionContract],
        direction: str,
    ) -> float:
        """Calculate portfolio delta for uniformly directional position.

        For a position where all legs have the same direction:
        - Long position: position_delta = sum(contract_deltas)
        - Short position: position_delta = -sum(contract_deltas)

        Args:
            contracts: List of option contracts.
            direction: Overall position direction ('buy' or 'sell').

        Returns:
            Portfolio delta.
        """
        contract_delta_sum = sum(
            c.delta for c in contracts if c.delta is not None
        )

        if direction == "sell":
            return -contract_delta_sum
        return contract_delta_sum

    def calculate_portfolio_delta_with_legs(
        self,
        contracts: list[OptionContract],
        legs_direction: list[str],
    ) -> float:
        """Calculate portfolio delta for multi-leg position.

        Each leg can have its own direction:
        - Long leg: position_delta = contract_delta
        - Short leg: position_delta = -contract_delta

        Args:
            contracts: List of option contracts.
            legs_direction: Direction for each leg ('buy' or 'sell').

        Returns:
            Portfolio delta.
        """
        total_delta = 0.0

        for contract, direction in zip(contracts, legs_direction, strict=True):
            if contract.delta is None:
                continue

            if direction == "sell":
                total_delta -= contract.delta
            else:
                total_delta += contract.delta

        return total_delta

    def check_hedge_needed(
        self,
        portfolio_delta: float,
        existing_hedge_delta: float = 0.0,
    ) -> Optional[HedgeSignal]:
        """Check if delta hedge is needed.

        Args:
            portfolio_delta: Current portfolio delta from options.
            existing_hedge_delta: Delta from existing hedge positions.

        Returns:
            HedgeSignal if hedge needed, None otherwise.
        """
        net_delta = portfolio_delta + existing_hedge_delta

        if abs(net_delta) <= self.config.rebalance_threshold:
            return None

        # Determine hedge direction and size
        if net_delta > 0:
            # Long delta -> sell to reduce
            direction = "sell"
        else:
            # Short delta -> buy to reduce
            direction = "buy"

        quantity = abs(net_delta)
        urgent = abs(net_delta) > self.config.hard_limit

        reason = f"Portfolio delta {net_delta:+.3f} exceeds threshold"
        if urgent:
            reason = f"URGENT: Portfolio delta {net_delta:+.3f} exceeds hard limit"

        return HedgeSignal(
            direction=direction,
            quantity=quantity,
            target_delta=0.0,
            urgent=urgent,
            reason=reason,
        )
```

Create `src/execution/__init__.py`:

```python
"""Execution module for order management and hedging."""

from src.execution.delta_hedger import DeltaHedger, HedgerConfig, HedgeSignal

__all__ = ["DeltaHedger", "HedgerConfig", "HedgeSignal"]
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_delta_hedger.py -v`
Expected: All 8 tests PASS

### Step 5: Commit

```bash
git add src/execution/ tests/unit/test_delta_hedger.py
git commit -m "feat: add delta hedger with portfolio delta calculation"
```

---

## Task 4: Circuit Breaker

**Files:**
- Create: `src/risk/circuit_breaker.py`
- Create: `tests/unit/test_circuit_breaker.py`
- Modify: `src/risk/__init__.py`

### Step 1: Write the failing test

```python
"""Tests for circuit breaker."""

import pytest
from datetime import datetime, timezone, timedelta

from src.risk.circuit_breaker import (
    CircuitBreaker,
    BreakerConfig,
    BreakerStatus,
    BreakerEvent,
)
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def breaker_config() -> BreakerConfig:
    """Create circuit breaker config."""
    return BreakerConfig(
        daily_loss_limit_pct=0.05,
        dvol_halt_threshold=80.0,
        dvol_resume_threshold=70.0,
        api_error_threshold=3,
        api_error_window_seconds=300,
        cooldown_hours=24,
    )


def test_initial_status_active(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker starts in active state."""
    breaker = CircuitBreaker(breaker_config)

    assert breaker.status == BreakerStatus.ACTIVE
    assert breaker.can_trade() is True


def test_trip_on_daily_loss(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on daily loss."""
    breaker = CircuitBreaker(breaker_config)

    event = breaker.check_daily_loss(
        daily_pnl=-5500.0,
        capital=100000.0,
    )

    assert event is not None
    assert event.trigger == "daily_loss"
    assert breaker.status == BreakerStatus.TRIPPED
    assert breaker.can_trade() is False


def test_no_trip_within_daily_loss_limit(breaker_config: BreakerConfig) -> None:
    """Test no trip when within daily loss limit."""
    breaker = CircuitBreaker(breaker_config)

    event = breaker.check_daily_loss(
        daily_pnl=-4000.0,  # -4%, under 5% limit
        capital=100000.0,
    )

    assert event is None
    assert breaker.status == BreakerStatus.ACTIVE


def test_trip_on_dvol_spike(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on DVOL spike."""
    breaker = CircuitBreaker(breaker_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,  # Above 80 threshold
        timestamp=datetime.now(timezone.utc),
    )

    event = breaker.check_dvol(metrics)

    assert event is not None
    assert event.trigger == "dvol_spike"
    assert breaker.status == BreakerStatus.TRIPPED


def test_no_resume_until_dvol_below_resume_threshold(
    breaker_config: BreakerConfig,
) -> None:
    """Test no auto-resume until DVOL falls below resume threshold."""
    breaker = CircuitBreaker(breaker_config)

    # Trip on high DVOL
    metrics_high = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )
    breaker.check_dvol(metrics_high)
    assert breaker.status == BreakerStatus.TRIPPED

    # Still high but below trip threshold
    metrics_mid = MarketMetrics(
        btc_price=97000.0,
        dvol=75.0,  # Below 80 but above 70 resume threshold
        timestamp=datetime.now(timezone.utc),
    )

    # Shouldn't auto-resume
    assert breaker.can_resume_dvol(metrics_mid) is False

    # Below resume threshold
    metrics_low = MarketMetrics(
        btc_price=97000.0,
        dvol=65.0,  # Below 70 resume threshold
        timestamp=datetime.now(timezone.utc),
    )

    assert breaker.can_resume_dvol(metrics_low) is True


def test_trip_on_api_errors(breaker_config: BreakerConfig) -> None:
    """Test circuit breaker trips on too many API errors."""
    breaker = CircuitBreaker(breaker_config)

    # Record 3 errors (threshold)
    now = datetime.now(timezone.utc)
    breaker.record_api_error(now - timedelta(seconds=60))
    breaker.record_api_error(now - timedelta(seconds=30))
    event = breaker.record_api_error(now)

    assert event is not None
    assert event.trigger == "api_errors"
    assert breaker.status == BreakerStatus.TRIPPED


def test_api_errors_expire_outside_window(breaker_config: BreakerConfig) -> None:
    """Test old API errors don't count toward threshold."""
    breaker = CircuitBreaker(breaker_config)

    now = datetime.now(timezone.utc)

    # Old errors outside 5-minute window
    breaker.record_api_error(now - timedelta(seconds=400))
    breaker.record_api_error(now - timedelta(seconds=350))

    # Only 1 recent error
    event = breaker.record_api_error(now)

    assert event is None
    assert breaker.status == BreakerStatus.ACTIVE


def test_manual_trip_and_reset(breaker_config: BreakerConfig) -> None:
    """Test manual trip and reset."""
    breaker = CircuitBreaker(breaker_config)

    breaker.trip("manual_test", "Testing manual trip")
    assert breaker.status == BreakerStatus.TRIPPED

    breaker.reset()
    assert breaker.status == BreakerStatus.ACTIVE


def test_get_events_history(breaker_config: BreakerConfig) -> None:
    """Test event history is maintained."""
    breaker = CircuitBreaker(breaker_config)

    breaker.check_daily_loss(-6000.0, 100000.0)
    breaker.reset()
    breaker.trip("test", "Another test")

    events = breaker.get_events()

    assert len(events) == 2
    assert events[0].trigger == "daily_loss"
    assert events[1].trigger == "test"
```

### Step 2: Run test to verify it fails

Run: `pytest tests/unit/test_circuit_breaker.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.risk.circuit_breaker'"

### Step 3: Write minimal implementation

```python
"""Circuit breaker for emergency trading halts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from src.data.market_metrics import MarketMetrics


class BreakerStatus(str, Enum):
    """Circuit breaker status."""

    ACTIVE = "active"
    TRIPPED = "tripped"


@dataclass
class BreakerConfig:
    """Configuration for circuit breaker.

    Attributes:
        daily_loss_limit_pct: Trip when daily loss exceeds this %.
        dvol_halt_threshold: Trip when DVOL exceeds this.
        dvol_resume_threshold: Can resume when DVOL falls below this.
        api_error_threshold: Trip after this many errors in window.
        api_error_window_seconds: Time window for counting API errors.
        cooldown_hours: Minimum hours before auto-resume.
    """

    daily_loss_limit_pct: float = 0.05
    dvol_halt_threshold: float = 80.0
    dvol_resume_threshold: float = 70.0
    api_error_threshold: int = 3
    api_error_window_seconds: int = 300
    cooldown_hours: int = 24


@dataclass
class BreakerEvent:
    """Record of a circuit breaker event.

    Attributes:
        trigger: What triggered the event.
        message: Description of the event.
        timestamp: When it occurred.
        severity: 'warning' or 'critical'.
    """

    trigger: str
    message: str
    timestamp: datetime
    severity: str = "critical"


class CircuitBreaker:
    """Circuit breaker for emergency trading halts.

    Triggers on:
    - Daily loss exceeding limit
    - DVOL spike above threshold
    - Too many API errors in time window
    """

    def __init__(self, config: BreakerConfig) -> None:
        """Initialize circuit breaker.

        Args:
            config: Breaker configuration.
        """
        self.config = config
        self._status = BreakerStatus.ACTIVE
        self._trip_time: Optional[datetime] = None
        self._trip_reason: Optional[str] = None
        self._events: list[BreakerEvent] = []
        self._api_errors: list[datetime] = []

    @property
    def status(self) -> BreakerStatus:
        """Get current breaker status."""
        return self._status

    def can_trade(self) -> bool:
        """Check if trading is allowed.

        Returns:
            True if breaker is active, False if tripped.
        """
        return self._status == BreakerStatus.ACTIVE

    def trip(self, trigger: str, message: str) -> BreakerEvent:
        """Trip the circuit breaker.

        Args:
            trigger: What triggered the trip.
            message: Description.

        Returns:
            BreakerEvent recording the trip.
        """
        self._status = BreakerStatus.TRIPPED
        self._trip_time = datetime.now(timezone.utc)
        self._trip_reason = trigger

        event = BreakerEvent(
            trigger=trigger,
            message=message,
            timestamp=self._trip_time,
            severity="critical",
        )
        self._events.append(event)
        return event

    def reset(self) -> None:
        """Reset circuit breaker to active state."""
        self._status = BreakerStatus.ACTIVE
        self._trip_time = None
        self._trip_reason = None

    def get_events(self) -> list[BreakerEvent]:
        """Get history of breaker events.

        Returns:
            List of BreakerEvent objects.
        """
        return list(self._events)

    def check_daily_loss(
        self,
        daily_pnl: float,
        capital: float,
    ) -> Optional[BreakerEvent]:
        """Check if daily loss limit is breached.

        Args:
            daily_pnl: Today's P&L (negative for loss).
            capital: Current capital.

        Returns:
            BreakerEvent if tripped, None otherwise.
        """
        if capital <= 0 or daily_pnl >= 0:
            return None

        loss_pct = abs(daily_pnl) / capital

        if loss_pct >= self.config.daily_loss_limit_pct:
            return self.trip(
                "daily_loss",
                f"Daily loss {loss_pct:.1%} exceeds limit {self.config.daily_loss_limit_pct:.1%}",
            )

        return None

    def check_dvol(self, metrics: MarketMetrics) -> Optional[BreakerEvent]:
        """Check if DVOL exceeds halt threshold.

        Args:
            metrics: Current market metrics.

        Returns:
            BreakerEvent if tripped, None otherwise.
        """
        if metrics.dvol is None:
            return None

        if metrics.dvol >= self.config.dvol_halt_threshold:
            return self.trip(
                "dvol_spike",
                f"DVOL {metrics.dvol:.1f} exceeds halt threshold {self.config.dvol_halt_threshold}",
            )

        return None

    def can_resume_dvol(self, metrics: MarketMetrics) -> bool:
        """Check if DVOL has fallen enough to resume.

        Args:
            metrics: Current market metrics.

        Returns:
            True if DVOL below resume threshold.
        """
        if metrics.dvol is None:
            return False

        return metrics.dvol < self.config.dvol_resume_threshold

    def record_api_error(self, timestamp: Optional[datetime] = None) -> Optional[BreakerEvent]:
        """Record an API error and check threshold.

        Args:
            timestamp: When error occurred (default: now).

        Returns:
            BreakerEvent if threshold exceeded, None otherwise.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self._api_errors.append(timestamp)

        # Clean old errors outside window
        cutoff = timestamp - timedelta(seconds=self.config.api_error_window_seconds)
        self._api_errors = [t for t in self._api_errors if t > cutoff]

        if len(self._api_errors) >= self.config.api_error_threshold:
            return self.trip(
                "api_errors",
                f"{len(self._api_errors)} API errors in {self.config.api_error_window_seconds}s window",
            )

        return None
```

Update `src/risk/__init__.py`:

```python
"""Risk management module."""

from src.risk.position_sizer import PositionSizer, SizingConfig, SizingResult
from src.risk.risk_manager import RiskManager, RiskConfig, ValidationResult
from src.risk.circuit_breaker import (
    CircuitBreaker,
    BreakerConfig,
    BreakerStatus,
    BreakerEvent,
)

__all__ = [
    "PositionSizer",
    "SizingConfig",
    "SizingResult",
    "RiskManager",
    "RiskConfig",
    "ValidationResult",
    "CircuitBreaker",
    "BreakerConfig",
    "BreakerStatus",
    "BreakerEvent",
]
```

### Step 4: Run test to verify it passes

Run: `pytest tests/unit/test_circuit_breaker.py -v`
Expected: All 9 tests PASS

### Step 5: Commit

```bash
git add src/risk/circuit_breaker.py src/risk/__init__.py tests/unit/test_circuit_breaker.py
git commit -m "feat: add circuit breaker for emergency trading halts"
```

---

## Task 5: Risk Integration Tests

**Files:**
- Create: `tests/integration/test_risk_integration.py`

### Step 1: Write the failing test

```python
"""Integration tests for risk management flow."""

import pytest
from datetime import datetime, timezone

from src.risk.position_sizer import PositionSizer, SizingConfig
from src.risk.risk_manager import RiskManager, RiskConfig
from src.risk.circuit_breaker import CircuitBreaker, BreakerConfig, BreakerStatus
from src.execution.delta_hedger import DeltaHedger, HedgerConfig
from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.market_metrics import MarketMetrics


@pytest.fixture
def risk_config() -> RiskConfig:
    """Create risk config."""
    return RiskConfig(
        max_positions=5,
        max_daily_loss_pct=0.05,
        max_drawdown_pct=0.15,
    )


@pytest.fixture
def sizing_config() -> SizingConfig:
    """Create sizing config."""
    return SizingConfig(
        max_position_pct=0.10,
        max_total_exposure_pct=0.30,
    )


@pytest.fixture
def breaker_config() -> BreakerConfig:
    """Create breaker config."""
    return BreakerConfig(
        daily_loss_limit_pct=0.05,
        dvol_halt_threshold=80.0,
        dvol_resume_threshold=70.0,
    )


@pytest.fixture
def hedger_config() -> HedgerConfig:
    """Create hedger config."""
    return HedgerConfig(
        rebalance_threshold=0.10,
        hard_limit=0.15,
    )


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create sample trade signal."""
    expiry = datetime.now(timezone.utc)
    return TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=[
            OptionContract(
                instrument_name="BTC-31JAN26-90000-P",
                strike=90000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.15,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-85000-P",
                strike=85000.0,
                expiry=expiry,
                option_type="put",
                delta=-0.05,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-104000-C",
                strike=104000.0,
                expiry=expiry,
                option_type="call",
                delta=0.15,
            ),
            OptionContract(
                instrument_name="BTC-31JAN26-110000-C",
                strike=110000.0,
                expiry=expiry,
                option_type="call",
                delta=0.05,
            ),
        ],
        direction="sell",
        quantity=0.10,
        legs_direction=["sell", "buy", "sell", "buy"],
    )


def test_full_risk_flow_approved(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    breaker_config: BreakerConfig,
    sample_signal: TradeSignal,
) -> None:
    """Test full risk check flow with approved signal."""
    breaker = CircuitBreaker(breaker_config)
    manager = RiskManager(risk_config, sizing_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        timestamp=datetime.now(timezone.utc),
    )

    # Step 1: Check circuit breaker
    dvol_event = breaker.check_dvol(metrics)
    assert dvol_event is None
    assert breaker.can_trade() is True

    # Step 2: Validate signal
    result = manager.validate_signal(
        signal=sample_signal,
        metrics=metrics,
        capital=100000.0,
        current_exposure=0.10,
        open_positions=2,
        daily_pnl=500.0,
        peak_capital=100000.0,
    )

    assert result.approved is True
    assert result.adjusted_quantity > 0


def test_full_risk_flow_blocked_by_breaker(
    risk_config: RiskConfig,
    sizing_config: SizingConfig,
    breaker_config: BreakerConfig,
    sample_signal: TradeSignal,
) -> None:
    """Test risk flow blocked by circuit breaker."""
    breaker = CircuitBreaker(breaker_config)
    manager = RiskManager(risk_config, sizing_config)

    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,  # High DVOL
        timestamp=datetime.now(timezone.utc),
    )

    # Step 1: Check circuit breaker - should trip
    dvol_event = breaker.check_dvol(metrics)
    assert dvol_event is not None
    assert breaker.can_trade() is False

    # Trading should be blocked before reaching risk manager
    # In real usage, we'd check breaker.can_trade() first


def test_delta_hedger_with_iron_condor(
    hedger_config: HedgerConfig,
    sample_signal: TradeSignal,
) -> None:
    """Test delta hedger with iron condor legs."""
    hedger = DeltaHedger(hedger_config)

    # Calculate delta with per-leg directions
    # Short put -0.15: +0.15
    # Long put -0.05: -0.05
    # Short call +0.15: -0.15
    # Long call +0.05: +0.05
    # Net: +0.15 - 0.05 - 0.15 + 0.05 = 0.0
    portfolio_delta = hedger.calculate_portfolio_delta_with_legs(
        sample_signal.contracts,
        sample_signal.legs_direction,
    )

    assert portfolio_delta == pytest.approx(0.0, abs=0.01)

    # No hedge needed
    hedge = hedger.check_hedge_needed(portfolio_delta)
    assert hedge is None


def test_delta_hedger_triggers_hedge_after_price_move(
    hedger_config: HedgerConfig,
) -> None:
    """Test delta hedger triggers hedge after price move."""
    hedger = DeltaHedger(hedger_config)

    # Simulate price move - put deltas changed
    expiry = datetime.now(timezone.utc)
    moved_contracts = [
        OptionContract(
            instrument_name="BTC-31JAN26-90000-P",
            strike=90000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.25,  # Was -0.15, price dropped
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-85000-P",
            strike=85000.0,
            expiry=expiry,
            option_type="put",
            delta=-0.10,  # Was -0.05
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-104000-C",
            strike=104000.0,
            expiry=expiry,
            option_type="call",
            delta=0.08,  # Was +0.15, price dropped
        ),
        OptionContract(
            instrument_name="BTC-31JAN26-110000-C",
            strike=110000.0,
            expiry=expiry,
            option_type="call",
            delta=0.03,  # Was +0.05
        ),
    ]
    legs_direction = ["sell", "buy", "sell", "buy"]

    # Recalculate delta
    # Short put -0.25: +0.25
    # Long put -0.10: -0.10
    # Short call +0.08: -0.08
    # Long call +0.03: +0.03
    # Net: +0.25 - 0.10 - 0.08 + 0.03 = +0.10
    portfolio_delta = hedger.calculate_portfolio_delta_with_legs(
        moved_contracts,
        legs_direction,
    )

    assert portfolio_delta == pytest.approx(0.10, abs=0.01)

    # Should trigger hedge at threshold
    hedge = hedger.check_hedge_needed(portfolio_delta)
    assert hedge is not None
    assert hedge.direction == "sell"


def test_regime_sizing_integration(
    sizing_config: SizingConfig,
) -> None:
    """Test position sizing across different regimes."""
    sizer = PositionSizer(sizing_config)
    capital = 100000.0

    # Normal regime
    normal = MarketMetrics(
        btc_price=97000.0,
        dvol=52.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_normal = sizer.size_position(capital, normal, 0.0)

    # Stressed regime
    stressed = MarketMetrics(
        btc_price=97000.0,
        dvol=68.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_stressed = sizer.size_position(capital, stressed, 0.0)

    # Extreme regime
    extreme = MarketMetrics(
        btc_price=97000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )
    result_extreme = sizer.size_position(capital, extreme, 0.0)

    # Verify sizing decreases with stress
    assert result_normal.approved is True
    assert result_stressed.approved is True
    assert result_extreme.approved is False

    assert result_stressed.size_pct < result_normal.size_pct
    assert result_extreme.size_pct == 0.0
```

### Step 2: Run test to verify it fails

Run: `pytest tests/integration/test_risk_integration.py -v`
Expected: PASS (all components exist)

### Step 3: No implementation needed

All components already implemented in Tasks 1-4.

### Step 4: Run test to verify it passes

Run: `pytest tests/integration/test_risk_integration.py -v`
Expected: All 5 tests PASS

### Step 5: Commit

```bash
git add tests/integration/test_risk_integration.py
git commit -m "test: add risk management integration tests"
```

---

## Task 6: Final Verification

**Files:**
- No new files

### Step 1: Run all tests

Run: `pytest --tb=short -q`
Expected: All tests pass (previous 106 + ~37 new = ~143 tests)

### Step 2: Run mypy

Run: `mypy src/risk src/execution --strict`
Expected: No errors

### Step 3: Run ruff

Run: `ruff check src/risk src/execution tests/unit/test_position_sizer.py tests/unit/test_risk_manager.py tests/unit/test_delta_hedger.py tests/unit/test_circuit_breaker.py tests/integration/test_risk_integration.py`
Expected: All checks passed

### Step 4: Check coverage

Run: `pytest --cov=src --cov-report=term-missing --cov-fail-under=80`
Expected: Coverage >= 80%

### Step 5: Final commit

```bash
git add -A
git commit -m "chore: Phase 4 complete - risk and execution"
```

---

## Summary

Phase 4 adds:

| Component | File | Tests |
|-----------|------|-------|
| Position Sizer | `src/risk/position_sizer.py` | 7 |
| Risk Manager | `src/risk/risk_manager.py` | 8 |
| Delta Hedger | `src/execution/delta_hedger.py` | 8 |
| Circuit Breaker | `src/risk/circuit_breaker.py` | 9 |
| Integration | `tests/integration/test_risk_integration.py` | 5 |

**Total new tests:** ~37

**New modules:**
- `src/risk/` - Position sizing, risk validation, circuit breakers
- `src/execution/` - Delta hedging (order management deferred to Phase 5)
