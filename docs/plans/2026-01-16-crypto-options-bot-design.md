# Crypto Options Trading Bot - Design Document

*Created: 2026-01-16*

---

## Overview

A fully autonomous BTC options trading bot that dynamically selects between yield strategies (Wheel, Iron Condors) and alpha strategies (Volatility Arbitrage, Gamma Scalping) based on real-time market conditions.

### Key Decisions

| Aspect | Decision |
|--------|----------|
| **Objective** | Yield generation + Alpha generation |
| **Exchange** | Deribit (extensible for OKX, others) |
| **Asset** | BTC only (extensible for ETH) |
| **Automation** | Fully autonomous 24/7 |
| **Risk profile** | Moderate (10% per position, 30% total, Half Kelly) |
| **Yield strategies** | Wheel, Iron Condor |
| **Alpha strategies** | Volatility Arbitrage, Gamma Scalping |
| **Regime detection** | Rule-based (IV Rank, DVOL, RV, IV-RV spread, Term Structure, Skew) |
| **Position sizing** | Half Kelly, capped at 10% per position |
| **DVOL thresholds** | 2-tier: 60+ reduce, 80+ halt |
| **Monitoring** | Dashboard + Telegram + Prometheus/Grafana |
| **Tech stack** | Python, SQLite, Docker |
| **Deployment** | Local dev → VPS production |

### v2 Features (Deferred)
- Calendar Spread strategy (term structure arbitrage)
- Event-Driven strategy (halving, ETF plays)
- VPIN order flow toxicity monitoring
- Full funding rate P&L tracking
- Slippage estimation from order book depth

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CRYPTO OPTIONS BOT                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ DATA SERVICE │    │   BRAIN      │    │  EXECUTION ENGINE    │  │
│  │              │───▶│              │───▶│                      │  │
│  │ • WebSocket  │    │ • Regime     │    │ • Order management   │  │
│  │ • Market data│    │ • Strategy   │    │ • Position tracking  │  │
│  │ • IV surface │    │ • Signals    │    │ • Delta hedging      │  │
│  │ • Greeks calc│    │ • Risk check │    │ • Fill monitoring    │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
│         │                   │                      │                │
│         └───────────────────┴──────────────────────┘                │
│                             │                                       │
│                    ┌────────▼────────┐                              │
│                    │    DATABASE     │                              │
│                    │    (SQLite)     │                              │
│                    │ • Trades        │                              │
│                    │ • Positions     │                              │
│                    │ • Market snaps  │                              │
│                    │ • Performance   │                              │
│                    └─────────────────┘                              │
│                             │                                       │
│         ┌───────────────────┼───────────────────┐                   │
│         ▼                   ▼                   ▼                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐         │
│  │ DASHBOARD   │    │  ALERTING   │    │    METRICS      │         │
│  │ (Web UI)    │    │ (Telegram)  │    │  (Prometheus)   │         │
│  └─────────────┘    └─────────────┘    └─────────────────┘         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   DERIBIT API   │
                    │  REST + WebSocket│
                    └─────────────────┘
```

### Core Behavior

```
┌─────────────────────────────────────────────────────────────┐
│                    MARKET REGIME DETECTOR                    │
│  Inputs: IV Rank, DVOL, Realized Vol, IV-RV Spread          │
│  Output: Current regime + recommended strategy               │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │   YIELD     │ │   ALPHA     │ │  DEFENSIVE  │
    │  Wheel      │ │  Vol Arb    │ │  Reduce     │
    │  Iron Condor│ │  Gamma Scalp│ │  Exposure   │
    └─────────────┘ └─────────────┘ └─────────────┘
```

---

## Market Regime Detection

### Metrics Collected

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| IV Rank | Deribit options chain | Every 5 min |
| IV Percentile | Deribit (52-week range) | Every 5 min |
| DVOL | Deribit volatility index | Real-time WebSocket |
| Realized Vol (7d/30d) | Calculated from BTC price | Every 5 min |
| IV-RV Spread | IV minus 30d RV | Every 5 min |
| Term Structure | Near-term ATM IV vs Far-term ATM IV | Every 5 min |
| Risk Reversal Skew | Δ25 Call IV − Δ25 Put IV | Every 5 min |

### Term Structure Analysis

The **term structure** shows IV across different expirations at ATM strikes:

```
Term Structure Ratio = IV(30 DTE) / IV(90 DTE)

IF ratio > 1.10:
    → BACKWARDATION: Near-term stress expected
    → Near-term options expensive relative to far-term

IF ratio < 0.95:
    → CONTANGO: Normal/calm market
    → Far-term options expensive (typical state)

IF ratio ≈ 1.0 (0.95-1.05):
    → FLAT: No significant term structure signal
```

### Volatility Skew Analysis

The **Risk Reversal (RR) Skew** measures sentiment via put/call IV differential:

```
RR Skew = Δ25 Call IV − Δ25 Put IV

IF RR Skew > +3:
    → CALL SKEW: Bullish sentiment, upside demand
    → Favor: Selling OTM calls, bullish spreads

IF RR Skew < -3:
    → PUT SKEW: Bearish sentiment, downside hedging demand
    → Favor: Selling OTM puts cautiously, bear spreads

IF RR Skew flips sign (was positive, now negative):
    → SENTIMENT SHIFT: Major signal
    → ACTION: Reduce short put exposure immediately
```

### Regime Classification Rules

```
# PRIMARY REGIME DETECTION (evaluated in order)

IF DVOL > 80:
    → REGIME: "Extreme Fear"
    → ACTION: Close short vol positions, no new trades
    → Wait for DVOL < 70 before resuming

IF DVOL > 60 AND DVOL <= 80:
    → REGIME: "High Stress"
    → ACTION: Reduce position sizes by 50%, no new short vol
    → Favor defined-risk spreads (iron condors over naked)

IF IV Rank > 50% AND IV-RV Spread > 15 points:
    → REGIME: "High IV, Overpriced"
    → ACTION: Sell premium (Iron Condor, Wheel)
    → Note: Check RR Skew - if negative, favor puts over calls

IF IV Rank < 30% AND IV-RV Spread < -10 points:
    → REGIME: "Low IV, Underpriced"
    → ACTION: Buy options (Gamma Scalp, Vol Arb long)
    → Requires: RV(7d) > 40% for sufficient movement

IF RV(7d) > RV(30d) * 1.3 AND IV-RV Spread < 5:
    → REGIME: "Volatile, Fair Priced"
    → ACTION: Gamma scalping (profit from oscillation)

IF RR Skew flipped negative (was > 0, now < -3):
    → MODIFIER: "Bearish Sentiment Shift"
    → ACTION: Close/reduce short puts, favor put credit spreads

IF Term Structure Ratio > 1.10 (Backwardation):
    → MODIFIER: "Near-Term Stress"
    → ACTION: Avoid selling near-term options
    → Note: v2 will add calendar spread strategy for this

DEFAULT:
    → REGIME: "Neutral"
    → ACTION: Wheel strategy (steady yield)
```

### Strategy Mapping

| Regime | Primary Strategy | Rationale |
|--------|-----------------|-----------|
| High IV, Overpriced | Iron Condor | Capture rich premium, expect IV crush |
| Low IV, Underpriced | Gamma Scalp | Cheap options, profit from movement |
| Volatile, Fair Priced | Gamma Scalp | High RV = more scalping opportunities |
| Extreme Fear | Close positions | Preserve capital, avoid blow-ups |
| High Stress | Reduce exposure | Limited exposure, wait for clarity |
| Neutral | Wheel | Steady premium collection |

---

## Strategy Implementations

### Strategy 1: The Wheel

**Entry conditions:**
- Regime is "Neutral" or no open wheel position
- IV Rank > 30% (decent premium available)

**Execution cycle:**
```
Phase 1: SELL CASH-SECURED PUT
  - Strike: 5-10% OTM (delta ~0.25-0.30)
  - Expiry: 30-45 DTE (theta sweet spot)
  - Size: Half Kelly, max 10% of capital at risk

  IF expires worthless → collect premium, repeat Phase 1
  IF assigned → move to Phase 2

Phase 2: SELL COVERED CALL
  - Strike: 5-10% OTM from assignment price (or break-even)
  - Expiry: 30-45 DTE

  IF expires worthless → collect premium, repeat Phase 2
  IF called away → collect premium + gains, return to Phase 1
```

**Exit rules:**
- Close at 50% profit (buy back cheap)
- Close if regime shifts to "Extreme Fear"
- Roll if <7 DTE and position is profitable

---

### Strategy 2: Iron Condor

**Entry conditions:**
- Regime is "High IV, Overpriced"
- IV Rank > 50%
- No major events in next 7 days (expiry, FOMC, etc.)

**Execution:**
```
SELL OTM PUT  @ delta ~0.15 (support level)
BUY OTM PUT   @ delta ~0.05 (protection)
SELL OTM CALL @ delta ~0.15 (resistance level)
BUY OTM CALL  @ delta ~0.05 (protection)

Expiry: 30-45 DTE
Width: ~5% between short and long strikes
```

**Management:**
- Close at 50% of max profit
- Delta 0.25 on short strike: WARNING, prepare to adjust or roll
- Delta 0.30 on short strike OR price within 3%: CLOSE wing, roll, or close entire
- Close entire position if tested (price breaches short strike)

---

### Strategy 3: Volatility Arbitrage

**Entry conditions:**
- IV-RV Spread > 15 points (IV overpriced → sell vol) — accounts for variance risk premium
- IV-RV Spread < -10 points (IV underpriced → buy vol) — genuinely cheap options
- AND IV Rank > 50% (for sell vol) or IV Rank < 30% (for buy vol)

**Execution (Sell Vol case - most common):**
```
SELL ATM STRADDLE (or strangle)
  - Sell ATM Call + Sell ATM Put
  - Expiry: 14-30 DTE
  - Delta hedge immediately with perpetual futures

MAINTAIN DELTA NEUTRAL
  - Rebalance when portfolio delta exceeds ±0.10
  - Hedge using Deribit perpetual (better liquidity than spot)
  - IMPORTANT: Track funding rate impact on hedge P&L (see below)
```

**Execution (Buy Vol case - less common):**
```
BUY ATM STRADDLE
  - Buy ATM Call + Buy ATM Put
  - Expiry: 30-45 DTE (more time for vol to realize)
  - Delta hedge as above
```

**Funding Rate Impact on Delta Hedges:**
```
Perpetual funding rates can be ±0.1% every 8 hours during high volatility.
Over a 30-day position: 90 funding periods × 0.05% avg = 4.5% of hedge notional

FUNDING COST CALCULATION:
  funding_cost = hedge_size_btc × funding_rate × num_periods

  Example: 0.5 BTC hedge × 0.03% × 90 periods = 1.35% cost

STRATEGY ADJUSTMENTS:
  - If structurally long perps (short delta options): Prefer negative funding periods
  - If structurally short perps (long delta options): Prefer positive funding periods
  - Factor expected funding into strategy P&L projections
  - Consider spot + futures basis trade if funding consistently unfavorable
```

**Exit rules:**
- Close when IV-RV spread normalizes (crosses zero)
- Close at 30% profit or 15% loss (AFTER accounting for funding costs)
- Max hold: 14 days (avoid excessive theta decay on long vol)
- Exit early if cumulative funding exceeds 2% of position value

---

### Strategy 4: Gamma Scalping

**Entry conditions:**
- Regime is "Volatile, Fair Priced" or "Low IV, Underpriced"
- RV(7d) > 40% annualized (enough movement to scalp)

**Execution:**
```
BUY ATM STRADDLE
  - Expiry: 14-21 DTE (balance gamma vs theta)
  - Establish delta-neutral position

SCALPING LOOP (continuous):
  Every price move of X% (calibrated to gamma):
    IF delta > +0.10: Sell BTC perp to flatten
    IF delta < -0.10: Buy BTC perp to flatten

  Lock in realized gains from hedging
  Theta decays, but scalping profits offset if RV > IV
```

**Exit rules:**
- Close if RV drops below IV (scalping edge gone)
- Close at 7 DTE (gamma decay accelerates)
- Close if cumulative scalp P&L < -theta burn for 2 days

**Key difference from Vol Arb:**
- Vol Arb: Bet on IV-RV convergence, hedge to neutralize
- Gamma Scalp: Bet on continued high RV, actively profit from each hedge

---

## Risk Management

### Position Limits

| Limit | Value | Action if Breached |
|-------|-------|-------------------|
| Max single position | 10% of capital | Reject new trade |
| Max total exposure | 30% of capital | Reject new trade |
| Max positions open | 5 concurrent | Queue new signals |
| Max daily loss | 5% of capital | Halt trading for 24h |
| Max drawdown | 15% from peak | Halt trading, alert |

### Per-Strategy Risk Rules

```
WHEEL:
  - Max 1 wheel cycle active at a time
  - Assignment triggers covered call, not additional put
  - If BTC drops >20% while holding, pause new puts

IRON CONDOR:
  - Max 2 iron condors at different expiries
  - Delta 0.25 on short strike: WARNING, prepare to adjust
  - Delta 0.30 on short strike: CLOSE wing or roll
  - Close if short strike breached (don't hope for recovery)
  - No iron condors if DVOL > 60

VOL ARB / GAMMA SCALP:
  - Delta must stay within ±0.15 at all times
  - Auto-hedge triggers at ±0.10 (don't wait)
  - Max loss per vol trade: 2% of capital (hard stop)
  - For gamma scalp: exit if RV < IV for 3 consecutive days
```

### Delta Hedging

```
HEDGING RULES:
  - Rebalance when portfolio delta exceeds ±0.10
  - Hard limit: never let delta exceed ±0.15
  - Use Deribit perpetual for hedging (better liquidity than spot)

FUNDING RATE NOTE:
  - Perpetual funding can be ±0.1% every 8 hours
  - Over 30 days: ~1-2% of hedge notional in funding costs
  - Factor this into P&L expectations for vol arb/gamma scalp
  - v2: Add detailed funding tracking
```

### Circuit Breakers

```
IF daily_pnl < -5%:
    → Close all positions, halt for 24 hours
    → Send CRITICAL alert

IF DVOL spikes > 100:
    → Close all short vol positions immediately
    → Switch to defensive mode

IF exchange API errors > 3 in 5 minutes:
    → Pause trading, alert, wait for manual review

IF position Greeks unavailable:
    → Close delta-sensitive positions (can't hedge blind)
```

### Position Sizing (Half Kelly)

```python
def calculate_position_size(win_rate, avg_win, avg_loss, capital):
    """
    Half Kelly sizing with 10% cap.
    """
    kelly = win_rate - ((1 - win_rate) / (avg_win / avg_loss))
    half_kelly = kelly / 2
    position = capital * half_kelly
    return min(position, capital * 0.10)  # Cap at 10%
```

**Regime Adjustment:**
- DVOL > 80: No new positions
- DVOL 60-80: Reduce size by 50%
- Normal: Full size (up to 10%)

---

## Data Flow & Main Loop

### Startup Sequence

```
1. Load configuration (API keys, risk limits, thresholds)
2. Initialize database, create tables if needed
3. Connect to Deribit WebSocket
4. Fetch current positions from exchange
5. Reconcile local state with exchange state
6. Calculate initial Greeks for any open positions
7. Start main loop
8. Start dashboard server
9. Send "Bot started" alert
```

### Main Loop (runs every 5 minutes)

```python
async def main_loop():
    while True:
        # 1. Collect market data
        market_data = await data_service.get_snapshot()
        # Contains: BTC price, IV surface, DVOL, option chains

        # 2. Calculate metrics
        metrics = volatility_calculator.compute(market_data)
        # Contains: IV Rank, IV Percentile, RV(7d), RV(30d), IV-RV spread

        # 3. Detect regime
        regime = regime_detector.classify(metrics)
        # Returns: "High IV", "Low IV", "Volatile", "Extreme Fear", "Neutral"

        # 4. Check risk limits
        if not risk_manager.can_trade():
            log("Risk limits breached, skipping cycle")
            await sleep(300)
            continue

        # 5. Get strategy recommendation
        strategy, params = strategy_selector.select(regime, metrics)

        # 6. Generate signal (if any)
        signal = strategy.evaluate(market_data, params)

        # 7. Execute if signal present
        if signal:
            risk_manager.validate(signal)  # Throws if rejected
            await execution_engine.execute(signal)

        # 8. Manage existing positions
        await position_manager.check_exits()
        await delta_hedger.rebalance_if_needed()

        # 9. Persist state
        await database.save_snapshot(market_data, metrics, regime)

        # 10. Export metrics
        prometheus_exporter.update(metrics, positions, pnl)

        await sleep(300)  # 5 minutes
```

### Real-Time Handlers (WebSocket)

```python
# These run independently of main loop

async def on_price_update(price):
    # Check if delta hedge needed (gamma scalp / vol arb)
    if delta_hedger.needs_rebalance(price):
        await delta_hedger.execute_hedge()

async def on_order_fill(fill):
    position_tracker.update(fill)
    await telegram.send(f"Order filled: {fill}")

async def on_position_liquidation(event):
    circuit_breaker.trigger("Liquidation detected")
    await telegram.send_critical("LIQUIDATION - Bot halted")
```

---

## Monitoring & Alerting

### Dashboard (Web UI)

```
┌─────────────────────────────────────────────────────────────┐
│  CRYPTO OPTIONS BOT - Dashboard              Status: ● LIVE │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  MARKET CONDITIONS                 ACCOUNT                  │
│  ├─ BTC Price:    $97,432          ├─ Capital:   $50,000    │
│  ├─ DVOL:         52.3             ├─ Exposure:  18.4%      │
│  ├─ IV Rank:      67%              ├─ Open PnL:  +$412      │
│  ├─ RV (30d):     48.2%            ├─ Daily PnL: +$89       │
│  └─ IV-RV Spread: +4.1             └─ Drawdown:  2.1%       │
│                                                             │
│  CURRENT REGIME: High IV, Overpriced                        │
│  ACTIVE STRATEGY: Iron Condor                               │
│                                                             │
│  OPEN POSITIONS                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Type       │ Strike │ Expiry  │ Delta │ PnL        │    │
│  ├────────────┼────────┼─────────┼───────┼────────────┤    │
│  │ Short Put  │ 92,000 │ 14 DTE  │ -0.18 │ +$142      │    │
│  │ Long Put   │ 88,000 │ 14 DTE  │ +0.05 │ -$31       │    │
│  │ Short Call │ 103,000│ 14 DTE  │ -0.16 │ +$98       │    │
│  │ Long Call  │ 107,000│ 14 DTE  │ +0.04 │ -$22       │    │
│  └─────────────────────────────────────────────────────┘    │
│  Portfolio Greeks: Δ -0.03 | Γ +0.002 | Θ +$47/day         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Telegram Alerts

| Event | Alert Level | Example Message |
|-------|-------------|-----------------|
| Trade executed | INFO | `✅ Sold BTC-28FEB-92000-P @ $320` |
| Position closed | INFO | `📤 Closed iron condor +$187 (52% profit)` |
| Regime change | INFO | `📊 Regime: Neutral → High IV` |
| Delta hedge | DEBUG | `⚖️ Hedged: Sold 0.02 BTC perp` |
| Risk limit warning | WARN | `⚠️ Exposure at 28% (limit 30%)` |
| Circuit breaker | CRITICAL | `🚨 Daily loss -5.2% - HALTED` |
| Exchange error | CRITICAL | `❌ Deribit API down - paused` |

### Scheduled Position Summary (every 4 hours + on-demand)

```
📊 POSITION CHECK - 2026-01-16 14:00 UTC

ACTIVE STRATEGIES:
├─ Iron Condor (IC-001)     Status: Running
├─ Wheel (WHL-002)          Status: Phase 1 (CSP)
└─ Gamma Scalp              Status: Inactive

OPEN POSITIONS:
┌────────────────────────────────────────────────────┐
│ IRON CONDOR (IC-001)           Opened: 3 days ago │
├────────────────────────────────────────────────────┤
│ Short Put   92,000  │ 14 DTE │ Δ -0.18 │ +$142   │
│ Long Put    88,000  │ 14 DTE │ Δ +0.05 │ -$31    │
│ Short Call 103,000  │ 14 DTE │ Δ -0.16 │ +$98    │
│ Long Call  107,000  │ 14 DTE │ Δ +0.04 │ -$22    │
│ Net PnL: +$187 (52% of max)                       │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│ WHEEL (WHL-002)               Opened: 7 days ago  │
├────────────────────────────────────────────────────┤
│ Short Put   94,000  │ 21 DTE │ Δ -0.24 │ +$225   │
│ Net PnL: +$225 (61% of max)                       │
└────────────────────────────────────────────────────┘

PORTFOLIO SUMMARY:
├─ Total Exposure: 18.4%
├─ Net Delta: -0.03
├─ Daily Theta: +$47
└─ Unrealized PnL: +$412
```

### Telegram Commands

| Command | Response |
|---------|----------|
| `/status` | Current regime, active strategies, quick PnL |
| `/positions` | Full position breakdown (as above) |
| `/risk` | Current exposure, limits, drawdown |
| `/pause` | Pause bot, close no positions |
| `/resume` | Resume trading |
| `/kill` | Emergency: close all positions, halt |

### Prometheus Metrics

```
# Performance
bot_pnl_total{strategy="wheel"} 1247.50
bot_pnl_daily 89.20
bot_drawdown_percent 2.1
bot_sharpe_ratio_30d 1.84

# Positions
bot_positions_open 4
bot_exposure_percent 18.4
bot_delta_net -0.03

# Market
bot_btc_price 97432
bot_dvol 52.3
bot_iv_rank 0.67
bot_regime{name="high_iv"} 1

# System
bot_api_latency_ms 45
bot_last_cycle_timestamp 1705420800
bot_errors_total{type="api"} 0
```

---

## Project Structure

```
options-trading-bot/
├── config/
│   ├── settings.yaml           # Thresholds, limits, API config
│   ├── strategies.yaml         # Strategy-specific parameters
│   └── alerts.yaml             # Telegram config, alert rules
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point, startup sequence
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── deribit_client.py   # REST + WebSocket connection
│   │   ├── market_data.py      # Price, IV surface, option chains
│   │   └── volatility.py       # IV Rank, RV, DVOL, term structure, skew
│   │
│   ├── brain/
│   │   ├── __init__.py
│   │   ├── regime_detector.py  # Market condition classification
│   │   ├── strategy_selector.py# Regime → strategy mapping
│   │   └── signal.py           # Signal data structures
│   │
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract strategy interface
│   │   ├── wheel.py            # Wheel implementation
│   │   ├── iron_condor.py      # Iron condor implementation
│   │   ├── vol_arb.py          # Volatility arbitrage
│   │   └── gamma_scalp.py      # Gamma scalping
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── order_manager.py    # Order placement, cancellation
│   │   ├── position_tracker.py # Track open positions by strategy
│   │   └── delta_hedger.py     # Automated delta rebalancing
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_manager.py     # Limit checks, validation
│   │   ├── position_sizer.py   # Kelly criterion sizing
│   │   └── circuit_breaker.py  # Emergency halt logic
│   │
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite connection
│   │   ├── models.py           # Trade, Position, Snapshot models
│   │   └── repositories.py     # CRUD operations
│   │
│   └── monitoring/
│       ├── __init__.py
│       ├── dashboard.py        # Flask/FastAPI web UI
│       ├── telegram.py         # Alert bot, commands
│       └── prometheus.py       # Metrics exporter
│
├── tests/
│   ├── unit/                   # Unit tests per module
│   ├── integration/            # API integration tests
│   └── backtest/               # Strategy backtests
│
├── scripts/
│   ├── backtest.py             # Run historical backtests
│   └── migrate_db.py           # Database migrations
│
├── docker-compose.yaml         # Local + prod deployment
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Database Schema

```sql
-- Track every order sent to exchange
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY,
    strategy_id     TEXT NOT NULL,
    strategy_type   TEXT NOT NULL,
    order_id        TEXT UNIQUE,
    instrument      TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    price           REAL NOT NULL,
    fees            REAL DEFAULT 0,
    status          TEXT NOT NULL,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    pnl             REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Aggregate view of strategy instances
CREATE TABLE positions (
    id              INTEGER PRIMARY KEY,
    strategy_id     TEXT UNIQUE NOT NULL,
    strategy_type   TEXT NOT NULL,
    status          TEXT NOT NULL,
    phase           TEXT,
    entry_price     REAL,
    max_profit      REAL,
    max_loss        REAL,
    current_pnl     REAL,
    delta           REAL,
    gamma           REAL,
    theta           REAL,
    vega            REAL,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    close_reason    TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Market snapshots for analysis and backtesting
CREATE TABLE market_snapshots (
    id              INTEGER PRIMARY KEY,
    btc_price       REAL NOT NULL,
    dvol            REAL,
    iv_rank         REAL,
    iv_percentile   REAL,
    rv_7d           REAL,
    rv_30d          REAL,
    iv_rv_spread    REAL,
    term_structure_ratio REAL,        -- IV(30DTE) / IV(90DTE)
    rr_skew         REAL,             -- Δ25 Call IV - Δ25 Put IV
    regime          TEXT,
    active_strategy TEXT,
    timestamp       TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily performance for analytics
CREATE TABLE daily_performance (
    id              INTEGER PRIMARY KEY,
    date            DATE UNIQUE NOT NULL,
    starting_capital REAL,
    ending_capital  REAL,
    pnl             REAL,
    pnl_percent     REAL,
    max_drawdown    REAL,
    trades_opened   INTEGER,
    trades_closed   INTEGER,
    fees_paid       REAL,
    pnl_wheel       REAL DEFAULT 0,
    pnl_iron_condor REAL DEFAULT 0,
    pnl_vol_arb     REAL DEFAULT 0,
    pnl_gamma_scalp REAL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Risk events and circuit breaker triggers
CREATE TABLE risk_events (
    id              INTEGER PRIMARY KEY,
    event_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    message         TEXT,
    action_taken    TEXT,
    timestamp       TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_trades_strategy ON trades(strategy_id);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_snapshots_timestamp ON market_snapshots(timestamp);
CREATE INDEX idx_daily_date ON daily_performance(date);
```

---

## Next Steps

### Phase 1: Foundation
1. **Set up project scaffolding** - Create directory structure, pyproject.toml, requirements.txt
2. **Implement Deribit client** - REST + WebSocket connection with authentication
3. **Build data layer** - Market data, option chains, Greeks
4. **Implement database** - Core tables (trades, positions, snapshots)

### Phase 2: Market Analysis
5. **Build volatility calculator** - IV Rank, RV, DVOL, term structure, skew
6. **Build regime detector** - Rule-based classification

### Phase 3: Strategies
7. **Implement Wheel strategy** - CSP → assignment → covered call cycle
8. **Implement Iron Condor** - With delta adjustment rules
9. **Implement Vol Arb** - Long/short vol with delta hedging
10. **Implement Gamma Scalping** - With RV tracking

### Phase 4: Risk & Execution
11. **Build position sizer** - Half Kelly with regime adjustment
12. **Build delta hedger** - Perpetual-based hedging
13. **Add circuit breakers** - Daily loss, DVOL spike, API errors

### Phase 5: Monitoring
14. **Add Telegram alerts** - Trade execution, regime changes, risk warnings
15. **Build dashboard** - Real-time positions, Greeks, P&L

### Phase 6: Validation
16. **Backtest strategies** - Against historical data
17. **Paper trade** - Full system against live data
18. **Go live** - Deploy to VPS with small capital
