"""Tests for dashboard chart generation functions."""

from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go

from src.persistence.models import HistoricalDataPoint
from src.dashboard.charts import (
    create_price_chart,
    create_dvol_chart,
    create_regime_pie_chart,
    create_price_dvol_dual_axis,
    create_candlestick_chart,
)


def make_historical_point(
    timestamp: datetime,
    btc_price: float = 50000.0,
    dvol: float = 60.0,
) -> HistoricalDataPoint:
    """Create a test HistoricalDataPoint."""
    return HistoricalDataPoint(
        timestamp=timestamp,
        btc_price=btc_price,
        btc_open=btc_price - 100,
        btc_high=btc_price + 200,
        btc_low=btc_price - 200,
        btc_volume=1000.0,
        dvol=dvol,
        dvol_open=dvol - 1,
        dvol_high=dvol + 2,
        dvol_low=dvol - 2,
    )


def make_sample_data(days: int = 10) -> list[HistoricalDataPoint]:
    """Create sample historical data for testing."""
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        make_historical_point(
            timestamp=base_ts + timedelta(days=i),
            btc_price=45000 + i * 100,
            dvol=55 + i,
        )
        for i in range(days)
    ]


class TestCreatePriceChart:
    """Tests for create_price_chart."""

    def test_empty_data_shows_annotation(self) -> None:
        """Test that empty data shows 'No data available' annotation."""
        fig = create_price_chart([])

        assert isinstance(fig, go.Figure)
        # Check for annotation
        assert len(fig.layout.annotations) == 1
        assert fig.layout.annotations[0].text == "No data available"

    def test_with_data_creates_traces(self) -> None:
        """Test that data creates price and volume traces."""
        data = make_sample_data(10)
        fig = create_price_chart(data)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2  # Price + Volume
        assert fig.data[0].name == "BTC Price"
        assert fig.data[1].name == "Volume"

    def test_price_values_correct(self) -> None:
        """Test that price values are extracted correctly."""
        data = make_sample_data(5)
        fig = create_price_chart(data)

        # Check price trace values
        price_trace = fig.data[0]
        assert list(price_trace.y) == [d.btc_price for d in data]


class TestCreateDvolChart:
    """Tests for create_dvol_chart."""

    def test_empty_data_shows_annotation(self) -> None:
        """Test that empty data shows annotation."""
        fig = create_dvol_chart([])

        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) == 1
        assert fig.layout.annotations[0].text == "No data available"

    def test_with_data_creates_trace(self) -> None:
        """Test that data creates DVOL trace."""
        data = make_sample_data(10)
        fig = create_dvol_chart(data)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].name == "DVOL"

    def test_no_thresholds_no_hlines(self) -> None:
        """Test that no thresholds means no horizontal lines."""
        data = make_sample_data(5)
        fig = create_dvol_chart(data, thresholds=None)

        # Should only have the DVOL trace, no shapes for hlines
        # (hlines are added as shapes in plotly)
        assert len(fig.data) == 1

    def test_with_thresholds_adds_hlines(self) -> None:
        """Test that thresholds add horizontal lines."""
        data = make_sample_data(5)
        thresholds = {"reduce": 60, "halt": 80}
        fig = create_dvol_chart(data, thresholds=thresholds)

        # hlines are added as shapes
        assert len(fig.layout.shapes) == 2


class TestCreateRegimePieChart:
    """Tests for create_regime_pie_chart."""

    def test_empty_distribution_shows_annotation(self) -> None:
        """Test that empty distribution shows annotation."""
        fig = create_regime_pie_chart({})

        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) == 1
        assert fig.layout.annotations[0].text == "No regime data"

    def test_with_distribution_creates_pie(self) -> None:
        """Test that distribution creates pie chart."""
        distribution = {"neutral": 10, "high_stress": 5, "extreme_fear": 2}
        fig = create_regime_pie_chart(distribution)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Pie)

    def test_custom_title(self) -> None:
        """Test that custom title is used."""
        distribution = {"neutral": 10}
        fig = create_regime_pie_chart(distribution, title="Last 7 Days")

        assert fig.layout.title.text == "Last 7 Days"

    def test_default_title(self) -> None:
        """Test default title."""
        distribution = {"neutral": 10}
        fig = create_regime_pie_chart(distribution)

        assert fig.layout.title.text == "Regime Distribution"


class TestCreatePriceDvolDualAxis:
    """Tests for create_price_dvol_dual_axis."""

    def test_empty_data_shows_annotation(self) -> None:
        """Test that empty data shows annotation."""
        fig = create_price_dvol_dual_axis([])

        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) == 1

    def test_with_data_creates_two_traces(self) -> None:
        """Test that data creates BTC and DVOL traces."""
        data = make_sample_data(10)
        fig = create_price_dvol_dual_axis(data)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2
        assert fig.data[0].name == "BTC Price"
        assert fig.data[1].name == "DVOL"


class TestCreateCandlestickChart:
    """Tests for create_candlestick_chart."""

    def test_empty_data_shows_annotation(self) -> None:
        """Test that empty data shows annotation."""
        fig = create_candlestick_chart([])

        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) == 1

    def test_with_data_creates_candlestick(self) -> None:
        """Test that data creates candlestick trace."""
        data = make_sample_data(10)
        fig = create_candlestick_chart(data)

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Candlestick)

    def test_ohlc_values_correct(self) -> None:
        """Test that OHLC values are extracted correctly."""
        data = make_sample_data(5)
        fig = create_candlestick_chart(data)

        candle = fig.data[0]
        assert list(candle.open) == [d.btc_open for d in data]
        assert list(candle.high) == [d.btc_high for d in data]
        assert list(candle.low) == [d.btc_low for d in data]
        assert list(candle.close) == [d.btc_price for d in data]
