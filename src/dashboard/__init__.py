"""Dashboard module for visualizing trading data."""

from src.dashboard.data_provider import (
    DashboardDataProvider,
    DEFAULT_HISTORICAL_DAYS,
    DEFAULT_REGIME_DAYS,
)
from src.dashboard.charts import (
    create_price_chart,
    create_dvol_chart,
    create_regime_pie_chart,
    create_price_dvol_dual_axis,
    create_candlestick_chart,
)
from src.dashboard.models import (
    LiveMarketData,
    LivePosition,
    AccountInfo,
)
from src.dashboard.live_data_provider import LiveDataProvider

__all__ = [
    "DashboardDataProvider",
    "DEFAULT_HISTORICAL_DAYS",
    "DEFAULT_REGIME_DAYS",
    "create_price_chart",
    "create_dvol_chart",
    "create_regime_pie_chart",
    "create_price_dvol_dual_axis",
    "create_candlestick_chart",
    "LiveMarketData",
    "LivePosition",
    "AccountInfo",
    "LiveDataProvider",
]
