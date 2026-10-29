"""Tests for data models."""

from datetime import datetime, timezone

from src.persistence.models import Trade, Position, MarketSnapshot, TradeStatus, PositionStatus


def test_trade_creation() -> None:
    """Test creating a trade model."""
    trade = Trade(
        strategy_id="WHL-001",
        strategy_type="wheel",
        order_id="ORD-123",
        instrument="BTC-28MAR25-100000-P",
        side="sell",
        quantity=0.1,
        price=1500.0,
        status=TradeStatus.FILLED,
        opened_at=datetime.now(timezone.utc),
    )

    assert trade.strategy_id == "WHL-001"
    assert trade.status == TradeStatus.FILLED
    assert trade.pnl is None  # Not set yet


def test_position_with_greeks() -> None:
    """Test position model with Greeks."""
    position = Position(
        strategy_id="IC-001",
        strategy_type="iron_condor",
        status=PositionStatus.OPEN,
        phase="active",
        entry_price=97000.0,
        max_profit=500.0,
        max_loss=2000.0,
        delta=-0.03,
        gamma=0.002,
        theta=47.0,
        vega=-15.0,
        opened_at=datetime.now(timezone.utc),
    )

    assert position.delta == -0.03
    assert position.theta == 47.0


def test_market_snapshot() -> None:
    """Test market snapshot model."""
    snapshot = MarketSnapshot(
        btc_price=97432.50,
        dvol=52.3,
        iv_rank=0.67,
        rv_7d=48.2,
        rv_30d=45.1,
        iv_rv_spread=4.1,
        term_structure_ratio=1.05,
        rr_skew=-2.1,
        regime="high_iv",
        timestamp=datetime.now(timezone.utc),
    )

    assert snapshot.btc_price == 97432.50
    assert snapshot.regime == "high_iv"
