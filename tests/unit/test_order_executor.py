"""Tests for OrderExecutor."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.brain.signal import TradeSignal, SignalAction, StrategyType, OptionContract
from src.data.deribit_client import DeribitClient, DeribitError
from src.execution.order_executor import OrderExecutor, OrderResult
from src.risk.circuit_breaker import CircuitBreaker, BreakerConfig


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock Deribit client."""
    client = MagicMock(spec=DeribitClient)
    return client


@pytest.fixture
def circuit_breaker() -> CircuitBreaker:
    """Create a circuit breaker for testing."""
    return CircuitBreaker(BreakerConfig())


@pytest.fixture
def executor(mock_client: MagicMock, circuit_breaker: CircuitBreaker) -> OrderExecutor:
    """Create an OrderExecutor with mock client."""
    return OrderExecutor(mock_client, circuit_breaker, use_market_orders=True)


@pytest.fixture
def sample_contract() -> OptionContract:
    """Create a sample option contract."""
    return OptionContract(
        instrument_name="BTC-28MAR25-100000-P",
        strike=100000.0,
        expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        bid=0.015,
        ask=0.017,
        mark_price=0.016,
    )


@pytest.fixture
def sample_signal(sample_contract: OptionContract) -> TradeSignal:
    """Create a sample trade signal."""
    return TradeSignal(
        strategy_type=StrategyType.WHEEL,
        action=SignalAction.OPEN,
        contracts=[sample_contract],
        direction="sell",
        quantity=0.1,
        reason="Test signal",
    )


@pytest.mark.asyncio
async def test_execute_leg_success(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test successful single leg execution."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order123",
            "filled_amount": 0.1,
            "average_price": 0.016,
        },
        "trades": [
            {"amount": 0.1, "price": 0.016}
        ],
    })

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert result.success
    assert result.order_id == "order123"
    assert result.filled_amount == 0.1
    assert result.average_price == 0.016
    mock_client.sell.assert_called_once()


@pytest.mark.asyncio
async def test_execute_leg_buy(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test buy order execution."""
    mock_client.buy = AsyncMock(return_value={
        "order": {
            "order_id": "order456",
            "filled_amount": 0.1,
            "average_price": 0.017,
        },
        "trades": [],
    })

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="buy",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert result.success
    assert result.order_id == "order456"
    mock_client.buy.assert_called_once()


@pytest.mark.asyncio
async def test_execute_hedge_places_underlying_perpetual_order(
    executor: OrderExecutor,
    mock_client: MagicMock,
) -> None:
    """Hedge execution should trade the underlying perpetual, not options."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "hedge123",
            "filled_amount": 0.2,
            "average_price": 2500.0,
        },
        "trades": [
            {"amount": 0.2, "price": 2500.0, "fee": 0.05, "fee_currency": "USDC"}
        ],
    })

    result = await executor.execute_hedge(
        currency="ETH",
        is_linear=True,
        direction="sell",
        quantity=0.24,
    )

    assert result.success
    assert result.instrument_name == "ETH_USDC-PERPETUAL"
    assert result.filled_amount == 0.2
    mock_client.sell.assert_called_once_with(
        instrument_name="ETH_USDC-PERPETUAL",
        amount=0.2,
        price=None,
        order_type="market",
    )


@pytest.mark.asyncio
async def test_execute_signal_single_leg(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_signal: TradeSignal,
) -> None:
    """Test executing a single-leg signal."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order123",
            "filled_amount": 0.1,
            "average_price": 0.016,
        },
        "trades": [{"amount": 0.1, "price": 0.016}],
    })

    results = await executor.execute_signal(sample_signal, 100000.0)

    assert len(results) == 1
    assert results[0].success
    assert results[0].order_id == "order123"


@pytest.mark.asyncio
async def test_execute_signal_multi_leg(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test executing a multi-leg signal (iron condor)."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)
    contracts = [
        OptionContract(
            instrument_name=f"BTC-28MAR25-{strike}-{opt_type[0].upper()}",
            strike=strike,
            expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
            option_type=opt_type,
            delta=delta,
            bid=0.01,
            ask=0.012,
            mark_price=0.011,
        )
        for strike, opt_type, delta in [
            (90000, "put", -0.15),
            (85000, "put", -0.05),
            (110000, "call", 0.15),
            (115000, "call", 0.05),
        ]
    ]

    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=contracts,
        direction="sell",
        quantity=0.1,
        legs_direction=["sell", "buy", "sell", "buy"],
        reason="Iron condor entry",
    )

    call_count = 0

    async def mock_order(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "order": {"order_id": f"order{call_count}", "filled_amount": 0.1, "average_price": 0.011},
            "trades": [{"amount": 0.1, "price": 0.011}],
        }

    mock_client.sell = AsyncMock(side_effect=mock_order)
    mock_client.buy = AsyncMock(side_effect=mock_order)

    results = await executor.execute_signal(signal, 100000.0)

    assert len(results) == 4
    assert all(r.success for r in results)
    # Verify correct directions: sell, buy, sell, buy
    assert mock_client.sell.call_count == 2
    assert mock_client.buy.call_count == 2


@pytest.mark.asyncio
async def test_execute_signal_rejects_multi_leg_market_open(
    executor: OrderExecutor,
    mock_client: MagicMock,
) -> None:
    """Multi-leg opening trades should not use uncapped sequential market orders."""
    expiry = datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-28MAR25-90000-P",
            strike=90000,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
            bid=0.01,
            ask=0.012,
        ),
        OptionContract(
            instrument_name="BTC-28MAR25-85000-P",
            strike=85000,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
            bid=0.004,
            ask=0.005,
        ),
    ]
    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=contracts,
        direction="sell",
        quantity=0.1,
        legs_direction=["sell", "buy"],
        reason="Iron condor entry",
    )

    results = await executor.execute_signal(signal, 100000.0)

    assert len(results) == 1
    assert not results[0].success
    assert "limit orders" in (results[0].error or "")
    mock_client.sell.assert_not_called()
    mock_client.buy.assert_not_called()


@pytest.mark.asyncio
async def test_execute_signal_uses_market_orders_for_closes_when_entries_use_limits(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Close signals should prioritize risk reduction even when entries use limits."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)
    expiry = datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-28MAR25-90000-P",
            strike=90000,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
            bid=0.01,
            ask=0.012,
        ),
        OptionContract(
            instrument_name="BTC-28MAR25-85000-P",
            strike=85000,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
            bid=0.004,
            ask=0.005,
        ),
    ]
    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.CLOSE,
        contracts=contracts,
        direction="buy",
        quantity=0.1,
        legs_direction=["buy", "sell"],
        reason="DTE exit",
    )
    mock_client.buy = AsyncMock(return_value={
        "order": {"order_id": "close1", "filled_amount": 0.1, "average_price": 0.012},
        "trades": [{"amount": 0.1, "price": 0.012}],
    })
    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "close2", "filled_amount": 0.1, "average_price": 0.004},
        "trades": [{"amount": 0.1, "price": 0.004}],
    })

    results = await executor.execute_signal(signal, 100000.0)

    assert len(results) == 2
    assert all(r.success for r in results)
    assert mock_client.buy.call_args.kwargs["order_type"] == "market"
    assert mock_client.buy.call_args.kwargs["price"] is None
    assert mock_client.sell.call_args.kwargs["order_type"] == "market"
    assert mock_client.sell.call_args.kwargs["price"] is None


@pytest.mark.asyncio
async def test_execute_signal_continues_close_after_leg_failure(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Close signals should try remaining legs even if one close leg fails."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)
    expiry = datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc)
    contracts = [
        OptionContract(
            instrument_name="BTC-28MAR25-90000-P",
            strike=90000,
            expiry=expiry,
            option_type="put",
            delta=-0.15,
            bid=0.01,
            ask=0.012,
        ),
        OptionContract(
            instrument_name="BTC-28MAR25-85000-P",
            strike=85000,
            expiry=expiry,
            option_type="put",
            delta=-0.05,
            bid=0.004,
            ask=0.005,
        ),
    ]
    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.CLOSE,
        contracts=contracts,
        direction="buy",
        quantity=0.1,
        legs_direction=["buy", "sell"],
        reason="DTE exit",
    )
    mock_client.buy = AsyncMock(side_effect=DeribitError(10001, "Error"))
    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "close2", "filled_amount": 0.1, "average_price": 0.004},
        "trades": [{"amount": 0.1, "price": 0.004}],
    })

    results = await executor.execute_signal(signal, 100000.0)

    assert len(results) == 2
    assert not results[0].success
    assert results[1].success
    mock_client.sell.assert_called_once()


@pytest.mark.asyncio
async def test_execute_leg_retry_on_error(
    executor: OrderExecutor,
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
    sample_contract: OptionContract,
) -> None:
    """Test retry logic on API error."""
    # Fail twice, succeed third time
    mock_client.sell = AsyncMock(side_effect=[
        DeribitError(10001, "Temporary error"),
        DeribitError(10001, "Temporary error"),
        {
            "order": {"order_id": "order123", "filled_amount": 0.1, "average_price": 0.016},
            "trades": [{"amount": 0.1, "price": 0.016}],
        },
    ])

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert result.success
    assert mock_client.sell.call_count == 3


@pytest.mark.asyncio
async def test_execute_leg_fail_after_retries(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that execution fails after max retries."""
    mock_client.sell = AsyncMock(side_effect=DeribitError(10001, "Persistent error"))

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert not result.success
    assert "Failed after 3 attempts" in result.error
    assert mock_client.sell.call_count == 3


@pytest.mark.asyncio
async def test_execute_signal_stops_on_leg_failure(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that multi-leg execution stops when a leg fails."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)
    contracts = [
        OptionContract(
            instrument_name=f"BTC-28MAR25-{strike}-P",
            strike=strike,
            expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
            option_type="put",
            delta=-0.15,
            bid=0.01,
            ask=0.012,
            mark_price=0.011,
        )
        for strike in [90000, 85000, 80000]
    ]

    signal = TradeSignal(
        strategy_type=StrategyType.IRON_CONDOR,
        action=SignalAction.OPEN,
        contracts=contracts,
        direction="sell",
        quantity=0.1,
        legs_direction=["sell", "buy", "sell"],
        reason="Test",
    )

    # First leg succeeds, second fails
    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "order1", "filled_amount": 0.1, "average_price": 0.011},
        "trades": [{"amount": 0.1, "price": 0.011}],
    })
    mock_client.buy = AsyncMock(side_effect=DeribitError(10001, "Error"))

    results = await executor.execute_signal(signal, 100000.0)

    assert len(results) == 2
    assert results[0].success
    assert not results[1].success
    assert mock_client.sell.call_count == 1


@pytest.mark.asyncio
async def test_cancel_order_success(
    executor: OrderExecutor,
    mock_client: MagicMock,
) -> None:
    """Test successful order cancellation."""
    mock_client.cancel = AsyncMock(return_value={"order_id": "order123"})

    result = await executor.cancel_order("order123")

    assert result.success
    assert result.order_id == "order123"


@pytest.mark.asyncio
async def test_cancel_order_failure(
    executor: OrderExecutor,
    mock_client: MagicMock,
) -> None:
    """Test order cancellation failure."""
    mock_client.cancel = AsyncMock(side_effect=DeribitError(10001, "Order not found"))

    result = await executor.cancel_order("invalid_id")

    assert not result.success
    assert result.error == "Order not found"


def test_order_result_dataclass() -> None:
    """Test OrderResult dataclass defaults."""
    result = OrderResult(success=True, order_id="123")

    assert result.success
    assert result.order_id == "123"
    assert result.filled_amount == 0.0
    assert result.average_price == 0.0
    assert result.error is None


@pytest.mark.asyncio
async def test_limit_orders(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
    sample_contract: OptionContract,
) -> None:
    """Test that limit orders use price from mid with buffer."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)

    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "order123", "filled_amount": 0.1, "average_price": 0.015},
        "trades": [],
    })

    await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    # Check that price was passed for limit order
    call_args = mock_client.sell.call_args
    assert call_args.kwargs.get("order_type") == "limit"
    assert call_args.kwargs.get("price") is not None


@pytest.mark.asyncio
async def test_eth_minimum_amount(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that ETH options use 1.0 minimum, BTC uses 0.1."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=True)

    # Create ETH option contract
    eth_contract = OptionContract(
        instrument_name="ETH-28MAR25-2800-P",
        strike=2800.0,
        expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        bid=0.015,
        ask=0.017,
    )

    # Create BTC option contract
    btc_contract = OptionContract(
        instrument_name="BTC-28MAR25-100000-P",
        strike=100000.0,
        expiry=datetime(2025, 3, 28, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        bid=0.015,
        ask=0.017,
    )

    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "order123", "filled_amount": 1.0, "average_price": 0.015},
        "trades": [],
    })

    # ETH option with small quantity should use 1.0 minimum
    await executor._execute_leg(
        contract=eth_contract,
        direction="sell",
        quantity=0.1,  # Small quantity
        btc_price=2800.0,
    )

    call_args = mock_client.sell.call_args
    assert call_args.kwargs.get("amount") == 1.0  # Should be 1.0 for ETH

    mock_client.sell.reset_mock()

    # BTC option with small quantity should use 0.1 minimum
    await executor._execute_leg(
        contract=btc_contract,
        direction="sell",
        quantity=0.05,  # Small quantity
        btc_price=100000.0,
    )

    call_args = mock_client.sell.call_args
    assert call_args.kwargs.get("amount") == 0.1  # Should be 0.1 for BTC


@pytest.mark.asyncio
async def test_usdc_linear_minimum_amount(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that USDC linear options use 0.1 minimum (not 1.0 like ETH inverse)."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=True)

    # Create ETH_USDC linear option contract
    usdc_contract = OptionContract(
        instrument_name="ETH_USDC-27FEB26-2100-P",
        strike=2100.0,
        expiry=datetime(2026, 2, 27, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.25,
        bid=151.0,
        ask=155.0,
    )

    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "order_usdc", "filled_amount": 0.1, "average_price": 151.0},
        "trades": [{"amount": 0.1, "price": 151.0}],
    })

    await executor._execute_leg(
        contract=usdc_contract,
        direction="sell",
        quantity=0.1,
        btc_price=2700.0,
    )

    call_args = mock_client.sell.call_args
    assert call_args.kwargs.get("amount") == 0.1  # USDC linear: 0.1 min (not 1.0)


@pytest.mark.asyncio
async def test_usdc_linear_price_floor(
    mock_client: MagicMock,
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that USDC linear options use $0.20 price floor, not 0.0001."""
    executor = OrderExecutor(mock_client, circuit_breaker, use_market_orders=False)

    # Create a USDC option with very low mid price
    usdc_contract = OptionContract(
        instrument_name="ETH_USDC-27FEB26-2100-P",
        strike=2100.0,
        expiry=datetime(2026, 2, 27, 8, 0, tzinfo=timezone.utc),
        option_type="put",
        delta=-0.05,
        bid=0.05,  # Very low bid
        ask=0.10,  # Very low ask → mid = 0.075
    )

    mock_client.sell = AsyncMock(return_value={
        "order": {"order_id": "order_usdc2", "filled_amount": 0.1, "average_price": 0.20},
        "trades": [],
    })

    await executor._execute_leg(
        contract=usdc_contract,
        direction="sell",
        quantity=0.1,
        btc_price=2700.0,
    )

    call_args = mock_client.sell.call_args
    # Price should be floored to $0.20 (USDC tick size), not 0.0001
    assert call_args.kwargs.get("price") >= 0.20


@pytest.mark.asyncio
async def test_zero_fill_treated_as_failure(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that zero fill is treated as a failure, not success."""
    # Simulate order that returns but with zero fill
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order123",
            "filled_amount": 0.0,
            "average_price": 0.0,
            "order_state": "cancelled",
        },
        "trades": [],
    })

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    # Should be treated as failure
    assert not result.success
    assert result.filled_amount == 0.0
    assert "Zero fill" in result.error


@pytest.mark.asyncio
async def test_successful_fill_succeeds(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that non-zero fill is treated as success."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order123",
            "filled_amount": 0.1,
            "average_price": 0.015,
            "order_state": "filled",
        },
        "trades": [{"amount": 0.1, "price": 0.015}],
    })

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert result.success
    assert result.filled_amount == 0.1
    assert result.error is None


@pytest.mark.asyncio
async def test_zero_fill_cancels_stale_open_order(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that zero-fill cancels stale order left on exchange."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "stale_order_123",
            "filled_amount": 0.0,
            "average_price": 0.0,
            "order_state": "open",
        },
        "trades": [],
    })
    mock_client.cancel = AsyncMock(return_value={})

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert not result.success
    assert "Zero fill" in result.error
    # Stale order should be cancelled
    mock_client.cancel.assert_called_once_with("stale_order_123")


@pytest.mark.asyncio
async def test_zero_fill_skips_cancel_for_non_open_order(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that zero-fill does not cancel already-cancelled/filled orders."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order_456",
            "filled_amount": 0.0,
            "average_price": 0.0,
            "order_state": "cancelled",
        },
        "trades": [],
    })
    mock_client.cancel = AsyncMock()

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    assert not result.success
    # Should NOT try to cancel an already-cancelled order
    mock_client.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_zero_fill_cancel_failure_does_not_crash(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that cancel failure after zero-fill is handled gracefully."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "stale_order_789",
            "filled_amount": 0.0,
            "average_price": 0.0,
            "order_state": "open",
        },
        "trades": [],
    })
    mock_client.cancel = AsyncMock(side_effect=Exception("Network error"))

    result = await executor._execute_leg(
        contract=sample_contract,
        direction="sell",
        quantity=0.1,
        btc_price=100000.0,
    )

    # Should still return failure result even if cancel fails
    assert not result.success
    assert "Zero fill" in result.error
    mock_client.cancel.assert_called_once_with("stale_order_789")


@pytest.mark.asyncio
async def test_fee_extracted_from_trades(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that fees are extracted from trade objects in API response."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order_fee_test",
            "filled_amount": 0.1,
            "average_price": 0.016,
        },
        "trades": [
            {"amount": 0.1, "price": 0.016, "fee": 0.000015, "fee_currency": "ETH"}
        ],
    })
    result = await executor._execute_leg(
        contract=sample_contract, direction="sell", quantity=0.1, btc_price=100000.0,
    )
    assert result.success
    assert result.fee == 0.000015
    assert result.fee_currency == "ETH"


@pytest.mark.asyncio
async def test_fee_summed_across_multiple_trades(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that fees are summed across multiple trade fills."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order_multi_fee",
            "filled_amount": 0.1,
            "average_price": 0.016,
        },
        "trades": [
            {"amount": 0.05, "price": 0.016, "fee": 0.000008, "fee_currency": "ETH"},
            {"amount": 0.05, "price": 0.016, "fee": 0.000007, "fee_currency": "ETH"},
        ],
    })
    result = await executor._execute_leg(
        contract=sample_contract, direction="sell", quantity=0.1, btc_price=100000.0,
    )
    assert result.success
    assert result.fee == pytest.approx(0.000015)
    assert result.fee_currency == "ETH"


@pytest.mark.asyncio
async def test_fee_defaults_to_zero_when_missing(
    executor: OrderExecutor,
    mock_client: MagicMock,
    sample_contract: OptionContract,
) -> None:
    """Test that fee defaults to 0 when trades have no fee field."""
    mock_client.sell = AsyncMock(return_value={
        "order": {
            "order_id": "order_no_fee",
            "filled_amount": 0.1,
            "average_price": 0.016,
        },
        "trades": [
            {"amount": 0.1, "price": 0.016}
        ],
    })
    result = await executor._execute_leg(
        contract=sample_contract, direction="sell", quantity=0.1, btc_price=100000.0,
    )
    assert result.success
    assert result.fee == 0.0
    assert result.fee_currency is None
