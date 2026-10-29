"""Chart generation functions for dashboard.

Uses Plotly for interactive charts optimized for Streamlit display.
Terminal Noir theme - dark backgrounds with cyan/green/red accents.
"""
# mypy: ignore-errors

import logging
from typing import Callable

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.persistence.models import HistoricalDataPoint

logger = logging.getLogger(__name__)


# =============================================================================
# TERMINAL NOIR CHART THEME
# =============================================================================

CHART_COLORS = {
    "bg_primary": "#0D0D0F",
    "bg_secondary": "#151518",
    "bg_card": "#1E1E24",
    "border": "#2A2A32",
    "text_primary": "#FFFFFF",
    "text_secondary": "#A0A0B0",
    "text_muted": "#6B6B7B",
    "accent_cyan": "#00D9FF",
    "profit_green": "#00FF88",
    "loss_red": "#FF3366",
    "warning_amber": "#FFB800",
    "neutral_purple": "#8B5CF6",
    "btc_orange": "#F7931A",
    "grid": "#1A1A1F",
}

CHART_LAYOUT = dict(
    font=dict(
        family="JetBrains Mono, monospace",
        size=12,
        color=CHART_COLORS["text_secondary"],
    ),
    paper_bgcolor=CHART_COLORS["bg_primary"],
    plot_bgcolor=CHART_COLORS["bg_card"],
    margin=dict(l=60, r=40, t=60, b=40),
    hoverlabel=dict(
        bgcolor=CHART_COLORS["bg_secondary"],
        bordercolor=CHART_COLORS["border"],
        font=dict(
            family="JetBrains Mono, monospace",
            size=12,
            color=CHART_COLORS["text_primary"],
        ),
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        bordercolor=CHART_COLORS["border"],
        font=dict(color=CHART_COLORS["text_secondary"]),
    ),
)

AXIS_STYLE = dict(
    gridcolor=CHART_COLORS["grid"],
    gridwidth=1,
    linecolor=CHART_COLORS["border"],
    tickfont=dict(color=CHART_COLORS["text_muted"]),
    title_font=dict(color=CHART_COLORS["text_secondary"]),
    zerolinecolor=CHART_COLORS["border"],
)


def _validate_chart_data(
    data: list[HistoricalDataPoint],
    value_extractor: Callable[[HistoricalDataPoint], float | None],
    min_points: int = 2,
) -> tuple[list[HistoricalDataPoint], list[str]]:
    """Validate and clean chart data.

    Handles edge cases: insufficient data points, None values, unsorted dates.

    Args:
        data: Raw data points.
        value_extractor: Function to extract the value being charted.
        min_points: Minimum points required for a valid chart.

    Returns:
        Tuple of (cleaned_data, warnings).
    """
    warnings: list[str] = []

    if not data:
        return [], ["No data available"]

    # Filter out None values
    valid_data = [d for d in data if value_extractor(d) is not None]
    if len(valid_data) < len(data):
        dropped = len(data) - len(valid_data)
        warnings.append(f"Filtered {dropped} points with None values")

    if len(valid_data) < min_points:
        warnings.append(f"Insufficient data: {len(valid_data)} points (need {min_points})")
        return [], warnings

    # Sort by timestamp
    sorted_data = sorted(valid_data, key=lambda d: d.timestamp)

    # Check for duplicates
    seen_timestamps = set()
    unique_data = []
    for point in sorted_data:
        if point.timestamp not in seen_timestamps:
            seen_timestamps.add(point.timestamp)
            unique_data.append(point)
        else:
            warnings.append(f"Duplicate timestamp: {point.timestamp}")

    if warnings:
        for warning in warnings:
            logger.warning("Chart data issue: %s", warning)

    return unique_data, warnings


def _create_empty_figure(message: str = "No data available") -> go.Figure:
    """Create an empty figure with a message annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(
            size=16,
            color=CHART_COLORS["text_muted"],
            family="Outfit, sans-serif",
        ),
    )
    fig.update_layout(
        **CHART_LAYOUT,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )
    return fig


def create_price_chart(data: list[HistoricalDataPoint], currency: str = "BTC") -> go.Figure:
    """Create price chart with volume subplot.

    Args:
        data: List of HistoricalDataPoint objects.
        currency: Trading currency for chart title (e.g., "BTC", "ETH").

    Returns:
        Plotly Figure with price line and volume bars.
    """
    # Validate data
    clean_data, warnings = _validate_chart_data(
        data, lambda d: d.btc_price, min_points=2
    )
    if not clean_data:
        return _create_empty_figure(warnings[0] if warnings else "No data available")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    dates = [d.timestamp for d in clean_data]

    # Price line with gradient fill
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=[d.btc_price for d in clean_data],
            name=f"{currency} Price",
            line=dict(color=CHART_COLORS["btc_orange"], width=2),
            fill="tozeroy",
            fillcolor="rgba(247, 147, 26, 0.1)",
            hovertemplate="<b>$%{y:,.0f}</b><extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Volume bars
    fig.add_trace(
        go.Bar(
            x=dates,
            y=[d.btc_volume for d in clean_data],
            name="Volume",
            marker_color=CHART_COLORS["accent_cyan"],
            marker_opacity=0.4,
            hovertemplate="%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"{currency} Price",
            font=dict(
                family="Outfit, sans-serif",
                size=18,
                color=CHART_COLORS["text_primary"],
            ),
        ),
        height=500,
        showlegend=False,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text="Price (USD)", row=1, col=1)
    fig.update_yaxes(**AXIS_STYLE, title_text="Volume", row=2, col=1)

    return fig


def create_dvol_chart(
    data: list[HistoricalDataPoint],
    thresholds: dict[str, float] | None = None,
) -> go.Figure:
    """Create DVOL chart with threshold lines.

    Args:
        data: List of HistoricalDataPoint objects.
        thresholds: Dict mapping threshold names to values.

    Returns:
        Plotly Figure with DVOL line and threshold markers.
    """
    # Validate data
    clean_data, warnings = _validate_chart_data(
        data, lambda d: d.dvol, min_points=2
    )
    if not clean_data:
        return _create_empty_figure(warnings[0] if warnings else "No data available")

    fig = go.Figure()

    dates = [d.timestamp for d in clean_data]

    # DVOL line with gradient fill
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=[d.dvol for d in clean_data],
            name="DVOL",
            line=dict(color=CHART_COLORS["accent_cyan"], width=2),
            fill="tozeroy",
            fillcolor="rgba(0, 217, 255, 0.1)",
            hovertemplate="<b>%{y:.1f}</b><extra></extra>",
        )
    )

    # Threshold lines
    if thresholds:
        colors = {
            "reduce": CHART_COLORS["warning_amber"],
            "halt": CHART_COLORS["loss_red"],
            "emergency": CHART_COLORS["loss_red"],
        }
        for name, value in thresholds.items():
            fig.add_hline(
                y=value,
                line_dash="dash",
                line_color=colors.get(name, CHART_COLORS["text_muted"]),
                line_width=1,
                annotation_text=f"{name.title()} ({value})",
                annotation_position="right",
                annotation_font=dict(
                    size=10,
                    color=colors.get(name, CHART_COLORS["text_muted"]),
                ),
            )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text="DVOL (Deribit Volatility Index)",
            font=dict(
                family="Outfit, sans-serif",
                size=18,
                color=CHART_COLORS["text_primary"],
            ),
        ),
        height=400,
        hovermode="x unified",
    )

    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text="DVOL")

    return fig


def create_regime_pie_chart(
    distribution: dict[str, int],
    title: str = "Regime Distribution",
) -> go.Figure:
    """Create donut chart of regime distribution.

    Args:
        distribution: Dict mapping regime name to count.
        title: Chart title.

    Returns:
        Plotly Figure with donut chart.
    """
    if not distribution:
        return _create_empty_figure("No regime data")

    # Color scheme for regimes
    colors = {
        "neutral": CHART_COLORS["profit_green"],
        "high_iv_overpriced": CHART_COLORS["warning_amber"],
        "high_stress": CHART_COLORS["loss_red"],
        "low_iv_underpriced": CHART_COLORS["neutral_purple"],
        "volatile_fair": CHART_COLORS["neutral_purple"],
        "extreme_fear": CHART_COLORS["loss_red"],
        "unknown": CHART_COLORS["text_muted"],
    }

    fig = go.Figure(
        data=[
            go.Pie(
                labels=list(distribution.keys()),
                values=list(distribution.values()),
                marker_colors=[colors.get(r, CHART_COLORS["text_muted"]) for r in distribution.keys()],
                hole=0.5,
                textinfo="percent",
                textfont=dict(
                    family="JetBrains Mono, monospace",
                    size=12,
                    color=CHART_COLORS["text_primary"],
                ),
                hovertemplate="<b>%{label}</b><br>%{value} snapshots<br>%{percent}<extra></extra>",
            )
        ]
    )

    # Create layout without base legend to avoid duplicate keyword
    base_layout = {k: v for k, v in CHART_LAYOUT.items() if k != "legend"}
    fig.update_layout(
        **base_layout,
        title=dict(
            text=title,
            font=dict(
                family="Outfit, sans-serif",
                size=18,
                color=CHART_COLORS["text_primary"],
            ),
        ),
        height=400,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(0,0,0,0)",
            font=dict(
                family="JetBrains Mono, monospace",
                size=11,
                color=CHART_COLORS["text_secondary"],
            ),
        ),
    )

    return fig


def create_price_dvol_dual_axis(data: list[HistoricalDataPoint], currency: str = "BTC") -> go.Figure:
    """Create combined price and DVOL chart with dual y-axes.

    Args:
        data: List of HistoricalDataPoint objects.
        currency: Trading currency for chart title (e.g., "BTC", "ETH").

    Returns:
        Plotly Figure with price on left axis and DVOL on right axis.
    """
    # Validate data
    clean_data, warnings = _validate_chart_data(
        data, lambda d: d.btc_price if d.dvol is not None else None, min_points=2
    )
    if not clean_data:
        return _create_empty_figure(warnings[0] if warnings else "No data available")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    dates = [d.timestamp for d in clean_data]

    # Price on primary y-axis
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=[d.btc_price for d in clean_data],
            name=f"{currency} Price",
            line=dict(color=CHART_COLORS["btc_orange"], width=2),
            hovertemplate="<b>$%{y:,.0f}</b><extra></extra>",
        ),
        secondary_y=False,
    )

    # DVOL on secondary y-axis
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=[d.dvol for d in clean_data],
            name="DVOL",
            line=dict(color=CHART_COLORS["accent_cyan"], width=2),
            hovertemplate="<b>%{y:.1f}</b><extra></extra>",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"{currency} Price vs DVOL",
            font=dict(
                family="Outfit, sans-serif",
                size=18,
                color=CHART_COLORS["text_primary"],
            ),
        ),
        height=450,
        hovermode="x unified",
    )

    fig.update_xaxes(**AXIS_STYLE)
    # Create axis style with custom title_font color for each axis
    btc_axis_style = {**AXIS_STYLE, "title_font": dict(color=CHART_COLORS["btc_orange"])}
    dvol_axis_style = {**AXIS_STYLE, "title_font": dict(color=CHART_COLORS["accent_cyan"])}
    fig.update_yaxes(
        **btc_axis_style,
        title_text=f"{currency} Price (USD)",
        secondary_y=False,
    )
    fig.update_yaxes(
        **dvol_axis_style,
        title_text="DVOL",
        secondary_y=True,
    )

    return fig


def create_candlestick_chart(data: list[HistoricalDataPoint], currency: str = "BTC") -> go.Figure:
    """Create OHLC candlestick chart for price.

    Args:
        data: List of HistoricalDataPoint objects.
        currency: Trading currency for chart title (e.g., "BTC", "ETH").

    Returns:
        Plotly Figure with candlestick chart.
    """
    # Validate data
    clean_data, warnings = _validate_chart_data(
        data, lambda d: d.btc_price, min_points=2
    )
    if not clean_data:
        return _create_empty_figure(warnings[0] if warnings else "No data available")

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=[d.timestamp for d in clean_data],
                open=[d.btc_open for d in clean_data],
                high=[d.btc_high for d in clean_data],
                low=[d.btc_low for d in clean_data],
                close=[d.btc_price for d in clean_data],
                name=currency,
                increasing=dict(
                    line=dict(color=CHART_COLORS["profit_green"], width=1),
                    fillcolor=CHART_COLORS["profit_green"],
                ),
                decreasing=dict(
                    line=dict(color=CHART_COLORS["loss_red"], width=1),
                    fillcolor=CHART_COLORS["loss_red"],
                ),
            )
        ]
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=f"{currency} Price (Candlestick)",
            font=dict(
                family="Outfit, sans-serif",
                size=18,
                color=CHART_COLORS["text_primary"],
            ),
        ),
        height=500,
        xaxis_rangeslider_visible=False,
    )

    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text="Price (USD)")

    return fig
