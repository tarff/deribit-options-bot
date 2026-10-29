"""Tests for Telegram notification service."""

import pytest
from aioresponses import aioresponses

from src.config import TelegramConfig
from src.monitoring.telegram_notifier import TelegramNotifier


@pytest.fixture
def config() -> TelegramConfig:
    """Create test configuration."""
    return TelegramConfig(
        enabled=True,
        bot_token="test_bot_token",
        chat_id="123456789",
        notify_entry=True,
        notify_exit=True,
        notify_circuit_breaker=True,
    )


@pytest.fixture
def disabled_config() -> TelegramConfig:
    """Create disabled configuration."""
    return TelegramConfig(enabled=False)


@pytest.fixture
async def notifier(config: TelegramConfig) -> TelegramNotifier:
    """Create test notifier with cleanup."""
    n = TelegramNotifier(config)
    yield n
    await n.close()


@pytest.fixture
async def disabled_notifier(disabled_config: TelegramConfig) -> TelegramNotifier:
    """Create disabled test notifier with cleanup."""
    n = TelegramNotifier(disabled_config)
    yield n
    await n.close()


@pytest.mark.asyncio
async def test_notify_trade_entry_success(notifier: TelegramNotifier) -> None:
    """Test successful trade entry notification."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 123}},
        )

        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.0123,
            btc_price=98000.0,
        )

        assert result is True


@pytest.mark.asyncio
async def test_notify_trade_entry_with_multiple_contracts(
    notifier: TelegramNotifier,
) -> None:
    """Test trade entry notification with multiple contracts (Iron Condor)."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 123}},
        )

        result = await notifier.notify_trade_entry(
            strategy="iron_condor",
            contracts=[
                "BTC-28MAR25-90000-P",
                "BTC-28MAR25-95000-P",
                "BTC-28MAR25-105000-C",
                "BTC-28MAR25-110000-C",
            ],
            premium=0.025,
            btc_price=100000.0,
            currency="BTC",
        )

        assert result is True


@pytest.mark.asyncio
async def test_notify_trade_exit_profit(notifier: TelegramNotifier) -> None:
    """Test trade exit notification with profit."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 124}},
        )

        result = await notifier.notify_trade_exit(
            strategy="wheel",
            pnl=0.005,
            pnl_usd=490.0,
            reason="profit_target",
        )

        assert result is True


@pytest.mark.asyncio
async def test_notify_trade_exit_loss(notifier: TelegramNotifier) -> None:
    """Test trade exit notification with loss."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 125}},
        )

        result = await notifier.notify_trade_exit(
            strategy="iron_condor",
            pnl=-0.003,
            pnl_usd=-294.0,
            reason="stop_loss",
        )

        assert result is True


@pytest.mark.asyncio
async def test_notify_circuit_breaker(notifier: TelegramNotifier) -> None:
    """Test circuit breaker notification."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 126}},
        )

        result = await notifier.notify_circuit_breaker(
            reason="DVOL exceeded threshold",
            dvol=85.5,
            daily_pnl=-250.0,
        )

        assert result is True


@pytest.mark.asyncio
async def test_notify_circuit_breaker_minimal(notifier: TelegramNotifier) -> None:
    """Test circuit breaker notification with only reason."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 127}},
        )

        result = await notifier.notify_circuit_breaker(
            reason="API error threshold exceeded",
        )

        assert result is True


@pytest.mark.asyncio
async def test_disabled_notifier_returns_true(
    disabled_notifier: TelegramNotifier,
) -> None:
    """Test that disabled notifier returns True (no-op success)."""
    # No mocking needed - should not make any HTTP requests
    result = await disabled_notifier.notify_trade_entry(
        strategy="wheel",
        contracts=["BTC-28MAR25-100000-P"],
        premium=0.01,
        btc_price=98000.0,
    )

    assert result is True


@pytest.mark.asyncio
async def test_api_error_returns_false(notifier: TelegramNotifier) -> None:
    """Test that API errors return False without raising."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            status=401,
            payload={"ok": False, "description": "Unauthorized"},
        )

        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is False


@pytest.mark.asyncio
async def test_network_error_returns_false(notifier: TelegramNotifier) -> None:
    """Test that network errors return False without raising."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            exception=Exception("Connection refused"),
        )

        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is False


@pytest.mark.asyncio
async def test_missing_token_returns_false() -> None:
    """Test that missing bot token returns False."""
    config = TelegramConfig(enabled=True, bot_token="", chat_id="123")
    notifier = TelegramNotifier(config)

    try:
        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is False
    finally:
        await notifier.close()


@pytest.mark.asyncio
async def test_missing_chat_id_returns_false() -> None:
    """Test that missing chat ID returns False."""
    config = TelegramConfig(enabled=True, bot_token="token", chat_id="")
    notifier = TelegramNotifier(config)

    try:
        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is False
    finally:
        await notifier.close()


@pytest.mark.asyncio
async def test_notify_entry_disabled_returns_true(config: TelegramConfig) -> None:
    """Test that disabled entry notifications return True."""
    config.notify_entry = False
    notifier = TelegramNotifier(config)

    try:
        # Should not make any HTTP requests
        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is True
    finally:
        await notifier.close()


@pytest.mark.asyncio
async def test_notify_exit_disabled_returns_true(config: TelegramConfig) -> None:
    """Test that disabled exit notifications return True."""
    config.notify_exit = False
    notifier = TelegramNotifier(config)

    try:
        result = await notifier.notify_trade_exit(
            strategy="wheel",
            pnl=0.01,
            pnl_usd=980.0,
            reason="profit_target",
        )

        assert result is True
    finally:
        await notifier.close()


@pytest.mark.asyncio
async def test_notify_circuit_breaker_disabled_returns_true(
    config: TelegramConfig,
) -> None:
    """Test that disabled circuit breaker notifications return True."""
    config.notify_circuit_breaker = False
    notifier = TelegramNotifier(config)

    try:
        result = await notifier.notify_circuit_breaker(
            reason="Test reason",
            dvol=85.0,
        )

        assert result is True
    finally:
        await notifier.close()


@pytest.mark.asyncio
async def test_eth_currency_in_message(notifier: TelegramNotifier) -> None:
    """Test that ETH currency is correctly displayed in messages."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 128}},
        )

        result = await notifier.notify_trade_entry(
            strategy="gamma_scalp",
            contracts=["ETH-28MAR25-4000-C"],
            premium=0.5,
            btc_price=3500.0,
            currency="ETH",
        )

        assert result is True


@pytest.mark.asyncio
async def test_linear_entry_notification(notifier: TelegramNotifier) -> None:
    """Test that linear entry notification shows USDC premium."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 200}},
        )

        result = await notifier.notify_trade_entry(
            strategy="iron_condor",
            contracts=["ETH_USDC-27FEB26-2100-P", "ETH_USDC-27FEB26-1900-P"],
            premium=73.0,  # USDC dollars, not crypto fractions
            btc_price=2700.0,
            currency="ETH",
            is_linear=True,
        )

        assert result is True


@pytest.mark.asyncio
async def test_linear_exit_notification(notifier: TelegramNotifier) -> None:
    """Test that linear exit notification shows USDC PnL."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 201}},
        )

        result = await notifier.notify_trade_exit(
            strategy="iron_condor",
            pnl=36.5,  # USDC
            pnl_usd=36.5,  # Same for linear
            reason="profit_target",
            currency="ETH",
            is_linear=True,
        )

        assert result is True


@pytest.mark.asyncio
async def test_session_reuse(notifier: TelegramNotifier) -> None:
    """Test that aiohttp session is reused across calls."""
    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            payload={"ok": True, "result": {"message_id": 129}},
            repeat=True,
        )

        # First call creates session
        await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        session_after_first = notifier._session

        # Second call should reuse session
        await notifier.notify_trade_exit(
            strategy="wheel",
            pnl=0.005,
            pnl_usd=490.0,
            reason="profit_target",
        )

        assert notifier._session is session_after_first


@pytest.mark.asyncio
async def test_timeout_returns_false(notifier: TelegramNotifier) -> None:
    """Test that timeouts return False without raising."""
    import asyncio

    with aioresponses() as mocked:
        mocked.post(
            "https://api.telegram.org/bottest_bot_token/sendMessage",
            exception=asyncio.TimeoutError(),
        )

        result = await notifier.notify_trade_entry(
            strategy="wheel",
            contracts=["BTC-28MAR25-100000-P"],
            premium=0.01,
            btc_price=98000.0,
        )

        assert result is False


@pytest.mark.asyncio
async def test_rate_limiting_enforces_minimum_delay(config: TelegramConfig) -> None:
    """Test that rate limiting enforces minimum 0.1s between messages."""
    import time

    notifier = TelegramNotifier(config)

    try:
        with aioresponses() as mocked:
            mocked.post(
                "https://api.telegram.org/bottest_bot_token/sendMessage",
                payload={"ok": True, "result": {"message_id": 1}},
                repeat=True,
            )

            # First message - no delay needed
            await notifier.notify_trade_entry(
                strategy="wheel",
                contracts=["BTC-28MAR25-100000-P"],
                premium=0.01,
                btc_price=98000.0,
            )

            # Second message - should wait at least 0.1s from first
            start = time.perf_counter()
            await notifier.notify_trade_exit(
                strategy="wheel",
                pnl=0.005,
                pnl_usd=490.0,
                reason="profit_target",
            )
            second_call_time = time.perf_counter() - start

            # Second call should have waited for rate limit
            # Allow small tolerance for timing variations
            assert second_call_time >= 0.08  # 0.1s - 0.02s tolerance
    finally:
        await notifier.close()
