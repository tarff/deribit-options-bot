"""Tests for synthetic option chain generator."""

from datetime import datetime, timezone

from src.backtest.option_chain_generator import (
    SyntheticChainConfig,
    SyntheticOptionChainGenerator,
)


class TestSyntheticOptionChainGenerator:
    """Tests for SyntheticOptionChainGenerator."""

    def test_generate_creates_puts_and_calls(self) -> None:
        """Generate should create both puts and calls."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        puts = [c for c in chain if c.option_type == "put"]
        calls = [c for c in chain if c.option_type == "call"]

        assert len(puts) > 0
        assert len(calls) > 0

    def test_generate_strikes_centered_on_spot(self) -> None:
        """Strikes should be centered around spot price."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        strikes = sorted(set(c.strike for c in chain))
        # Should have strikes above and below spot
        assert min(strikes) < 100000.0
        assert max(strikes) > 100000.0

    def test_delta_atm_near_half(self) -> None:
        """ATM options should have delta near 0.50."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        # Find ATM call (strike closest to spot)
        calls = [c for c in chain if c.option_type == "call"]
        atm_call = min(calls, key=lambda c: abs(c.strike - 100000.0))

        assert atm_call.delta is not None
        assert 0.40 <= atm_call.delta <= 0.60

    def test_bid_less_than_ask(self) -> None:
        """Bid should be less than ask (positive spread)."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        for contract in chain:
            assert contract.bid is not None
            assert contract.ask is not None
            assert contract.bid < contract.ask

    def test_custom_config(self) -> None:
        """Generator should respect custom config."""
        config = SyntheticChainConfig(
            dte_list=[30],
            strikes_above_atm=2,
            strikes_below_atm=2,
        )
        generator = SyntheticOptionChainGenerator(config)
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        # 5 strikes (ATM + 2 above + 2 below) × 2 types × 1 DTE = 10 contracts
        assert len(chain) == 10

    def test_extreme_high_dvol_produces_higher_premiums(self) -> None:
        """High DVOL (crisis) should produce higher premiums."""
        generator = SyntheticOptionChainGenerator()
        now = datetime.now(timezone.utc)

        normal_chain = generator.generate(spot_price=100000.0, dvol=50.0, timestamp=now)
        high_chain = generator.generate(spot_price=100000.0, dvol=120.0, timestamp=now)

        # Find ATM calls for comparison
        normal_atm = min(
            [c for c in normal_chain if c.option_type == "call"],
            key=lambda c: abs(c.strike - 100000.0)
        )
        high_atm = min(
            [c for c in high_chain if c.option_type == "call"],
            key=lambda c: abs(c.strike - 100000.0)
        )

        # Higher DVOL should mean higher premium
        assert high_atm.mark_price > normal_atm.mark_price

    def test_low_dvol_produces_lower_premiums(self) -> None:
        """Low DVOL (calm market) should produce lower premiums."""
        generator = SyntheticOptionChainGenerator()
        now = datetime.now(timezone.utc)

        normal_chain = generator.generate(spot_price=100000.0, dvol=50.0, timestamp=now)
        low_chain = generator.generate(spot_price=100000.0, dvol=25.0, timestamp=now)

        # Find ATM puts for comparison
        normal_atm = min(
            [c for c in normal_chain if c.option_type == "put"],
            key=lambda c: abs(c.strike - 100000.0)
        )
        low_atm = min(
            [c for c in low_chain if c.option_type == "put"],
            key=lambda c: abs(c.strike - 100000.0)
        )

        # Lower DVOL should mean lower premium
        assert low_atm.mark_price < normal_atm.mark_price

    def test_put_delta_is_negative(self) -> None:
        """Put options should have negative delta."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        puts = [c for c in chain if c.option_type == "put"]
        for put in puts:
            assert put.delta is not None
            assert put.delta < 0, f"Put at strike {put.strike} has positive delta {put.delta}"

    def test_call_delta_is_positive(self) -> None:
        """Call options should have positive delta."""
        generator = SyntheticOptionChainGenerator()
        chain = generator.generate(
            spot_price=100000.0,
            dvol=50.0,
            timestamp=datetime.now(timezone.utc),
        )

        calls = [c for c in chain if c.option_type == "call"]
        for call in calls:
            assert call.delta is not None
            assert call.delta > 0, f"Call at strike {call.strike} has negative delta {call.delta}"
