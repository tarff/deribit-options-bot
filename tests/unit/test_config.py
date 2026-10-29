"""Tests for configuration loading."""

import pytest
from pathlib import Path

from src.config import Settings, TradingConfig, load_settings


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    """Test loading settings from YAML file."""
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("""
deribit:
  base_url: "https://test.deribit.com"
  ws_url: "wss://test.deribit.com/ws/api/v2"

risk:
  max_position_pct: 10.0
  max_exposure_pct: 30.0
  max_daily_loss_pct: 5.0
  max_drawdown_pct: 15.0

database:
  path: "data/bot.db"
""")

    settings = load_settings(config_file)

    assert settings.deribit.base_url == "https://test.deribit.com"
    assert settings.risk.max_position_pct == 10.0
    assert settings.database.path == "data/bot.db"


def test_settings_validation_rejects_invalid_risk() -> None:
    """Test that invalid risk parameters are rejected."""
    with pytest.raises(ValueError):
        Settings(
            deribit={"base_url": "https://test.deribit.com", "ws_url": "wss://test.deribit.com/ws/api/v2"},
            risk={"max_position_pct": 150.0},  # Invalid: > 100%
            database={"path": "test.db"},
        )


def test_trading_config_settlement_default() -> None:
    """Test that settlement defaults to 'linear'."""
    config = TradingConfig()
    assert config.settlement == "linear"


def test_trading_config_settlement_from_yaml(tmp_path: Path) -> None:
    """Test loading settlement type from YAML."""
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("""
trading:
  currency: "ETH"
  settlement: "inverse"
""")

    settings = load_settings(config_file)
    assert settings.trading.settlement == "inverse"
    assert settings.trading.currency == "ETH"


def test_trading_config_settlement_linear(tmp_path: Path) -> None:
    """Test loading linear settlement from YAML."""
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("""
trading:
  currency: "ETH"
  settlement: "linear"
""")

    settings = load_settings(config_file)
    assert settings.trading.settlement == "linear"


def test_mainnet_config_uses_limit_orders() -> None:
    """Production config should avoid uncapped sequential market orders."""
    settings = load_settings(Path("config/settings.mainnet.yaml"))

    assert settings.paper_trading.use_market_orders is False


def test_testnet_config_uses_limit_orders() -> None:
    """Testnet config should match executor policy for multi-leg entries."""
    settings = load_settings(Path("config/settings.testnet.yaml"))

    assert settings.paper_trading.use_market_orders is False


def test_example_config_uses_limit_orders() -> None:
    """Example config should not steer new deployments to blocked market entries."""
    settings = load_settings(Path("config/settings.example.yaml"))

    assert settings.paper_trading.use_market_orders is False
