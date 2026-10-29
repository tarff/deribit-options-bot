# Phase 2: Market Analysis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build volatility metrics calculator and market regime detector for strategy selection.

**Architecture:** The volatility module calculates IV Rank, Realized Vol, IV-RV Spread, Term Structure, and Skew from Deribit market data. The regime detector uses rule-based logic to classify market conditions and recommend strategies. All metrics are persisted as MarketSnapshot records.

**Tech Stack:** Python 3.11+, aiohttp, numpy (for volatility math), pydantic, pytest

---

## Prerequisites

- Phase 1 complete (DeribitClient, Database, Repositories)
- Install numpy: `pip install numpy` and add to requirements.txt

---

## Task 1: Add numpy Dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Step 1: Update requirements.txt**

Add to `requirements.txt`:
```
numpy>=1.26.0
```

**Step 2: Update pyproject.toml**

In `pyproject.toml`, add numpy to dependencies:
```toml
dependencies = [
    "aiohttp>=3.9.0",
    "pydantic>=2.5.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "numpy>=1.26.0",
]
```

**Step 3: Install and verify**

Run: `pip install numpy`
Run: `python -c "import numpy; print(numpy.__version__)"`
Expected: Version number printed (1.26.x or higher)

**Step 4: Commit**

```bash
git add requirements.txt pyproject.toml
git commit -m "chore: add numpy dependency for volatility calculations"
```

---

## Task 2: Extend DeribitClient with Historical Data Methods

**Files:**
- Modify: `src/data/deribit_client.py`
- Create: `tests/unit/test_deribit_historical.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_deribit_historical.py`:

```python
"""Tests for Deribit historical data methods."""

import re
import pytest
from aioresponses import aioresponses

from src.data.deribit_client import DeribitClient


@pytest.fixture
async def client():
    """Create test client."""
    c = DeribitClient(base_url="https://test.deribit.com")
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_get_tradingview_chart_data(client: DeribitClient) -> None:
    """Test fetching OHLCV data for BTC."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r".*/public/get_tradingview_chart_data\?.*"),
            payload={
                "result": {
                    "ticks": [1705363200000, 1705449600000],
                    "open": [97000.0, 97500.0],
                    "high": [98000.0, 98200.0],
                    "low": [96500.0, 97000.0],
                    "close": [97500.0, 97800.0],
                    "volume": [1000.0, 1200.0],
                    "status": "ok",
                }
            },
        )

        data = await client.get_tradingview_chart_data(
            instrument_name="BTC-PERPETUAL",
            resolution="1D",
            start_timestamp=1705363200000,
            end_timestamp=1705449600000,
        )

        assert len(data["ticks"]) == 2
        assert data["close"] == [97500.0, 97800.0]


@pytest.mark.asyncio
async def test_get_historical_volatility(client: DeribitClient) -> None:
    """Test fetching historical volatility data."""
    with aioresponses() as mocked:
        mocked.get(
            re.compile(r".*/public/get_historical_volatility\?.*"),
            payload={
                "result": [[1705363200000, 45.2], [1705449600000, 46.1]],
            },
        )

        data = await client.get_historical_volatility("BTC")

        assert len(data) == 2
        assert data[0][1] == 45.2  # First volatility value
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_deribit_historical.py -v`
Expected: FAIL with AttributeError (methods don't exist)

**Step 3: Implement the methods**

Add to `src/data/deribit_client.py` (after `get_current_dvol` method, around line 348):

```python
    async def get_tradingview_chart_data(
        self,
        instrument_name: str,
        resolution: str = "1D",
        start_timestamp: int = 0,
        end_timestamp: int = 9999999999999,
    ) -> dict[str, Any]:
        """Get OHLCV chart data for an instrument.

        Args:
            instrument_name: Instrument name (e.g., BTC-PERPETUAL).
            resolution: Candle resolution (1, 3, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1D).
            start_timestamp: Start time in milliseconds.
            end_timestamp: End time in milliseconds.

        Returns:
            Dict with ticks, open, high, low, close, volume arrays.
        """
        params = {
            "instrument_name": instrument_name,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        return cast(dict[str, Any], await self._request("GET", "/public/get_tradingview_chart_data", params))

    async def get_historical_volatility(
        self,
        currency: str = "BTC",
    ) -> list[list[float]]:
        """Get historical volatility data.

        Args:
            currency: Currency (BTC, ETH).

        Returns:
            List of [timestamp, volatility] pairs.
        """
        params = {"currency": currency}
        return cast(list[list[float]], await self._request("GET", "/public/get_historical_volatility", params))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_deribit_historical.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/data/deribit_client.py tests/unit/test_deribit_historical.py
git commit -m "feat: add historical data methods to DeribitClient"
```

---

## Task 3: Create Realized Volatility Calculator

**Files:**
- Create: `src/data/volatility.py`
- Create: `tests/unit/test_volatility.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_volatility.py`:

```python
"""Tests for volatility calculations."""

import pytest
import numpy as np

from src.data.volatility import calculate_realized_volatility, annualize_volatility


def test_calculate_realized_volatility_from_prices() -> None:
    """Test RV calculation from daily close prices."""
    # 7 days of prices with ~1% daily moves
    prices = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.5]

    rv = calculate_realized_volatility(prices)

    # Should be roughly 15-20% annualized for ~1% daily moves
    assert 10.0 < rv < 30.0


def test_calculate_realized_volatility_flat_prices() -> None:
    """Test RV is near zero for flat prices."""
    prices = [100.0, 100.0, 100.0, 100.0, 100.0]

    rv = calculate_realized_volatility(prices)

    assert rv < 1.0  # Near zero


def test_calculate_realized_volatility_insufficient_data() -> None:
    """Test RV returns None with insufficient data."""
    prices = [100.0]  # Need at least 2 prices

    rv = calculate_realized_volatility(prices)

    assert rv is None


def test_annualize_volatility() -> None:
    """Test annualization of daily volatility."""
    daily_vol = 0.01  # 1% daily

    annual_vol = annualize_volatility(daily_vol, periods_per_year=365)

    # sqrt(365) * 0.01 ≈ 0.191 (19.1%)
    assert 18.0 < annual_vol < 20.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Implement the volatility module**

Create `src/data/volatility.py`:

```python
"""Volatility calculations for market analysis."""

import math
from typing import Optional

import numpy as np


def calculate_realized_volatility(
    prices: list[float],
    annualize: bool = True,
    periods_per_year: int = 365,
) -> Optional[float]:
    """Calculate realized volatility from price series.

    Uses log returns and standard deviation method.

    Args:
        prices: List of prices (oldest first).
        annualize: Whether to annualize the result.
        periods_per_year: Number of periods per year (365 for daily).

    Returns:
        Realized volatility as percentage (e.g., 45.0 for 45%), or None if insufficient data.
    """
    if len(prices) < 2:
        return None

    # Calculate log returns
    prices_array = np.array(prices)
    log_returns = np.diff(np.log(prices_array))

    # Calculate standard deviation of returns
    daily_vol = float(np.std(log_returns, ddof=1))

    if annualize:
        return annualize_volatility(daily_vol, periods_per_year)

    return daily_vol * 100


def annualize_volatility(
    periodic_vol: float,
    periods_per_year: int = 365,
) -> float:
    """Annualize a periodic volatility figure.

    Args:
        periodic_vol: Volatility for one period (as decimal, e.g., 0.01 for 1%).
        periods_per_year: Number of periods per year.

    Returns:
        Annualized volatility as percentage.
    """
    return periodic_vol * math.sqrt(periods_per_year) * 100
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/data/volatility.py tests/unit/test_volatility.py
git commit -m "feat: add realized volatility calculator"
```

---

## Task 4: Add IV Rank Calculator

**Files:**
- Modify: `src/data/volatility.py`
- Modify: `tests/unit/test_volatility.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_volatility.py`:

```python
from src.data.volatility import (
    calculate_realized_volatility,
    annualize_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
)


def test_calculate_iv_rank() -> None:
    """Test IV Rank calculation (current vs 52-week high/low)."""
    # 52 weeks of DVOL data
    historical_iv = [40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0]  # min=40, max=70
    current_iv = 55.0

    iv_rank = calculate_iv_rank(current_iv, historical_iv)

    # (55 - 40) / (70 - 40) = 15/30 = 0.50
    assert iv_rank == pytest.approx(0.50, abs=0.01)


def test_calculate_iv_rank_at_extremes() -> None:
    """Test IV Rank at min and max."""
    historical_iv = [40.0, 50.0, 60.0]

    assert calculate_iv_rank(40.0, historical_iv) == pytest.approx(0.0)
    assert calculate_iv_rank(60.0, historical_iv) == pytest.approx(1.0)


def test_calculate_iv_rank_insufficient_data() -> None:
    """Test IV Rank returns None with no historical data."""
    assert calculate_iv_rank(50.0, []) is None
    assert calculate_iv_rank(50.0, [50.0]) is None  # Need range


def test_calculate_iv_percentile() -> None:
    """Test IV Percentile (% of days below current)."""
    historical_iv = [40.0, 45.0, 50.0, 55.0, 60.0]
    current_iv = 52.0

    percentile = calculate_iv_percentile(current_iv, historical_iv)

    # 3 out of 5 values are below 52 = 60%
    assert percentile == pytest.approx(0.60, abs=0.01)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_volatility.py::test_calculate_iv_rank -v`
Expected: FAIL with ImportError

**Step 3: Implement IV Rank and Percentile**

Add to `src/data/volatility.py`:

```python
def calculate_iv_rank(
    current_iv: float,
    historical_iv: list[float],
) -> Optional[float]:
    """Calculate IV Rank (current IV position in 52-week range).

    IV Rank = (Current IV - 52w Low) / (52w High - 52w Low)

    Args:
        current_iv: Current implied volatility.
        historical_iv: Historical IV values (e.g., 52 weeks of daily DVOL).

    Returns:
        IV Rank as decimal (0.0 to 1.0), or None if insufficient data.
    """
    if len(historical_iv) < 2:
        return None

    iv_min = min(historical_iv)
    iv_max = max(historical_iv)

    if iv_max == iv_min:
        return 0.5  # No range, return middle

    return (current_iv - iv_min) / (iv_max - iv_min)


def calculate_iv_percentile(
    current_iv: float,
    historical_iv: list[float],
) -> Optional[float]:
    """Calculate IV Percentile (% of historical readings below current).

    Args:
        current_iv: Current implied volatility.
        historical_iv: Historical IV values.

    Returns:
        IV Percentile as decimal (0.0 to 1.0), or None if insufficient data.
    """
    if not historical_iv:
        return None

    count_below = sum(1 for iv in historical_iv if iv < current_iv)
    return count_below / len(historical_iv)
```

**Step 4: Update imports in test file**

Update the imports at the top of `tests/unit/test_volatility.py`:

```python
from src.data.volatility import (
    calculate_realized_volatility,
    annualize_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: PASS (8 tests)

**Step 6: Commit**

```bash
git add src/data/volatility.py tests/unit/test_volatility.py
git commit -m "feat: add IV Rank and IV Percentile calculators"
```

---

## Task 5: Add Term Structure and Skew Calculators

**Files:**
- Modify: `src/data/volatility.py`
- Modify: `tests/unit/test_volatility.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_volatility.py`:

```python
from src.data.volatility import (
    calculate_realized_volatility,
    annualize_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
    calculate_term_structure_ratio,
    calculate_risk_reversal_skew,
)


def test_calculate_term_structure_ratio_backwardation() -> None:
    """Test term structure in backwardation (near > far)."""
    near_term_iv = 55.0  # 30 DTE
    far_term_iv = 50.0   # 90 DTE

    ratio = calculate_term_structure_ratio(near_term_iv, far_term_iv)

    # 55/50 = 1.10 (backwardation)
    assert ratio == pytest.approx(1.10, abs=0.01)


def test_calculate_term_structure_ratio_contango() -> None:
    """Test term structure in contango (far > near)."""
    near_term_iv = 48.0
    far_term_iv = 52.0

    ratio = calculate_term_structure_ratio(near_term_iv, far_term_iv)

    # 48/52 = 0.923 (contango)
    assert ratio == pytest.approx(0.923, abs=0.01)


def test_calculate_term_structure_zero_far() -> None:
    """Test term structure handles zero far-term IV."""
    assert calculate_term_structure_ratio(50.0, 0.0) is None


def test_calculate_risk_reversal_skew_call_skew() -> None:
    """Test RR skew when calls are expensive (bullish)."""
    call_iv_25d = 52.0
    put_iv_25d = 48.0

    skew = calculate_risk_reversal_skew(call_iv_25d, put_iv_25d)

    # 52 - 48 = +4 (call skew, bullish)
    assert skew == pytest.approx(4.0, abs=0.01)


def test_calculate_risk_reversal_skew_put_skew() -> None:
    """Test RR skew when puts are expensive (bearish)."""
    call_iv_25d = 48.0
    put_iv_25d = 55.0

    skew = calculate_risk_reversal_skew(call_iv_25d, put_iv_25d)

    # 48 - 55 = -7 (put skew, bearish)
    assert skew == pytest.approx(-7.0, abs=0.01)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_volatility.py::test_calculate_term_structure_ratio_backwardation -v`
Expected: FAIL with ImportError

**Step 3: Implement term structure and skew calculators**

Add to `src/data/volatility.py`:

```python
def calculate_term_structure_ratio(
    near_term_iv: float,
    far_term_iv: float,
) -> Optional[float]:
    """Calculate term structure ratio.

    Ratio = IV(near-term) / IV(far-term)
    - > 1.10: Backwardation (near-term stress)
    - < 0.95: Contango (normal market)
    - 0.95-1.05: Flat

    Args:
        near_term_iv: IV for near-term expiry (e.g., 30 DTE ATM).
        far_term_iv: IV for far-term expiry (e.g., 90 DTE ATM).

    Returns:
        Term structure ratio, or None if far_term_iv is zero.
    """
    if far_term_iv <= 0:
        return None

    return near_term_iv / far_term_iv


def calculate_risk_reversal_skew(
    call_iv_25d: float,
    put_iv_25d: float,
) -> float:
    """Calculate risk reversal skew.

    RR Skew = 25-delta Call IV - 25-delta Put IV
    - > +3: Call skew (bullish sentiment)
    - < -3: Put skew (bearish sentiment)

    Args:
        call_iv_25d: 25-delta call implied volatility.
        put_iv_25d: 25-delta put implied volatility.

    Returns:
        Risk reversal skew in volatility points.
    """
    return call_iv_25d - put_iv_25d
```

**Step 4: Update imports in test file**

Update imports at top of `tests/unit/test_volatility.py`:

```python
from src.data.volatility import (
    calculate_realized_volatility,
    annualize_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
    calculate_term_structure_ratio,
    calculate_risk_reversal_skew,
)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: PASS (13 tests)

**Step 6: Commit**

```bash
git add src/data/volatility.py tests/unit/test_volatility.py
git commit -m "feat: add term structure and risk reversal skew calculators"
```

---

## Task 6: Create MarketMetrics Data Class

**Files:**
- Create: `src/data/market_metrics.py`
- Create: `tests/unit/test_market_metrics.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_market_metrics.py`:

```python
"""Tests for MarketMetrics data class."""

import pytest
from datetime import datetime, timezone

from src.data.market_metrics import MarketMetrics


def test_market_metrics_creation() -> None:
    """Test creating MarketMetrics with all fields."""
    metrics = MarketMetrics(
        btc_price=97432.50,
        dvol=52.3,
        iv_rank=0.67,
        iv_percentile=0.72,
        rv_7d=48.2,
        rv_30d=45.1,
        iv_rv_spread=7.2,
        term_structure_ratio=1.05,
        rr_skew=-2.1,
        timestamp=datetime.now(timezone.utc),
    )

    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank == 0.67


def test_market_metrics_iv_rv_spread_property() -> None:
    """Test IV-RV spread calculation."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=55.0,
        rv_30d=45.0,
        timestamp=datetime.now(timezone.utc),
    )

    # IV-RV spread should be dvol - rv_30d = 10.0
    assert metrics.calculated_iv_rv_spread == 10.0


def test_market_metrics_defaults() -> None:
    """Test MarketMetrics with minimal required fields."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert metrics.dvol is None
    assert metrics.iv_rank is None
    assert metrics.rv_7d is None


def test_market_metrics_is_high_iv() -> None:
    """Test high IV detection helper."""
    high_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.67,
        iv_rv_spread=16.0,
        timestamp=datetime.now(timezone.utc),
    )
    low_iv = MarketMetrics(
        btc_price=97000.0,
        iv_rank=0.25,
        iv_rv_spread=5.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert high_iv.is_high_iv is True
    assert low_iv.is_high_iv is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_market_metrics.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Implement MarketMetrics**

Create `src/data/market_metrics.py`:

```python
"""Market metrics data class for volatility analysis."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class MarketMetrics:
    """Aggregated market metrics for regime detection.

    Attributes:
        btc_price: Current BTC spot price.
        dvol: Deribit Volatility Index.
        iv_rank: IV Rank (0-1, current IV position in 52-week range).
        iv_percentile: IV Percentile (0-1, % of days below current IV).
        rv_7d: 7-day realized volatility (annualized %).
        rv_30d: 30-day realized volatility (annualized %).
        iv_rv_spread: DVOL minus 30-day RV (volatility points).
        term_structure_ratio: Near-term IV / Far-term IV.
        rr_skew: Risk reversal skew (25d call IV - 25d put IV).
        timestamp: When these metrics were calculated.
    """

    btc_price: float
    timestamp: datetime
    dvol: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    rv_7d: Optional[float] = None
    rv_30d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    term_structure_ratio: Optional[float] = None
    rr_skew: Optional[float] = None

    @property
    def calculated_iv_rv_spread(self) -> Optional[float]:
        """Calculate IV-RV spread from DVOL and 30d RV."""
        if self.dvol is not None and self.rv_30d is not None:
            return self.dvol - self.rv_30d
        return None

    @property
    def is_high_iv(self) -> bool:
        """Check if currently in high IV environment.

        High IV defined as: IV Rank > 50% AND IV-RV spread > 15 points.
        """
        if self.iv_rank is None:
            return False
        spread = self.iv_rv_spread or self.calculated_iv_rv_spread or 0
        return self.iv_rank > 0.5 and spread > 15

    @property
    def is_low_iv(self) -> bool:
        """Check if currently in low IV environment.

        Low IV defined as: IV Rank < 30% AND IV-RV spread < -10 points.
        """
        if self.iv_rank is None:
            return False
        spread = self.iv_rv_spread or self.calculated_iv_rv_spread or 0
        return self.iv_rank < 0.3 and spread < -10
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_market_metrics.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/data/market_metrics.py tests/unit/test_market_metrics.py
git commit -m "feat: add MarketMetrics data class"
```

---

## Task 7: Create Regime Enum and Detector

**Files:**
- Create: `src/brain/__init__.py`
- Create: `src/brain/regime_detector.py`
- Create: `tests/unit/test_regime_detector.py`

**Step 1: Create brain package**

Create `src/brain/__init__.py`:

```python
"""Brain module for market analysis and strategy selection."""
```

**Step 2: Write the failing tests**

Create `tests/unit/test_regime_detector.py`:

```python
"""Tests for market regime detection."""

import pytest
from datetime import datetime, timezone

from src.data.market_metrics import MarketMetrics
from src.brain.regime_detector import MarketRegime, RegimeDetector


@pytest.fixture
def detector() -> RegimeDetector:
    """Create regime detector with default thresholds."""
    return RegimeDetector()


def test_regime_extreme_fear(detector: RegimeDetector) -> None:
    """Test EXTREME_FEAR detection when DVOL > 80."""
    metrics = MarketMetrics(
        btc_price=90000.0,
        dvol=85.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.EXTREME_FEAR


def test_regime_high_stress(detector: RegimeDetector) -> None:
    """Test HIGH_STRESS detection when 60 < DVOL <= 80."""
    metrics = MarketMetrics(
        btc_price=92000.0,
        dvol=70.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.HIGH_STRESS


def test_regime_high_iv_overpriced(detector: RegimeDetector) -> None:
    """Test HIGH_IV_OVERPRICED when IV Rank > 50% and spread > 15."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=55.0,
        iv_rank=0.65,
        iv_rv_spread=18.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.HIGH_IV_OVERPRICED


def test_regime_low_iv_underpriced(detector: RegimeDetector) -> None:
    """Test LOW_IV_UNDERPRICED when IV Rank < 30% and spread < -10."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=35.0,
        iv_rank=0.20,
        iv_rv_spread=-12.0,
        rv_7d=48.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.LOW_IV_UNDERPRICED


def test_regime_volatile_fair(detector: RegimeDetector) -> None:
    """Test VOLATILE_FAIR when RV(7d) > RV(30d) * 1.3 and spread near zero."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        rv_7d=60.0,
        rv_30d=42.0,  # 60 > 42 * 1.3 = 54.6
        iv_rv_spread=3.0,  # Near zero (< 5)
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.VOLATILE_FAIR


def test_regime_neutral_default(detector: RegimeDetector) -> None:
    """Test NEUTRAL when no other conditions match."""
    metrics = MarketMetrics(
        btc_price=97000.0,
        dvol=50.0,
        iv_rank=0.45,
        rv_7d=45.0,
        rv_30d=43.0,
        iv_rv_spread=5.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.NEUTRAL


def test_regime_priority_extreme_fear_first(detector: RegimeDetector) -> None:
    """Test EXTREME_FEAR takes priority over other conditions."""
    metrics = MarketMetrics(
        btc_price=85000.0,
        dvol=90.0,  # Extreme fear trigger
        iv_rank=0.95,  # Would also trigger high IV
        iv_rv_spread=25.0,
        timestamp=datetime.now(timezone.utc),
    )

    regime = detector.detect(metrics)

    assert regime == MarketRegime.EXTREME_FEAR
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_regime_detector.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 4: Implement RegimeDetector**

Create `src/brain/regime_detector.py`:

```python
"""Market regime detection based on volatility metrics."""

from enum import Enum
from typing import Optional

from src.data.market_metrics import MarketMetrics


class MarketRegime(str, Enum):
    """Market regime classification."""

    EXTREME_FEAR = "extreme_fear"
    HIGH_STRESS = "high_stress"
    HIGH_IV_OVERPRICED = "high_iv_overpriced"
    LOW_IV_UNDERPRICED = "low_iv_underpriced"
    VOLATILE_FAIR = "volatile_fair"
    NEUTRAL = "neutral"


class RegimeDetector:
    """Detects market regime from volatility metrics.

    Uses rule-based classification with priority ordering:
    1. EXTREME_FEAR: DVOL > 80 (crisis, halt trading)
    2. HIGH_STRESS: DVOL 60-80 (reduce exposure)
    3. HIGH_IV_OVERPRICED: IV Rank > 50% AND IV-RV spread > 15
    4. LOW_IV_UNDERPRICED: IV Rank < 30% AND IV-RV spread < -10
    5. VOLATILE_FAIR: RV(7d) > RV(30d) * 1.3 AND spread near zero
    6. NEUTRAL: Default (wheel strategy)
    """

    def __init__(
        self,
        dvol_halt_threshold: float = 80.0,
        dvol_reduce_threshold: float = 60.0,
        high_iv_rank_threshold: float = 0.5,
        low_iv_rank_threshold: float = 0.3,
        high_iv_spread_threshold: float = 15.0,
        low_iv_spread_threshold: float = -10.0,
        rv_spike_multiplier: float = 1.3,
        fair_spread_threshold: float = 5.0,
    ) -> None:
        """Initialize detector with thresholds.

        Args:
            dvol_halt_threshold: DVOL level to trigger EXTREME_FEAR.
            dvol_reduce_threshold: DVOL level to trigger HIGH_STRESS.
            high_iv_rank_threshold: IV Rank above this = high IV.
            low_iv_rank_threshold: IV Rank below this = low IV.
            high_iv_spread_threshold: IV-RV spread above this = overpriced.
            low_iv_spread_threshold: IV-RV spread below this = underpriced.
            rv_spike_multiplier: RV(7d) / RV(30d) ratio for volatile regime.
            fair_spread_threshold: IV-RV spread absolute value for "fair" pricing.
        """
        self.dvol_halt_threshold = dvol_halt_threshold
        self.dvol_reduce_threshold = dvol_reduce_threshold
        self.high_iv_rank_threshold = high_iv_rank_threshold
        self.low_iv_rank_threshold = low_iv_rank_threshold
        self.high_iv_spread_threshold = high_iv_spread_threshold
        self.low_iv_spread_threshold = low_iv_spread_threshold
        self.rv_spike_multiplier = rv_spike_multiplier
        self.fair_spread_threshold = fair_spread_threshold

    def detect(self, metrics: MarketMetrics) -> MarketRegime:
        """Detect current market regime.

        Args:
            metrics: Current market metrics.

        Returns:
            Detected market regime.
        """
        # Priority 1: EXTREME_FEAR (DVOL > 80)
        if metrics.dvol is not None and metrics.dvol > self.dvol_halt_threshold:
            return MarketRegime.EXTREME_FEAR

        # Priority 2: HIGH_STRESS (60 < DVOL <= 80)
        if metrics.dvol is not None and metrics.dvol > self.dvol_reduce_threshold:
            return MarketRegime.HIGH_STRESS

        # Priority 3: HIGH_IV_OVERPRICED
        if self._is_high_iv_overpriced(metrics):
            return MarketRegime.HIGH_IV_OVERPRICED

        # Priority 4: LOW_IV_UNDERPRICED
        if self._is_low_iv_underpriced(metrics):
            return MarketRegime.LOW_IV_UNDERPRICED

        # Priority 5: VOLATILE_FAIR
        if self._is_volatile_fair(metrics):
            return MarketRegime.VOLATILE_FAIR

        # Default: NEUTRAL
        return MarketRegime.NEUTRAL

    def _is_high_iv_overpriced(self, metrics: MarketMetrics) -> bool:
        """Check if IV is high and overpriced relative to RV."""
        if metrics.iv_rank is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        return (
            metrics.iv_rank > self.high_iv_rank_threshold
            and spread > self.high_iv_spread_threshold
        )

    def _is_low_iv_underpriced(self, metrics: MarketMetrics) -> bool:
        """Check if IV is low and underpriced relative to RV."""
        if metrics.iv_rank is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        return (
            metrics.iv_rank < self.low_iv_rank_threshold
            and spread < self.low_iv_spread_threshold
        )

    def _is_volatile_fair(self, metrics: MarketMetrics) -> bool:
        """Check if market is volatile but fairly priced."""
        if metrics.rv_7d is None or metrics.rv_30d is None:
            return False

        spread = metrics.iv_rv_spread or metrics.calculated_iv_rv_spread
        if spread is None:
            return False

        rv_spiking = metrics.rv_7d > metrics.rv_30d * self.rv_spike_multiplier
        fair_priced = abs(spread) < self.fair_spread_threshold

        return rv_spiking and fair_priced
```

**Step 5: Create tests/__init__.py for brain tests**

Create `tests/unit/__init__.py` if it doesn't exist (should already exist).

**Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_regime_detector.py -v`
Expected: PASS (7 tests)

**Step 7: Commit**

```bash
git add src/brain/__init__.py src/brain/regime_detector.py tests/unit/test_regime_detector.py
git commit -m "feat: add market regime detector with rule-based classification"
```

---

## Task 8: Add Strategy Recommendations to Regime Detector

**Files:**
- Modify: `src/brain/regime_detector.py`
- Modify: `tests/unit/test_regime_detector.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_regime_detector.py`:

```python
def test_get_recommended_strategy_extreme_fear(detector: RegimeDetector) -> None:
    """Test no strategy recommended during extreme fear."""
    recommendation = detector.get_recommendation(MarketRegime.EXTREME_FEAR)

    assert recommendation.strategy is None
    assert recommendation.action == "close_all"
    assert "halt" in recommendation.reason.lower()


def test_get_recommended_strategy_high_iv(detector: RegimeDetector) -> None:
    """Test iron condor recommended for high IV."""
    recommendation = detector.get_recommendation(MarketRegime.HIGH_IV_OVERPRICED)

    assert recommendation.strategy == "iron_condor"
    assert recommendation.size_multiplier == 1.0


def test_get_recommended_strategy_high_stress(detector: RegimeDetector) -> None:
    """Test reduced sizing during high stress."""
    recommendation = detector.get_recommendation(MarketRegime.HIGH_STRESS)

    assert recommendation.size_multiplier == 0.5
    assert recommendation.action == "reduce_exposure"


def test_get_recommended_strategy_neutral(detector: RegimeDetector) -> None:
    """Test wheel strategy for neutral regime."""
    recommendation = detector.get_recommendation(MarketRegime.NEUTRAL)

    assert recommendation.strategy == "wheel"
    assert recommendation.size_multiplier == 1.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_regime_detector.py::test_get_recommended_strategy_extreme_fear -v`
Expected: FAIL with AttributeError

**Step 3: Implement strategy recommendations**

Add to `src/brain/regime_detector.py` (after MarketRegime enum):

```python
from dataclasses import dataclass


@dataclass
class StrategyRecommendation:
    """Strategy recommendation based on market regime.

    Attributes:
        regime: The detected market regime.
        strategy: Recommended strategy name, or None if should not trade.
        action: Action to take (open_new, reduce_exposure, close_all).
        size_multiplier: Position size multiplier (0.0 to 1.0).
        reason: Human-readable explanation.
    """

    regime: MarketRegime
    strategy: Optional[str]
    action: str
    size_multiplier: float
    reason: str
```

Add method to `RegimeDetector` class:

```python
    def get_recommendation(self, regime: MarketRegime) -> StrategyRecommendation:
        """Get strategy recommendation for a regime.

        Args:
            regime: Market regime.

        Returns:
            Strategy recommendation with sizing and action.
        """
        recommendations = {
            MarketRegime.EXTREME_FEAR: StrategyRecommendation(
                regime=regime,
                strategy=None,
                action="close_all",
                size_multiplier=0.0,
                reason="DVOL > 80: Halt all trading, close short vol positions",
            ),
            MarketRegime.HIGH_STRESS: StrategyRecommendation(
                regime=regime,
                strategy="iron_condor",  # Defined risk only
                action="reduce_exposure",
                size_multiplier=0.5,
                reason="DVOL 60-80: Reduce position sizes by 50%, defined-risk only",
            ),
            MarketRegime.HIGH_IV_OVERPRICED: StrategyRecommendation(
                regime=regime,
                strategy="iron_condor",
                action="open_new",
                size_multiplier=1.0,
                reason="High IV Rank + positive spread: Sell premium via iron condor",
            ),
            MarketRegime.LOW_IV_UNDERPRICED: StrategyRecommendation(
                regime=regime,
                strategy="gamma_scalp",
                action="open_new",
                size_multiplier=1.0,
                reason="Low IV Rank + negative spread: Buy cheap options, gamma scalp",
            ),
            MarketRegime.VOLATILE_FAIR: StrategyRecommendation(
                regime=regime,
                strategy="gamma_scalp",
                action="open_new",
                size_multiplier=1.0,
                reason="High RV, fair IV: Gamma scalp to profit from oscillation",
            ),
            MarketRegime.NEUTRAL: StrategyRecommendation(
                regime=regime,
                strategy="wheel",
                action="open_new",
                size_multiplier=1.0,
                reason="Neutral conditions: Steady yield via wheel strategy",
            ),
        }
        return recommendations[regime]
```

**Step 4: Update imports**

At the top of `src/brain/regime_detector.py`, ensure dataclass is imported:

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.data.market_metrics import MarketMetrics
```

Update imports in `tests/unit/test_regime_detector.py`:

```python
from src.brain.regime_detector import MarketRegime, RegimeDetector, StrategyRecommendation
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_regime_detector.py -v`
Expected: PASS (11 tests)

**Step 6: Commit**

```bash
git add src/brain/regime_detector.py tests/unit/test_regime_detector.py
git commit -m "feat: add strategy recommendations to regime detector"
```

---

## Task 9: Create MarketAnalyzer Service

**Files:**
- Create: `src/data/market_analyzer.py`
- Create: `tests/unit/test_market_analyzer.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_market_analyzer.py`:

```python
"""Tests for MarketAnalyzer service."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from src.data.market_analyzer import MarketAnalyzer
from src.data.deribit_client import DeribitClient
from src.brain.regime_detector import MarketRegime


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create mock Deribit client."""
    client = AsyncMock(spec=DeribitClient)

    # Mock index price
    client.get_index_price.return_value = 97432.50

    # Mock current DVOL
    client.get_current_dvol.return_value = 52.3

    # Mock historical DVOL (52 weeks of data)
    client.get_volatility_index.return_value = [
        [1705363200000 + i * 86400000, 40.0 + i * 0.5]
        for i in range(365)
    ]

    # Mock historical prices (30 days)
    client.get_tradingview_chart_data.return_value = {
        "ticks": [1705363200000 + i * 86400000 for i in range(30)],
        "close": [95000.0 + i * 100 for i in range(30)],
    }

    return client


@pytest.fixture
def analyzer(mock_client: AsyncMock) -> MarketAnalyzer:
    """Create market analyzer with mock client."""
    return MarketAnalyzer(mock_client)


@pytest.mark.asyncio
async def test_get_current_metrics(analyzer: MarketAnalyzer, mock_client: AsyncMock) -> None:
    """Test fetching and calculating current market metrics."""
    metrics = await analyzer.get_current_metrics()

    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank is not None
    assert metrics.rv_30d is not None
    mock_client.get_index_price.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_regime(analyzer: MarketAnalyzer) -> None:
    """Test getting current market regime."""
    regime = await analyzer.get_current_regime()

    assert isinstance(regime, MarketRegime)


@pytest.mark.asyncio
async def test_analyze_returns_metrics_and_regime(analyzer: MarketAnalyzer) -> None:
    """Test full analysis returns both metrics and regime."""
    result = await analyzer.analyze()

    assert "metrics" in result
    assert "regime" in result
    assert "recommendation" in result
    assert result["metrics"].btc_price > 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_market_analyzer.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Implement MarketAnalyzer**

Create `src/data/market_analyzer.py`:

```python
"""Market analyzer service for aggregating metrics and detecting regime."""

from datetime import datetime, timezone
from typing import Any

from src.data.deribit_client import DeribitClient
from src.data.market_metrics import MarketMetrics
from src.data.volatility import (
    calculate_realized_volatility,
    calculate_iv_rank,
    calculate_iv_percentile,
)
from src.brain.regime_detector import (
    MarketRegime,
    RegimeDetector,
    StrategyRecommendation,
)


class MarketAnalyzer:
    """Aggregates market data and calculates volatility metrics.

    Fetches data from Deribit, calculates derived metrics (IV Rank, RV, etc.),
    and detects the current market regime.
    """

    def __init__(
        self,
        client: DeribitClient,
        detector: RegimeDetector | None = None,
    ) -> None:
        """Initialize market analyzer.

        Args:
            client: Deribit API client.
            detector: Regime detector (uses default if not provided).
        """
        self.client = client
        self.detector = detector or RegimeDetector()

    async def get_current_metrics(self) -> MarketMetrics:
        """Fetch current market data and calculate metrics.

        Returns:
            MarketMetrics with current values.
        """
        # Fetch current data
        btc_price = await self.client.get_index_price("btc_usd")
        current_dvol = await self.client.get_current_dvol("BTC")

        # Fetch historical DVOL for IV Rank (52 weeks)
        historical_dvol = await self._fetch_historical_dvol()

        # Fetch historical prices for RV calculation
        historical_prices = await self._fetch_historical_prices(days=30)

        # Calculate metrics
        iv_rank = calculate_iv_rank(current_dvol, historical_dvol)
        iv_percentile = calculate_iv_percentile(current_dvol, historical_dvol)
        rv_30d = calculate_realized_volatility(historical_prices)

        # Calculate 7-day RV from last 7 prices
        rv_7d = None
        if len(historical_prices) >= 7:
            rv_7d = calculate_realized_volatility(historical_prices[-7:])

        # Calculate IV-RV spread
        iv_rv_spread = None
        if rv_30d is not None:
            iv_rv_spread = current_dvol - rv_30d

        return MarketMetrics(
            btc_price=btc_price,
            dvol=current_dvol,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            rv_7d=rv_7d,
            rv_30d=rv_30d,
            iv_rv_spread=iv_rv_spread,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_current_regime(self) -> MarketRegime:
        """Get current market regime.

        Returns:
            Current market regime.
        """
        metrics = await self.get_current_metrics()
        return self.detector.detect(metrics)

    async def analyze(self) -> dict[str, Any]:
        """Perform full market analysis.

        Returns:
            Dict with metrics, regime, and recommendation.
        """
        metrics = await self.get_current_metrics()
        regime = self.detector.detect(metrics)
        recommendation = self.detector.get_recommendation(regime)

        return {
            "metrics": metrics,
            "regime": regime,
            "recommendation": recommendation,
        }

    async def _fetch_historical_dvol(self) -> list[float]:
        """Fetch 52 weeks of historical DVOL data.

        Returns:
            List of DVOL values (oldest first).
        """
        # Fetch DVOL data - returns [[timestamp, open, high, low, close], ...]
        dvol_data = await self.client.get_volatility_index(
            currency="BTC",
            resolution=86400,  # Daily
        )

        # Extract close values
        return [candle[4] if len(candle) > 4 else candle[1] for candle in dvol_data]

    async def _fetch_historical_prices(self, days: int = 30) -> list[float]:
        """Fetch historical BTC prices.

        Args:
            days: Number of days of history.

        Returns:
            List of close prices (oldest first).
        """
        data = await self.client.get_tradingview_chart_data(
            instrument_name="BTC-PERPETUAL",
            resolution="1D",
        )

        close_prices = data.get("close", [])

        # Return last N days
        if len(close_prices) > days:
            return close_prices[-days:]
        return close_prices
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_market_analyzer.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/data/market_analyzer.py tests/unit/test_market_analyzer.py
git commit -m "feat: add MarketAnalyzer service for metrics aggregation"
```

---

## Task 10: Integration Test for Full Analysis Pipeline

**Files:**
- Create: `tests/integration/test_market_analysis.py`

**Step 1: Write the integration test**

Create `tests/integration/test_market_analysis.py`:

```python
"""Integration tests for market analysis pipeline."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer
from src.data.market_metrics import MarketMetrics
from src.brain.regime_detector import MarketRegime, RegimeDetector
from src.persistence.database import Database
from src.persistence.repositories import SnapshotRepository
from src.persistence.models import MarketSnapshot


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create mock Deribit client with realistic data."""
    client = AsyncMock(spec=DeribitClient)

    # Realistic BTC price
    client.get_index_price.return_value = 97432.50

    # Current DVOL at 52.3 (moderate)
    client.get_current_dvol.return_value = 52.3

    # Historical DVOL: range 35-75 over past year
    # Current 52.3 should give IV Rank around 0.43
    client.get_volatility_index.return_value = [
        [1705363200000 + i * 86400000, 35.0 + (i % 40)]  # 35-75 range
        for i in range(365)
    ]

    # Historical prices with some volatility
    client.get_tradingview_chart_data.return_value = {
        "ticks": [1705363200000 + i * 86400000 for i in range(30)],
        "close": [95000.0 + (i * 100) + ((i % 5) * 200) for i in range(30)],
    }

    return client


@pytest.fixture
def db(tmp_path) -> Database:
    """Create test database."""
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    yield database
    database.close()


@pytest.mark.asyncio
async def test_full_analysis_pipeline(mock_client: AsyncMock, db: Database) -> None:
    """Test complete flow: fetch data -> calculate metrics -> detect regime -> persist."""
    # 1. Analyze market
    analyzer = MarketAnalyzer(mock_client)
    result = await analyzer.analyze()

    # 2. Verify metrics calculated
    metrics = result["metrics"]
    assert metrics.btc_price == 97432.50
    assert metrics.dvol == 52.3
    assert metrics.iv_rank is not None
    assert 0.0 <= metrics.iv_rank <= 1.0
    assert metrics.rv_30d is not None
    assert metrics.rv_30d > 0

    # 3. Verify regime detected
    regime = result["regime"]
    assert isinstance(regime, MarketRegime)

    # 4. Verify recommendation provided
    recommendation = result["recommendation"]
    assert recommendation.strategy is not None or recommendation.action == "close_all"

    # 5. Persist as snapshot
    snapshot_repo = SnapshotRepository(db)
    snapshot_id = snapshot_repo.save(MarketSnapshot(
        btc_price=metrics.btc_price,
        dvol=metrics.dvol,
        iv_rank=metrics.iv_rank,
        iv_percentile=metrics.iv_percentile,
        rv_7d=metrics.rv_7d,
        rv_30d=metrics.rv_30d,
        iv_rv_spread=metrics.iv_rv_spread,
        regime=regime.value,
        active_strategy=recommendation.strategy,
        timestamp=metrics.timestamp,
    ))

    # 6. Verify persisted correctly
    saved = snapshot_repo.get_latest()
    assert saved is not None
    assert saved.btc_price == 97432.50
    assert saved.regime == regime.value


@pytest.mark.asyncio
async def test_regime_transitions(mock_client: AsyncMock) -> None:
    """Test regime changes as market conditions change."""
    analyzer = MarketAnalyzer(mock_client)

    # Scenario 1: Normal market
    mock_client.get_current_dvol.return_value = 50.0
    result = await analyzer.analyze()
    # With moderate DVOL and no extreme conditions, should be NEUTRAL
    assert result["regime"] in [MarketRegime.NEUTRAL, MarketRegime.HIGH_IV_OVERPRICED]

    # Scenario 2: Fear spike
    mock_client.get_current_dvol.return_value = 85.0
    result = await analyzer.analyze()
    assert result["regime"] == MarketRegime.EXTREME_FEAR
    assert result["recommendation"].strategy is None
    assert result["recommendation"].action == "close_all"

    # Scenario 3: High stress
    mock_client.get_current_dvol.return_value = 70.0
    result = await analyzer.analyze()
    assert result["regime"] == MarketRegime.HIGH_STRESS
    assert result["recommendation"].size_multiplier == 0.5
```

**Step 2: Run the integration test**

Run: `pytest tests/integration/test_market_analysis.py -v`
Expected: PASS (2 tests)

**Step 3: Commit**

```bash
git add tests/integration/test_market_analysis.py
git commit -m "test: add integration tests for market analysis pipeline"
```

---

## Task 11: Update Main Entry Point

**Files:**
- Modify: `src/main.py`

**Step 1: Update main.py to use MarketAnalyzer**

Replace the contents of `src/main.py`:

```python
"""Entry point for the crypto options trading bot."""

import asyncio
import logging
from pathlib import Path

from src.config import load_settings
from src.persistence.database import Database
from src.persistence.repositories import SnapshotRepository
from src.persistence.models import MarketSnapshot
from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    logger.info("Crypto Options Bot starting...")

    # Load configuration
    config_path = Path("config/settings.yaml")
    if not config_path.exists():
        logger.warning("No config/settings.yaml found, using defaults")
    settings = load_settings(config_path if config_path.exists() else None)

    # Initialize database
    logger.info(f"Initializing database at {settings.database.path}")
    db = Database(settings.database.path)
    db.initialize()
    logger.info("Database initialized")

    # Initialize Deribit client
    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Initialize market analyzer
    analyzer = MarketAnalyzer(client)
    snapshot_repo = SnapshotRepository(db)

    try:
        # Perform market analysis
        logger.info("Analyzing market conditions...")
        result = await analyzer.analyze()

        metrics = result["metrics"]
        regime = result["regime"]
        recommendation = result["recommendation"]

        # Log results
        logger.info(f"BTC Price: ${metrics.btc_price:,.2f}")
        logger.info(f"DVOL: {metrics.dvol:.1f}")
        logger.info(f"IV Rank: {metrics.iv_rank:.1%}" if metrics.iv_rank else "IV Rank: N/A")
        logger.info(f"RV (30d): {metrics.rv_30d:.1f}%" if metrics.rv_30d else "RV (30d): N/A")
        logger.info(f"IV-RV Spread: {metrics.iv_rv_spread:.1f}" if metrics.iv_rv_spread else "IV-RV Spread: N/A")
        logger.info(f"Market Regime: {regime.value}")
        logger.info(f"Recommended Strategy: {recommendation.strategy or 'NONE'}")
        logger.info(f"Action: {recommendation.action}")
        logger.info(f"Reason: {recommendation.reason}")

        # Persist snapshot
        snapshot_repo.save(MarketSnapshot(
            btc_price=metrics.btc_price,
            dvol=metrics.dvol,
            iv_rank=metrics.iv_rank,
            iv_percentile=metrics.iv_percentile,
            rv_7d=metrics.rv_7d,
            rv_30d=metrics.rv_30d,
            iv_rv_spread=metrics.iv_rv_spread,
            regime=regime.value,
            active_strategy=recommendation.strategy,
            timestamp=metrics.timestamp,
        ))
        logger.info("Market snapshot saved to database")

        logger.info("Phase 2 complete. Ready for Phase 3 (Strategy Implementation).")

    except Exception as e:
        logger.error(f"Error during market analysis: {e}")
        raise
    finally:
        await client.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Verify syntax is correct**

Run: `python -m py_compile src/main.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: update main.py to use MarketAnalyzer for regime detection"
```

---

## Task 12: Final Verification and Cleanup

**Files:**
- All source and test files

**Step 1: Run full test suite**

Run: `pytest -v --tb=short`
Expected: All tests pass (should be ~30+ tests)

**Step 2: Run type checking**

Run: `python -m mypy src --ignore-missing-imports`
Expected: Success (0 errors)

**Step 3: Run linting**

Run: `python -m ruff check src tests`
Expected: All checks passed

**Step 4: Run with coverage**

Run: `pytest --cov=src --cov-report=term-missing`
Expected: Coverage report showing coverage percentage

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: Phase 2 complete - Market Analysis implementation"
```

---

## Summary

Phase 2 implements the market analysis layer:

| Task | Component | Description |
|------|-----------|-------------|
| 1 | Dependencies | Add numpy for volatility math |
| 2 | DeribitClient | Historical data methods |
| 3 | volatility.py | Realized volatility calculator |
| 4 | volatility.py | IV Rank and Percentile |
| 5 | volatility.py | Term structure and skew |
| 6 | MarketMetrics | Aggregated metrics dataclass |
| 7 | RegimeDetector | Rule-based regime classification |
| 8 | RegimeDetector | Strategy recommendations |
| 9 | MarketAnalyzer | Service combining all components |
| 10 | Integration | Full pipeline test |
| 11 | main.py | Updated entry point |
| 12 | Verification | Tests, types, linting |

**New Files Created:**
- `src/data/volatility.py`
- `src/data/market_metrics.py`
- `src/data/market_analyzer.py`
- `src/brain/__init__.py`
- `src/brain/regime_detector.py`
- `tests/unit/test_volatility.py`
- `tests/unit/test_market_metrics.py`
- `tests/unit/test_market_analyzer.py`
- `tests/unit/test_regime_detector.py`
- `tests/unit/test_deribit_historical.py`
- `tests/integration/test_market_analysis.py`

**Ready for Phase 3:** Strategy implementations (Wheel, Iron Condor, Vol Arb, Gamma Scalp)
