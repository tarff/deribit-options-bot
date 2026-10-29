"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def sample_btc_price() -> float:
    """Sample BTC price for testing."""
    return 97432.50
