"""Telegram notification service for trade events and alerts."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from src.config import TelegramConfig

logger = logging.getLogger(__name__)

# Rate limit: minimum seconds between messages
# Telegram bot API limit is ~30 msgs/sec, but 0.1s gives comfortable margin
RATE_LIMIT_SECONDS = 0.1


class TelegramNotifier:
    """Telegram notification service for trading bot events.

    Sends notifications for trade entries, exits, and circuit breaker trips.
    Never raises exceptions - logs failures and returns False.

    Example:
        >>> config = TelegramConfig(enabled=True, bot_token="...", chat_id="...")
        >>> notifier = TelegramNotifier(config)
        >>> await notifier.notify_trade_entry(
        ...     strategy="wheel",
        ...     contracts=["BTC-28MAR25-100000-P"],
        ...     premium=0.0123,
        ...     btc_price=98000.0,
        ... )
        True
    """

    def __init__(self, config: "TelegramConfig") -> None:
        """Initialize Telegram notifier.

        Args:
            config: Telegram configuration with bot token and chat ID.
        """
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._last_message_time: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (lazy initialization).

        Returns:
            Active aiohttp ClientSession.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _send_message(self, text: str) -> bool:
        """Send a message to configured Telegram chat.

        Applies rate limiting and handles all errors internally.

        Args:
            text: Message text (supports Telegram MarkdownV2).

        Returns:
            True if message sent successfully, False otherwise.
        """
        if not self.config.enabled:
            return True  # No-op success when disabled

        if not self.config.bot_token or not self.config.chat_id:
            logger.warning("Telegram bot_token or chat_id not configured")
            return False

        # Rate limiting - enforce minimum spacing between message sends
        now = time.monotonic()
        elapsed = now - self._last_message_time
        if elapsed < RATE_LIMIT_SECONDS:
            await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)

        # Record send time before request (not after) to enforce spacing between starts
        self._last_message_time = time.monotonic()

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            session = await self._get_session()
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.post(url, json=payload, timeout=timeout) as response:

                if response.status == 200:
                    return True

                error_text = await response.text()
                logger.warning(
                    f"Telegram API error: status={response.status}, body={error_text[:200]}"
                )
                return False

        except asyncio.TimeoutError:
            logger.warning("Telegram API request timed out")
            return False
        except aiohttp.ClientError as e:
            logger.warning(f"Telegram API client error: {e}")
            return False
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")
            return False

    async def notify_trade_entry(
        self,
        strategy: str,
        contracts: list[str],
        premium: float,
        btc_price: float,
        currency: str = "BTC",
        is_linear: bool = False,
    ) -> bool:
        """Notify about a new trade entry.

        Args:
            strategy: Strategy name (e.g., "wheel", "iron_condor").
            contracts: List of contract instrument names.
            premium: Total premium received (inverse: crypto units, linear: USDC).
            btc_price: Current underlying price.
            currency: Trading currency (BTC or ETH).
            is_linear: Whether using USDC-settled linear options.

        Returns:
            True if notification sent successfully.
        """
        if not self.config.notify_entry:
            return True

        contracts_str = "\n".join(f"  • {c}" for c in contracts)

        if is_linear:
            premium_line = f"<b>Premium:</b> ${premium:,.2f} USDC"
        else:
            premium_usd = premium * btc_price
            premium_line = f"<b>Premium:</b> {premium:.6f} {currency} (${premium_usd:,.2f})"

        message = (
            f"<b>📈 Trade Opened: {strategy.upper()}</b>\n\n"
            f"<b>Contracts:</b>\n{contracts_str}\n\n"
            f"{premium_line}\n"
            f"<b>{currency} Price:</b> ${btc_price:,.0f}\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return await self._send_message(message)

    async def notify_trade_exit(
        self,
        strategy: str,
        pnl: float,
        pnl_usd: float,
        reason: str,
        currency: str = "BTC",
        is_linear: bool = False,
    ) -> bool:
        """Notify about a trade exit.

        Args:
            strategy: Strategy name (e.g., "wheel", "iron_condor").
            pnl: Realized PnL (inverse: crypto units, linear: USDC).
            pnl_usd: Realized PnL in USD.
            reason: Exit reason (e.g., "profit_target", "stop_loss").
            currency: Trading currency (BTC or ETH).
            is_linear: Whether using USDC-settled linear options.

        Returns:
            True if notification sent successfully.
        """
        if not self.config.notify_exit:
            return True

        emoji = "✅" if pnl >= 0 else "❌"
        pnl_sign = "+" if pnl >= 0 else ""

        if is_linear:
            pnl_line = f"<b>PnL:</b> {pnl_sign}${pnl_usd:,.2f} USDC"
        else:
            pnl_line = f"<b>PnL:</b> {pnl_sign}{pnl:.6f} {currency} ({pnl_sign}${pnl_usd:,.2f})"

        message = (
            f"<b>{emoji} Trade Closed: {strategy.upper()}</b>\n\n"
            f"{pnl_line}\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return await self._send_message(message)

    async def notify_circuit_breaker(
        self,
        reason: str,
        dvol: float | None = None,
        daily_pnl: float | None = None,
    ) -> bool:
        """Notify about a circuit breaker trip.

        Args:
            reason: Breaker trip reason.
            dvol: Current DVOL if relevant.
            daily_pnl: Current daily PnL if relevant.

        Returns:
            True if notification sent successfully.
        """
        if not self.config.notify_circuit_breaker:
            return True

        details = []
        if dvol is not None:
            details.append(f"<b>DVOL:</b> {dvol:.1f}")
        if daily_pnl is not None:
            details.append(f"<b>Daily PnL:</b> ${daily_pnl:,.2f}")

        details_str = "\n".join(details)
        if details_str:
            details_str = f"\n\n{details_str}"

        message = (
            f"<b>🚨 CIRCUIT BREAKER TRIPPED</b>\n\n"
            f"<b>Reason:</b> {reason}{details_str}\n\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"Trading is halted until conditions improve."
        )

        return await self._send_message(message)
