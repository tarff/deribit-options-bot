# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autonomous BTC options trading bot for Deribit exchange. Dynamically selects between yield strategies (Wheel, Iron Condor) and alpha strategies (Volatility Arbitrage, Gamma Scalping) based on real-time market regime detection.

## Commands

```bash
# Run all tests
pytest

# Run single test file
pytest tests/unit/test_volatility.py

# Run single test function
pytest tests/unit/test_volatility.py::test_calculate_iv_rank -v

# Run with coverage
pytest --cov=src --cov-report=html

# Type checking
mypy src/

# Linting
ruff check src/ tests/

# Fix lint issues
ruff check --fix src/ tests/

# Run the bot (requires config/settings.yaml)
python -m src.main
```

## Architecture

### Data Flow
```
DeribitClient → MarketAnalyzer → RegimeDetector → StrategySelector → Strategy → Signal
                     ↓                                                              ↓
               MarketMetrics                                              RiskManager → Execution
```

### Core Layers

**Data Layer** (`src/data/`)
- `deribit_client.py`: Async REST client for Deribit API (auth, market data, orders)
- `market_metrics.py`: MarketMetrics dataclass with BTC price, DVOL, IV rank, RV, spreads
- `volatility.py`: IV rank, realized volatility, IV-RV spread calculations
- `option_selector.py`: Find options by delta, strike, DTE

**Brain Layer** (`src/brain/`)
- `regime_detector.py`: Rule-based classification into 6 regimes (EXTREME_FEAR, HIGH_STRESS, HIGH_IV_OVERPRICED, LOW_IV_UNDERPRICED, VOLATILE_FAIR, NEUTRAL)
- `strategy_selector.py`: Maps MarketRegime → StrategyType
- `signal.py`: TradeSignal, OptionContract, SignalAction, StrategyType enums

**Strategy Layer** (`src/strategies/`)
- `base.py`: BaseStrategy ABC with `evaluate()` (entry) and `manage()` (exit) methods
- `wheel.py`: CSP → assignment → covered call cycle
- `iron_condor.py`: 4-leg defined risk spread
- `vol_arb.py`: IV-RV spread trading with delta hedging
- `gamma_scalp.py`: Long gamma with delta scalping

**Risk Layer** (`src/risk/`)
- `position_sizer.py`: Half Kelly with DVOL regime adjustment (1.0x/0.5x/0.0x)
- `risk_manager.py`: Pre-trade validation (positions, daily loss, drawdown limits)
- `circuit_breaker.py`: Emergency halts (daily loss, DVOL spike, API errors)

**Execution Layer** (`src/execution/`)
- `delta_hedger.py`: Portfolio delta calculation, hedge signals with rebalance threshold

**Persistence Layer** (`src/persistence/`)
- `database.py`: SQLite connection and initialization
- `models.py`: Pydantic models (Trade, Position, MarketSnapshot, RiskEvent)
- `repositories.py`: CRUD operations with repository pattern

### Key Patterns

- All strategies inherit from `BaseStrategy` and implement `evaluate()` and `manage()`
- Market data flows through `MarketMetrics` dataclass
- Trade execution uses `TradeSignal` with `SignalAction` enum (OPEN, CLOSE, ADJUST, HEDGE)
- Risk validation checks signals before execution; CLOSE/HEDGE always approved

### Regime → Strategy Mapping
| Regime | Strategy | Position Sizing |
|--------|----------|-----------------|
| EXTREME_FEAR (DVOL > 80) | None | 0.0x (halt) |
| HIGH_STRESS (DVOL 60-80) | Iron Condor | 0.5x |
| HIGH_IV_OVERPRICED | Iron Condor | 1.0x |
| LOW_IV_UNDERPRICED | Gamma Scalp | 1.0x |
| VOLATILE_FAIR | Gamma Scalp | 1.0x |
| NEUTRAL | Calendar Spread | 1.0x |

## Configuration

Copy `config/settings.example.yaml` to `config/settings.yaml`:
- `deribit.base_url`: Use `https://test.deribit.com` for paper trading
- `risk.*`: Position limits, DVOL thresholds, daily loss limits

## Testing

- Unit tests in `tests/unit/` mirror `src/` structure
- Integration tests in `tests/integration/`
- Uses `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock Deribit responses with `aioresponses`
