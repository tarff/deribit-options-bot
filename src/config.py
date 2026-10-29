"""Configuration management for the trading bot."""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DeribitConfig(BaseModel):
    """Deribit API configuration."""

    base_url: str = "https://www.deribit.com"
    ws_url: str = "wss://www.deribit.com/ws/api/v2"
    api_key: str = ""
    api_secret: str = ""


class TradingConfig(BaseModel):
    """Trading configuration."""

    currency: str = Field(default="BTC", description="Trading currency (BTC or ETH)")
    settlement: str = Field(
        default="linear",
        description="Settlement type: 'linear' (USDC-settled) or 'inverse' (crypto-margined)",
    )


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_position_pct: float = Field(default=10.0, ge=0, le=100)
    max_exposure_pct: float = Field(default=30.0, ge=0, le=100)
    max_daily_loss_pct: float = Field(default=5.0, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15.0, ge=0, le=100)
    dvol_reduce_threshold: float = Field(default=60.0)
    dvol_halt_threshold: float = Field(default=80.0)


class DatabaseConfig(BaseModel):
    """Database configuration."""

    path: str = "data/bot.db"


class PaperTradingConfig(BaseModel):
    """Paper trading configuration."""

    loop_interval_seconds: int = Field(default=60, ge=10)
    position_sync_interval: int = Field(default=5, ge=1)
    use_market_orders: bool = False
    initial_capital_usd: float = Field(default=10000.0, ge=100.0)


class TelegramConfig(BaseModel):
    """Telegram notification configuration."""

    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    notify_entry: bool = True
    notify_exit: bool = True
    notify_circuit_breaker: bool = True


class EmergencyConfig(BaseModel):
    """Emergency manager configuration."""

    dvol_emergency_threshold: float = Field(default=100.0)


class Settings(BaseModel):
    """Application settings."""

    deribit: DeribitConfig = Field(default_factory=DeribitConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    paper_trading: PaperTradingConfig = Field(default_factory=PaperTradingConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    emergency: EmergencyConfig = Field(default_factory=EmergencyConfig)


def _substitute_env_vars(content: str) -> str:
    """Substitute ${VAR_NAME} patterns with environment variable values.

    Args:
        content: String content with potential env var placeholders.

    Returns:
        Content with env vars substituted.
    """
    pattern = re.compile(r'\$\{([^}]+)\}')

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            logger.warning(f"Environment variable {var_name} not set, using empty string")
            return ""
        return value

    return pattern.sub(replace, content)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file.

    Environment variables in the format ${VAR_NAME} are substituted
    with their values from the environment.

    Args:
        config_path: Path to YAML config file. Defaults to config/settings.yaml.

    Returns:
        Loaded Settings object.
    """
    if config_path is None:
        config_path = Path("config/settings.yaml")

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return Settings()

    with open(config_path) as f:
        content = f.read()

    # Substitute environment variables
    content = _substitute_env_vars(content)

    data: dict[str, Any] = yaml.safe_load(content) or {}

    return Settings(**data)
