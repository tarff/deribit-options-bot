# Crypto Options Trading Bot Strategies: Comprehensive Research

*Research compiled: January 2026*

---

## Table of Contents

1. [Core Options Strategies for Automation](#1-core-options-strategies-for-automation)
2. [Hybrid & Advanced Strategies](#2-hybrid--advanced-strategies)
3. [Technical Implementation](#3-technical-implementation)
4. [Risk Management Framework](#4-risk-management-framework)
5. [Strategy Selection by Market Condition](#5-strategy-selection-by-market-condition)
6. [Greeks Management for Automated Trading](#6-greeks-management-for-automated-trading)
7. [Volatility Surface Trading](#7-volatility-surface-trading)
8. [Advanced Spread Strategies](#8-advanced-spread-strategies)
9. [Put-Call Parity Arbitrage](#9-put-call-parity-arbitrage)
10. [Theta Gang Strategies (Premium Selling)](#10-theta-gang-strategies-premium-selling)
11. [Protective Strategies](#11-protective-strategies)
12. [Event-Driven Trading](#12-event-driven-trading)
13. [DeFi Options Protocols](#13-defi-options-protocols)
14. [Market Microstructure Considerations](#14-market-microstructure-considerations)
15. [Pricing Model Considerations](#15-pricing-model-considerations)
16. [Position Sizing & Risk Management](#16-position-sizing--risk-management)
17. [Technical Architecture for Bots](#17-technical-architecture-for-bots)
18. [Institutional Approaches](#18-institutional-approaches)
19. [Strategy Selection Matrix](#19-strategy-selection-matrix)
20. [Sources & References](#20-sources--references)

---

## 1. Core Options Strategies for Automation

### Gamma Scalping (Delta-Neutral Trading)

A dynamic hedging strategy that profits from volatility rather than direction. The bot:
- Establishes a delta-neutral position (typically long options + hedged underlying)
- Continuously rebalances delta as price moves
- Profits when **realized volatility exceeds implied volatility**
- Works best in oscillating markets with frequent price swings

Key insight: The strategy is **path-dependent** - more oscillation around a mean equals more profit. Uses perpetual futures for hedging due to better liquidity than options themselves.

**Implementation Resources**:
- Alpaca offers a Python tutorial for gamma scalping
- Greeks.Live integrates with Deribit for one-click delta hedging

---

### Volatility Arbitrage

Exploits the difference between **implied volatility (IV)** and **realized volatility (RV)**:

| Condition | Action |
|-----------|--------|
| IV > RV (options overpriced) | Sell options, hedge delta |
| IV < RV (options underpriced) | Buy options, hedge delta |

The strategy benefits from IV mean-reversion - when IV Rank exceeds 50%, expect contraction. Crypto's high volatility makes this particularly lucrative but also riskier.

**Tools**: Track IV surfaces using Amberdata to detect mispriced options.

---

### The Wheel Strategy

A yield-generation cycle:
1. **Sell cash-secured puts** - collect premium, potentially acquire BTC at discount
2. **If assigned**, **sell covered calls** - collect premium, potentially sell BTC at premium
3. **Repeat**

Best for: Sideways/range-bound markets. Strike selection typically 5-15% OTM. In high-volatility environments, premiums are elevated, improving yields.

---

### Iron Condor

A **market-neutral** strategy profiting from low volatility:
- Sell OTM call + sell OTM put
- Buy further OTM call + buy further OTM put (for protection)

Profits if price stays within a defined range. Maximum profit = net premium received. Maximum loss = spread width minus premium.

---

### Straddles and Strangles

For **volatility exposure** without directional bias:

| Strategy | Structure | When to Use |
|----------|-----------|-------------|
| **Long Straddle** | Buy ATM call + ATM put | Expect large move, direction unknown |
| **Long Strangle** | Buy OTM call + OTM put | Cheaper than straddle, needs bigger move |
| **Short Straddle/Strangle** | Sell both | Expect low volatility, range-bound |

Profits from IV increases (long) or decreases (short), independent of direction.

---

## 2. Hybrid & Advanced Strategies

### Funding Rate Arbitrage + Protective Options

Combines perpetual futures yield with options insurance:
1. **Short perpetual futures** when funding rate is positive (shorts receive funding)
2. **Buy spot** to hedge directional exposure
3. **Buy OTM put** for tail-risk protection

Returns documented at **18-31% annually** with Sharpe ratios of 1.4-2.3.

---

### Basis Trading (Cash-and-Carry)

Exploits futures premium over spot:
- **Long spot** + **Short futures**
- Lock in the basis as profit at expiration

Combines well with options by selling covered calls on the spot position for additional yield.

---

### Market Making

Automated two-sided quoting:
- Post bids slightly below mid-price
- Post asks slightly above mid-price
- Capture the spread continuously

Requires:
- **Dynamic spread adjustment** based on volatility
- **Inventory management** (skew quotes to rebalance)
- **High-frequency infrastructure**

Market makers can tighten crypto spreads from 6% to 0.2% with active participation.

---

## 3. Technical Implementation

### Key Platforms & APIs

| Platform | Focus | Features |
|----------|-------|----------|
| **Deribit** | Options & futures | Industry leader, REST/WebSocket API, Position Builder, Option Wizard |
| **Delta Exchange** | Options | Lower fees, beginner-friendly |
| **OKX** | Multi-asset | Options + spot + perps unified |

### Open Source Projects

| Repository | Description |
|------------|-------------|
| vavabot_options_strategy | Deribit options bot with triggers, stop-loss, multi-leg strategies |
| deribit-api-python | Python REST client for Deribit |
| OctoBot | Grid, DCA, AI strategies for 15+ exchanges |
| Freqtrade | ML-optimized strategies with backtesting |
| passivbot | Minimal intervention perpetuals bot |
| awesome-crypto-trading-bots | Curated list of resources |

### Commercial Platforms

- **3Commas** - DCA, grid, signals integration
- **Cryptohopper** - AI Strategy Designer with auto-backtesting
- **WunderTrading** - Deribit integration, TradingView signals
- **HaasOnline** - HaasScript for complex bots, institutional-grade
- **Tradetron** - Code-free visual strategy builder

---

## 4. Risk Management Framework

### Position Sizing
- Never deploy more than **5-10%** of portfolio on a new strategy
- Use Kelly Criterion for optimal sizing

### Stop Losses
- Program hard stops for flash crash protection
- Options strategies have defined max loss (spreads) - prefer these

### Diversification
- Don't run correlated strategies (e.g., multiple grid bots on BTC/ETH/LTC)
- Mix long-vol and short-vol strategies

### Common Risks

| Risk | Mitigation |
|------|------------|
| **Overfitting** | Backtest across multiple market regimes |
| **Liquidity gaps** | Trade only liquid instruments (BTC, ETH options) |
| **Exchange risk** | Distribute across exchanges |
| **Theta decay** | Monitor time decay on long options |
| **Black swan events** | Always have protective positions |

---

## 5. Strategy Selection by Market Condition

| Market Condition | Recommended Strategies |
|------------------|----------------------|
| **High IV, Range-bound** | Short straddles, iron condors, wheel |
| **Low IV, Expecting breakout** | Long straddles/strangles |
| **Trending** | Gamma scalping, momentum-based |
| **Volatile/Uncertain** | Vol arb (sell IV > RV), protective puts |
| **Positive funding** | Funding rate arbitrage |

---

## 6. Greeks Management for Automated Trading

### Real-Time Greeks Monitoring

Options Greeks in crypto operate 24/7, unlike traditional markets. This has critical implications:

| Greek | Crypto-Specific Consideration |
|-------|------------------------------|
| **Delta (Δ)** | Continuous exposure; hedge with perpetuals (better liquidity than spot) |
| **Gamma (Γ)** | Near-expiry options show extreme gamma; monitor gamma curves |
| **Theta (Θ)** | Decays 24/7 (no weekends); short options decay faster in crypto |
| **Vega (ν)** | High sensitivity to volatility regime changes; BTC can shift 20+ vol points rapidly |

### Dynamic Hedging Algorithms

**Bot Implementation Pattern:**
1. Calculate portfolio Greeks at each block/tick
2. Compare delta to threshold (e.g., |Δ| > 0.1 per BTC notional)
3. Execute hedge trade (perpetual or spot)
4. Account for funding rates in perpetual hedges
5. Monitor slippage vs. benefit of rebalancing

Key insight: **Greeks.Live app** offers one-click delta hedging integrated with Deribit, useful for manual oversight of automated systems.

---

## 7. Volatility Surface Trading

### Term Structure Arbitrage

The **term structure** shows IV across different expirations at ATM strikes:

| Condition | Market Expectation | Strategy |
|-----------|-------------------|----------|
| **Contango** (near < far IV) | Low near-term volatility expected | Sell near-term, buy far-term (calendar spread) |
| **Backwardation** (near > far IV) | Event/stress expected | Buy near-term, sell far-term |

BTC and ETH often show **different term structures** - ETH typically trades at an IV premium with put skew (downside hedging demand).

### Volatility Skew Trading

The **skew** (smile) shows IV across strikes at the same expiration:

- **Call skew positive**: Market expects upside moves (bullish sentiment)
- **Put skew positive**: Market expects downside/hedging demand

**Risk Reversal (RR) Skew** = Δ25 Call IV − Δ25 Put IV
- When RR flips from positive to negative: Sentiment shifting bearish
- Trade: Buy puts, sell calls if anticipating skew steepening

### DVOL Index

Deribit's **DVOL** is crypto's VIX equivalent. ~90% of BTC options trade on Deribit, making DVOL highly representative. Use for:
- Regime detection (high DVOL = expensive options)
- Mean-reversion signals (DVOL > 80 historically reverts)

---

## 8. Advanced Spread Strategies

### Calendar Spreads (Time Arbitrage)

**Structure**: Same strike, different expirations
- **Buy**: Far-dated option (slow theta decay)
- **Sell**: Near-dated option (fast theta decay)

**Profit Mechanism**: Near-term option decays faster. Maximum profit when underlying at strike at near expiry.

**Crypto Edge**: IV term structure inefficiencies persist longer than traditional markets due to less sophisticated participant base.

### Diagonal Spreads

**Structure**: Different strikes AND different expirations
- Combines calendar spread theta capture with directional bias
- More delta exposure than pure calendar

**Example (Bullish Diagonal Call Spread)**:
- Sell 30-DTE 100K BTC call
- Buy 60-DTE 95K BTC call
- Net: Long delta, positive theta, captures term structure

### Double Diagonal

Combines call diagonal + put diagonal for market-neutral theta harvesting. Can be rolled into iron condor at near expiration.

---

## 9. Put-Call Parity Arbitrage

### The Fundamental Relationship

```
Call + PV(Strike) = Put + Underlying
```

When this equality breaks, **synthetic arbitrage** opportunities exist.

### Crypto Market Inefficiencies

Research from Binance options data shows:
- **Significant violations persist** even after bid-ask spread adjustments
- More pronounced in **<15 DTE options**
- Markets becoming **more efficient** over time

### Arbitrage Execution

**Forward Conversion** (when call overpriced):
1. Sell overpriced call
2. Buy put (same strike/expiry)
3. Buy underlying
4. Lock in risk-free profit at expiration

**Reverse Conversion** (when put overpriced):
1. Buy call
2. Sell overpriced put
3. Short underlying

**Practical Challenges**: Execution speed, funding costs for holding spot, liquidation risk on short positions.

---

## 10. Theta Gang Strategies (Premium Selling)

### Core Philosophy

Harvest **theta decay** by being net short options. Crypto's elevated IV means **richer premiums** but higher risk.

### Key Strategies

| Strategy | Structure | Ideal Conditions |
|----------|-----------|------------------|
| **Cash-Secured Put** | Sell OTM put, hold cash for assignment | Bullish/neutral; want to accumulate |
| **Covered Call** | Own underlying, sell OTM call | Neutral/mildly bullish; generate yield |
| **The Wheel** | Cycle between CSP → assignment → CC | Range-bound markets |
| **Put Credit Spread** | Sell put, buy lower put | Bullish with defined risk |
| **Iron Condor** | Credit spread on both sides | Range-bound, expect IV crush |

### Automation: ThetaGang Bot

Open-source ThetaGang bot automates the wheel strategy for Interactive Brokers. Similar architecture can be built for Deribit API.

**Key Metrics to Monitor**:
- **Probability of Profit (POP)**: Target >65% for credit spreads
- **Days to Expiration**: Sweet spot 30-45 DTE (theta accelerates)
- **IV Rank**: Sell premium when IVR > 50%

---

## 11. Protective Strategies

### Collar (Long Stock + Long Put + Short Call)

Creates a **floor and ceiling** on portfolio:
- **Long OTM put**: Insurance against crash
- **Short OTM call**: Finances the put (can be zero-cost)
- Net effect: Capped upside, protected downside

**Crypto Application**: Protect BTC holdings during uncertain events (halving, regulatory news) without selling.

### Risk Reversal (Opposite of Collar)

- **Long call + Short put**: Synthetic long with leverage
- Used to express bullish view cheaply
- **Danger**: Unlimited downside on short put

### Protective Put + Funding Rate Capture

Hybrid strategy combining:
1. Short perpetual (collect positive funding)
2. Long spot (hedge direction)
3. Long OTM put (tail risk protection)

Net: Funding income with insurance against black swan events.

---

## 12. Event-Driven Trading

### Key Crypto Events

| Event | Typical Vol Behavior | Strategy |
|-------|---------------------|----------|
| **Options Expiry** | Pin to max pain → volatility expansion post-expiry | Trade the gamma flush |
| **Halving** | IV elevated pre-event → crush after | Sell vol pre-event if priced in |
| **ETF Decisions** | IV spike → massive crush if approved | Straddle before, close at announcement |
| **Macro Events** | FOMC, CPI can move crypto | Calendar spreads around events |

### Volatility Crush Pattern

- IV spikes before known events (uncertainty)
- IV collapses after event resolution
- **Strategy**: Sell straddles/strangles BEFORE event, buy back after IV crush
- **Risk**: If move exceeds implied, losses can be severe

### Max Pain Theory

**Max pain** = strike price where most options expire worthless.

- Market makers hedge to keep price near max pain
- More reliable for **large expiries** ($20B+)
- Use as **probability weighting** rather than prediction

CoinGlass Max Pain Charts provide real-time data.

---

## 13. DeFi Options Protocols

### Centralized vs Decentralized

| Aspect | CEX (Deribit, OKX) | DeFi (Lyra, Panoptic) |
|--------|-------------------|----------------------|
| Liquidity | Deep | Growing |
| Settlement | Cash-settled | On-chain |
| Counterparty | Exchange | Smart contract |
| IV Pricing | Order book | AMM/oracle |
| Automation | API bots | Smart contract strategies |

### Key Protocols

**Lyra (Derive)**:
- 70%+ market share in DeFi options
- AMM aims to be delta-neutral
- $100M+ TVL, $369M monthly volume

**Panoptic**:
- **Perpetual options** (no expiration)
- Oracle-free pricing via Uniswap v3 LP positions
- **Streaming premium** (pay as you go, not upfront)
- No theta decay in traditional sense

**Dopex (Stryke)**:
- Concentrated liquidity AMM (40x higher returns than standard fees)
- Atlantics product for working collateral

### DeFi Strategy Automation

Structured product vaults (Ribbon, JonesDAO) automate:
- Weekly covered call selling
- Put selling for yield
- Auto-compounding

---

## 14. Market Microstructure Considerations

### Order Flow Toxicity (VPIN)

**VPIN** (Volume-Synchronized Probability of Informed Trading) measures adverse selection risk.

High VPIN signals:
- Informed traders exploiting information edge
- Market makers widen spreads
- **Predictive for price jumps** in BTC

Bot implication: Reduce position sizes or pause trading when VPIN spikes.

### Smart Order Routing (SOR)

For multi-exchange execution:
- Split orders across Deribit, OKX, Binance
- Factor in: Liquidity depth, fees, latency
- **AI-enhanced routers** detect stale quotes

### Latency Arbitrage

Sub-millisecond execution requires:
- **Co-located servers** near exchange
- **FPGAs** for hardware acceleration
- Low-latency NICs and kernel optimization

Most retail/prosumer bots cannot compete here; focus on **longer-term inefficiencies**.

---

## 15. Pricing Model Considerations

### Black-Scholes Limitations in Crypto

| Assumption | Reality in Crypto |
|------------|------------------|
| Constant volatility | Highly variable; use stochastic vol models |
| Normal distribution | Fat tails; use jump-diffusion |
| No transaction costs | Significant fees + slippage |
| Continuous trading | Actually fits crypto well |
| European exercise | Crypto options are European style |
| Fractional units | Crypto supports fractional |

### Better Models for Crypto

- **Jump-Diffusion**: Captures sudden price gaps
- **Stochastic Volatility (Heston)**: Models vol-of-vol
- **Machine Learning**: 8.55% improvement in IV prediction per research

### Variance Risk Premium

**IV typically exceeds realized volatility** - selling variance is profitable on average.

Trading implication: Systematically selling options captures this premium, but tail risk management is critical.

---

## 16. Position Sizing & Risk Management

### Kelly Criterion Application

```
Kelly % = W - [(1-W) / R]
```
Where W = win rate, R = win/loss ratio

**Crypto Adjustments**:
- Use **Quarter Kelly** (6.25%) for crypto's volatility
- Half Kelly captures ~75% of growth with 50% less drawdown

### Volatility-Based Position Sizing

```
Position Size = (Account Risk %) / (Asset Volatility × Price)
```

- High volatility → smaller positions
- Adjust using **ATR** or rolling realized vol
- During elevated VIX/DVOL (>45), reduce by 50%

### Risk Limits

| Limit Type | Recommendation |
|------------|----------------|
| Daily loss | 2x single trade risk → stop trading |
| Single position | Never >25% of account |
| Correlation | Reduce size when holding correlated assets |
| Max drawdown | Hard stop at 15-20% |

---

## 17. Technical Architecture for Bots

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     CRYPTO OPTIONS BOT                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Data Feed   │  │ Strategy    │  │ Execution Engine    │  │
│  │ - WebSocket │→ │ - Greeks    │→ │ - Order routing     │  │
│  │ - Order book│  │ - Signals   │  │ - Position mgmt     │  │
│  │ - Trades    │  │ - Risk mgmt │  │ - Fills tracking    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│         ↑                                     ↓              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Exchange APIs (Deribit, OKX)               ││
│  │   REST: Orders, Positions   |   WS: Market Data, Fills  ││
│  └─────────────────────────────────────────────────────────┘│
│         ↓                                     ↓              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Backtester  │  │ Database    │  │ Monitoring/Alerts   │  │
│  │ - Historical│  │ - Trades    │  │ - PnL dashboard     │  │
│  │ - Walk-fwd  │  │ - Greeks    │  │ - Risk alerts       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Key Libraries

| Component | Python Library |
|-----------|---------------|
| Exchange API | `ccxt`, `deribit_api`, custom WebSocket |
| Greeks Calculation | `py_vollib`, `QuantLib`, `mibian` |
| Backtesting | `backtrader`, `backtesting.py`, `vectorbt` |
| Data Storage | `TimescaleDB`, `InfluxDB`, `DolphinDB` |
| ML/Optimization | `scikit-learn`, `optuna`, `stable-baselines3` |

### Data Requirements

- **Tick data**: Essential for accurate backtesting
- **Order book snapshots**: Required for slippage modeling
- **Dual timestamps**: Exchange time + receipt time for latency analysis
- **Historical IV surface**: For vol strategy backtesting

---

## 18. Institutional Approaches

### Hedge Fund Strategy Categories (per HFR)

1. **Long/Short Crypto**: Directional with hedges
2. **Market Neutral**: Delta-neutral, vol-focused
3. **Quantitative**: Factor models, ML-driven
4. **Arbitrage**: Funding rate, basis, cross-exchange
5. **Event-Driven**: Halving, forks, regulatory
6. **Multi-Strategy**: Combination approaches

### Desk Structure

- **Execution desk**: Order routing, slippage minimization
- **Risk desk**: Greeks monitoring, limit enforcement
- **Quant desk**: Strategy development, backtesting
- **Operations**: Reconciliation, settlement

### Counterparty Management

Institutions distribute across:
- Multiple exchanges (Deribit, OKX, Binance)
- OTC desks (Cumberland, Galaxy, B2C2)
- Prime brokers (FalconX, Hidden Road)
- Qualified custodians (Anchorage, BitGo)

---

## 19. Strategy Selection Matrix

| Your Edge/Interest | Primary Strategy | Secondary Strategies |
|-------------------|-----------------|---------------------|
| **Volatility forecasting** | Vol arbitrage (IV vs RV) | Gamma scalping, variance selling |
| **Directional views** | Risk reversals, vertical spreads | Diagonal spreads |
| **Yield generation** | Wheel, covered calls, CSPs | Funding rate + protective puts |
| **Market neutral** | Iron condors, delta-neutral | Calendar spreads |
| **Event trading** | Straddles/strangles | Vol crush plays |
| **Arbitrage** | Put-call parity, funding rate | Cross-exchange, basis |
| **DeFi native** | Panoptic perpetual options | Lyra AMM strategies |

---

## 20. Sources & References

### Technical Analysis & Greeks
- Amberdata - Options Greeks Explained: https://blog.amberdata.io/options-greeks-explained-managing-risk-in-crypto-derivatives
- Deribit Volatility Section: https://insights.deribit.com/options-course/sections/section-7-volatility/
- Deribit Skew Analysis: https://insights.deribit.com/industry/weekly-commentary-skew-structure/

### Strategy Guides
- Alpaca - Gamma Scalping Tutorial: https://alpaca.markets/learn/gamma-scalping
- Delta Exchange - Gamma Scalping in Crypto: https://www.delta.exchange/blog/gamma-scalping-crypto-options
- Deribit - Delta Hedging: https://insights.deribit.com/industry/how-to-use-delta-hedging-to-lock-up-profits/
- Pi42 - Volatility Arbitrage Crypto Options: https://pi42.com/blog/volatility-arbitrage-crypto-options/
- XBTO - Crypto Options for Yield: https://www.xbto.com/resources/crypto-options-trading-a-new-way-to-generate-yield-2025
- DamaDefi - Bitcoin Covered Calls & Wheel: https://damadefi.com/bitcoin-options-for-income-covered-calls-the-wheel/
- Delta Exchange - Iron Condor: https://www.delta.exchange/blog/understanding-iron-condor-crypto-options-trading-strategy
- Alpaca Calendar Spread Tutorial: https://alpaca.markets/learn/calendar-spread

### Arbitrage & Market Structure
- Amberdata - Funding Rate Arbitrage: https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata
- OKX Put-Call Parity Arbitrage: https://www.okx.com/en-us/learn/how-to-put-call-parity-arbitrage-crypto-options
- Binance Put-Call Parity Research: https://www.sciencedirect.com/science/article/abs/pii/S1544612323012461
- Order Flow Toxicity Research: https://www.sciencedirect.com/science/article/pii/S0275531925004192

### Market Making & Institutional
- Quant Matter - Crypto Options Market Making: https://quantmatter.com/crypto-option-trading-the-dynamics-of-market-making/
- DWF Labs - Market Making Strategies: https://www.dwf-labs.com/news/4-common-strategies-that-crypto-market-makers-use
- Crypto Hedge Fund Guide (CAIA): https://caia.org/blog/2025/07/14/framework-cryptocurrency-trading
- Coinbase Institutional Guide: https://www.coinbase.com/institutional/research-insights/research/market-intelligence/asset-allocators-guide-to-crypto-hedge-funds-2024

### DeFi Options
- Yellow - DeFi Options 2025: https://yellow.com/research/defi-options-trading-in-2025-how-lyra-dopex-and-panoptic-are-reshaping-derivatives
- Panoptic Introduction: https://panoptic.xyz/blog/panoptic-defi-options-protocol-introduction
- Three Sigma - DeFi Options Landscape: https://threesigma.xyz/blog/defi-options-landscape

### Protective Strategies
- Coinbase Risk Reversal Guide: https://www.coinbase.com/learn/advanced-trading/how-does-a-risk-reversal-options-strategy-work-in-crypto
- Fidelity - Collar Strategy: https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/collar

### Open Source & Tools
- Deribit API Docs: https://docs.deribit.com/
- ThetaGang GitHub: https://github.com/brndnmtthws/thetagang
- OctoBot GitHub: https://github.com/Drakkar-Software/OctoBot
- vavabot GitHub: https://github.com/vavarb/vavabot_options_strategy
- deribit-api-python: https://github.com/kramer65/deribit-api-python
- awesome-crypto-trading-bots: https://github.com/botcrypto-io/awesome-crypto-trading-bots

### Pricing & Models
- Black-Scholes Crypto Limitations: https://www.cryptodatadownload.com/blog/posts/black-scholes-options-assumptions-crypto-markets/
- Crypto Options Pricing Research: https://onlinelibrary.wiley.com/doi/10.1002/fut.70029

### Market Data & Analytics
- CoinGlass Max Pain Charts: https://www.coinglass.com/pro/options/max-pain
- Amberdata Deribit Market Data: https://www.amberdata.io/deribit-market-data
- The Block Options Data: https://www.theblock.co/data/crypto-markets/options

### News & Analysis
- FalconX Options Market Analysis: https://www.falconx.io/newsroom/inside-the-crypto-options-boom-three-significant-shifts-shaping-this-market
- Deribit Bitcoin Volatility Regimes: https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/

---

## Emerging Trends (2025-2026)

- **AI/ML-driven bots** now control ~58% of crypto trading volume
- **Reinforcement learning** for adaptive strategy switching
- **Decentralized options** (Panoptic, Lyra) enabling on-chain strategies
- **Cross-exchange arbitrage** yielding 3-5% additional annualized returns
- **Predictive analytics** anticipating regulatory/macro shifts
- **Spot BTC ETF impact**: Volatility compression, institutional flows altering traditional cycles
- **Perpetual options**: No expiration, streaming premiums (Panoptic model)

---

*This document is for educational and research purposes only. Options trading involves substantial risk. Past performance does not guarantee future results.*
