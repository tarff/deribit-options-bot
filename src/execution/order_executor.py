"""Order executor for executing trade signals via Deribit API."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from src.brain.signal import TradeSignal, SignalAction, OptionContract
from src.data.deribit_client import DeribitClient, DeribitError
from src.risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Rate limit delay between API calls (0.12s = ~8 req/s with margin)
API_RATE_LIMIT_DELAY = 0.12

# Retry configuration
MAX_RETRIES = 3
BASE_RETRY_DELAY = 0.5


@dataclass
class OrderResult:
    """Result of an order execution.

    Attributes:
        success: Whether the order was successful.
        order_id: Order ID if successful.
        filled_amount: Amount that was filled.
        average_price: Average fill price.
        error: Error message if failed.
        instrument_name: Instrument that was traded.
    """

    success: bool
    order_id: Optional[str] = None
    filled_amount: float = 0.0
    average_price: float = 0.0
    fee: float = 0.0
    fee_currency: Optional[str] = None
    error: Optional[str] = None
    instrument_name: Optional[str] = None


class OrderExecutor:
    """Executes trade signals via Deribit API.

    Handles:
    - Multi-leg order execution
    - Rate limiting between API calls
    - Retry logic with exponential backoff
    - Circuit breaker integration
    """

    def __init__(
        self,
        client: DeribitClient,
        circuit_breaker: Optional[CircuitBreaker] = None,
        use_market_orders: bool = True,
    ) -> None:
        """Initialize order executor.

        Args:
            client: Deribit API client.
            circuit_breaker: Optional circuit breaker for error tracking.
            use_market_orders: Whether to use market orders (default True).
        """
        self.client = client
        self.circuit_breaker = circuit_breaker
        self.use_market_orders = use_market_orders

    async def execute_signal(
        self,
        signal: TradeSignal,
        btc_price: float,
    ) -> list[OrderResult]:
        """Execute a trade signal.

        Executes all legs of the signal with rate limiting between calls.

        Args:
            signal: Trade signal to execute.
            btc_price: Current BTC price for size calculations.

        Returns:
            List of OrderResult for each leg.
        """
        results: list[OrderResult] = []

        if (
            self.use_market_orders
            and signal.action == SignalAction.OPEN
            and len(signal.contracts) > 1
        ):
            return [
                OrderResult(
                    success=False,
                    error="Multi-leg OPEN signals require limit orders to cap slippage",
                )
            ]

        # Determine direction for each leg
        if signal.legs_direction:
            directions = signal.legs_direction
        else:
            directions = [signal.direction] * len(signal.contracts)

        for contract, direction in zip(signal.contracts, directions, strict=True):
            # Rate limit between calls
            if results:
                await asyncio.sleep(API_RATE_LIMIT_DELAY)

            result = await self._execute_leg(
                contract=contract,
                direction=direction,
                quantity=signal.quantity,
                btc_price=btc_price,
                use_market_order_override=(
                    True if signal.action == SignalAction.CLOSE else self.use_market_orders
                ),
            )
            results.append(result)

            if not result.success:
                logger.error(
                    f"Leg execution failed: {contract.instrument_name} - {result.error}"
                )
                # For OPEN, stop to avoid adding more partial exposure. For CLOSE,
                # continue trying remaining legs to reduce existing risk.
                if signal.action == SignalAction.OPEN:
                    break

        return results

    async def execute_hedge(
        self,
        currency: str,
        is_linear: bool,
        direction: str,
        quantity: float,
    ) -> OrderResult:
        """Execute a delta hedge in the underlying perpetual market."""
        instrument_name = (
            f"{currency.upper()}_USDC-PERPETUAL"
            if is_linear
            else f"{currency.upper()}-PERPETUAL"
        )
        amount_tick = 0.1
        amount = round(int(quantity / amount_tick) * amount_tick, 10)
        if amount <= 0:
            return OrderResult(
                success=False,
                error=f"Hedge quantity below minimum tick: {quantity}",
                instrument_name=instrument_name,
            )

        try:
            if direction == "buy":
                result = await self.client.buy(
                    instrument_name=instrument_name,
                    amount=amount,
                    price=None,
                    order_type="market",
                )
            else:
                result = await self.client.sell(
                    instrument_name=instrument_name,
                    amount=amount,
                    price=None,
                    order_type="market",
                )
        except DeribitError as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_api_error()
            return OrderResult(
                success=False,
                error=e.message,
                instrument_name=instrument_name,
            )
        except Exception as e:
            return OrderResult(success=False, error=str(e), instrument_name=instrument_name)

        order = result.get("order", {})
        trades = result.get("trades", [])
        filled_amount = sum(t.get("amount", 0) for t in trades)
        if trades:
            total_value = sum(t.get("amount", 0) * t.get("price", 0) for t in trades)
            average_price = total_value / filled_amount if filled_amount > 0 else 0
        else:
            average_price = order.get("average_price", 0)
            filled_amount = order.get("filled_amount", 0)

        total_fee = sum(t.get("fee", 0) for t in trades)
        fee_currency = trades[0].get("fee_currency") if trades else None

        if filled_amount <= 0:
            return OrderResult(
                success=False,
                order_id=order.get("order_id"),
                filled_amount=0.0,
                average_price=0.0,
                error="Zero fill - hedge not executed",
                instrument_name=instrument_name,
            )

        if filled_amount < amount * 0.95:
            return OrderResult(
                success=False,
                order_id=order.get("order_id"),
                filled_amount=filled_amount,
                average_price=average_price,
                fee=total_fee,
                fee_currency=fee_currency,
                error=f"Partial hedge fill: {filled_amount}/{amount}",
                instrument_name=instrument_name,
            )

        return OrderResult(
            success=True,
            order_id=order.get("order_id"),
            filled_amount=filled_amount,
            average_price=average_price,
            fee=total_fee,
            fee_currency=fee_currency,
            instrument_name=instrument_name,
        )

    async def _execute_leg(
        self,
        contract: OptionContract,
        direction: str,
        quantity: float,
        btc_price: float,
        use_market_order_override: Optional[bool] = None,
    ) -> OrderResult:
        """Execute a single leg of an order.

        Args:
            contract: Option contract to trade.
            direction: 'buy' or 'sell'.
            quantity: Position size in BTC.
            btc_price: Current BTC price.

        Returns:
            OrderResult with execution details.
        """
        # Determine minimum and tick size based on instrument type
        # BTC inverse options: 0.1 minimum, 0.1 tick
        # ETH inverse options: 1.0 minimum, 1.0 tick (contract_size=1, min_trade_amount=1)
        # USDC linear options (ETH_USDC-, BTC_USDC-): 0.1 minimum, 0.1 tick
        if contract.instrument_name.startswith(("ETH_USDC-", "BTC_USDC-")):
            min_amount = 0.1
            amount_tick = 0.1
        elif contract.instrument_name.startswith("ETH-"):
            min_amount = 1.0
            amount_tick = 1.0
        else:
            min_amount = 0.1
            amount_tick = 0.1

        # Round down to valid tick size, then enforce minimum
        amount = int(quantity / amount_tick) * amount_tick
        amount = max(amount, min_amount)

        use_market_order = (
            self.use_market_orders
            if use_market_order_override is None
            else use_market_order_override
        )
        order_type = "market" if use_market_order else "limit"

        # For limit orders, use mid price with a small buffer
        # 1% buffer empirically chosen: wide enough to fill in normal conditions,
        # tight enough to avoid excessive slippage. Deribit options typically have
        # 1-3% bid-ask spreads, so 1% buffer crosses ~half the spread.
        price = None
        if not use_market_order:
            mid = contract.mid_price
            if mid is not None:
                buffer = mid * 0.01
                price = mid + buffer if direction == "buy" else mid - buffer
                # USDC linear options: $0.20 tick size (min price)
                # Inverse options: 0.0001 BTC/ETH minimum
                if contract.instrument_name.startswith(("ETH_USDC-", "BTC_USDC-")):
                    price = max(price, 0.20)
                else:
                    price = max(price, 0.0001)

        logger.info(
            f"Order params: instrument={contract.instrument_name}, "
            f"direction={direction}, amount={amount}, type={order_type}, price={price}"
        )

        for attempt in range(MAX_RETRIES):
            try:
                if direction == "buy":
                    result = await self.client.buy(
                        instrument_name=contract.instrument_name,
                        amount=amount,
                        price=price,
                        order_type=order_type,
                    )
                else:
                    result = await self.client.sell(
                        instrument_name=contract.instrument_name,
                        amount=amount,
                        price=price,
                        order_type=order_type,
                    )

                # Parse result
                order = result.get("order", {})
                trades = result.get("trades", [])

                filled_amount = sum(t.get("amount", 0) for t in trades)
                if trades:
                    total_value = sum(
                        t.get("amount", 0) * t.get("price", 0) for t in trades
                    )
                    average_price = total_value / filled_amount if filled_amount > 0 else 0
                else:
                    average_price = order.get("average_price", 0)
                    filled_amount = order.get("filled_amount", 0)

                # Extract fees from trade fills (Deribit returns fee per fill)
                total_fee = sum(t.get("fee", 0) for t in trades)
                fee_currency = trades[0].get("fee_currency") if trades else None

                logger.info(
                    f"Order executed: {direction} {amount} {contract.instrument_name} "
                    f"@ {average_price:.6f} (filled: {filled_amount})"
                )

                # Treat zero fill as failure - order didn't execute.
                # Cancel the order to prevent it sitting as a stale limit
                # order on the exchange (Session 69: stale buy order filled
                # silently, closing a leg without DB awareness).
                if filled_amount <= 0:
                    stale_order_id = order.get("order_id")
                    order_state = order.get("order_state", "unknown")
                    logger.warning(
                        f"Order returned zero fill: {contract.instrument_name} "
                        f"(order_state={order_state})"
                    )
                    if stale_order_id and order_state in ("open", "untriggered"):
                        try:
                            await self.client.cancel(stale_order_id)
                            logger.info(
                                f"Cancelled stale order {stale_order_id} "
                                f"({contract.instrument_name})"
                            )
                        except Exception as cancel_err:
                            logger.error(
                                f"Failed to cancel stale order {stale_order_id}: "
                                f"{cancel_err}"
                            )
                    return OrderResult(
                        success=False,
                        order_id=stale_order_id,
                        filled_amount=0.0,
                        average_price=0.0,
                        error="Zero fill - order not executed",
                        instrument_name=contract.instrument_name,
                    )

                # Detect partial fills (5% tolerance for rounding)
                if filled_amount < amount * 0.95:
                    logger.warning(
                        f"Partial fill: {filled_amount}/{amount} {contract.instrument_name}"
                    )
                    return OrderResult(
                        success=False,
                        order_id=order.get("order_id"),
                        filled_amount=filled_amount,
                        average_price=average_price,
                        fee=total_fee,
                        fee_currency=fee_currency,
                        error=f"Partial fill: {filled_amount}/{amount}",
                        instrument_name=contract.instrument_name,
                    )

                return OrderResult(
                    success=True,
                    order_id=order.get("order_id"),
                    filled_amount=filled_amount,
                    average_price=average_price,
                    fee=total_fee,
                    fee_currency=fee_currency,
                    instrument_name=contract.instrument_name,
                )

            except DeribitError as e:
                logger.warning(
                    f"Order attempt {attempt + 1}/{MAX_RETRIES} failed: code={e.code} msg={e.message} "
                    f"(instrument={contract.instrument_name}, amount={amount})"
                )

                # Exponential backoff
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_RETRY_DELAY * (2 ** attempt)
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Unexpected error executing order: {e}")
                return OrderResult(
                    success=False,
                    error=str(e),
                    instrument_name=contract.instrument_name,
                )

        # Record API error only after ALL retries exhausted (not per-attempt)
        if self.circuit_breaker:
            self.circuit_breaker.record_api_error()

        return OrderResult(
            success=False,
            error=f"Failed after {MAX_RETRIES} attempts",
            instrument_name=contract.instrument_name,
        )

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an existing order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            OrderResult indicating success/failure.
        """
        try:
            await self.client.cancel(order_id)
            return OrderResult(
                success=True,
                order_id=order_id,
            )
        except DeribitError as e:
            logger.error(f"Failed to cancel order {order_id}: {e.message}")
            return OrderResult(
                success=False,
                order_id=order_id,
                error=e.message,
            )
