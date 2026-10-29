# deribit-options-bot

An autonomous BTC options trading bot for [Deribit](https://www.deribit.com), written in async Python.
It reads the market every cycle, classifies it into one of six volatility regimes, and picks the
strategy that suits that regime. Every signal passes a separate risk layer before any order is sent.

## How it works

```
DeribitClient -> MarketAnalyzer -> RegimeDetector -> StrategySelector -> Strategy -> Signal
                                                                              |
                                                                     RiskManager -> Execution
```

- **Data** (`src/data/`): async REST client for the Deribit API, IV rank, realised volatility, IV-RV
  spread and option selection by delta, strike and days to expiry.
- **Regimes** (`src/brain/`): rule-based classification into six regimes using DVOL, IV rank and the
  IV-RV spread, mapped to a strategy and a position-size multiplier.
- **Strategies** (`src/strategies/`): the wheel, iron condors, volatility arbitrage with delta
  hedging, gamma scalping and calendar spreads, all behind one `BaseStrategy` interface.
- **Risk** (`src/risk/`): half-Kelly sizing scaled by regime, pre-trade checks on positions, daily loss
  and drawdown, and circuit breakers for DVOL spikes and API errors.
- **Persistence** (`src/persistence/`): SQLite with Pydantic models and a repository layer.
- **Dashboard** (`dashboard/`): React front end on a FastAPI backend.

`scripts/` holds the backtest, paper-trading runner and the calibration scripts behind the
thresholds in `config/`. `docs/MAINNET_GO_LIVE.md` is the go-live checklist.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scriptsctivate
pip install -r requirements.txt -r requirements-dev.txt
cp config/settings.example.yaml config/settings.yaml
```

Secrets come from environment variables (`DERIBIT_API_KEY`, `DERIBIT_API_SECRET`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Use `https://test.deribit.com` for paper trading.

## Test

```bash
pytest
mypy src/
ruff check src/ tests/
```

Not financial advice. Use it on testnet first; trading options can lose more than you expect.
