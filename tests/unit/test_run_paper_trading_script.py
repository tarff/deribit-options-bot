"""Tests for the paper trading runner script."""

import argparse

from scripts import run_paper_trading
from src.config import PaperTradingConfig, Settings


def test_build_paper_config_uses_loaded_order_policy_by_default() -> None:
    """Runner should not override settings back to market orders by default."""
    settings = Settings(paper_trading=PaperTradingConfig(use_market_orders=False))
    args = argparse.Namespace(
        interval=30,
        capital=5000.0,
        market_orders=False,
        limit_orders=False,
    )

    config = run_paper_trading.build_paper_config(args, settings)

    assert config.loop_interval_seconds == 30
    assert config.initial_capital_usd == 5000.0
    assert config.use_market_orders is False


def test_build_paper_config_can_explicitly_enable_market_orders() -> None:
    """Market order mode should require an explicit CLI override."""
    settings = Settings(paper_trading=PaperTradingConfig(use_market_orders=False))
    args = argparse.Namespace(
        interval=30,
        capital=5000.0,
        market_orders=True,
        limit_orders=False,
    )

    config = run_paper_trading.build_paper_config(args, settings)

    assert config.use_market_orders is True


def test_build_paper_config_can_explicitly_enable_limit_orders() -> None:
    """Limit order mode should be an explicit override when settings differ."""
    settings = Settings(paper_trading=PaperTradingConfig(use_market_orders=True))
    args = argparse.Namespace(
        interval=30,
        capital=5000.0,
        market_orders=False,
        limit_orders=True,
    )

    config = run_paper_trading.build_paper_config(args, settings)

    assert config.use_market_orders is False
