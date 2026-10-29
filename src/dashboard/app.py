"""Streamlit dashboard for options trading bot.

Run with: streamlit run src/dashboard/app.py

Terminal Noir theme - A sophisticated dark trading terminal with
electric cyan accents and professional typography.
"""
# ruff: noqa: E402
# mypy: ignore-errors

import sys
from pathlib import Path

# Add project root to path for imports when running via streamlit
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import time
import streamlit as st
from datetime import datetime, timedelta, timezone

from src.persistence.database import Database
from src.config import load_settings
from src.dashboard.data_provider import DashboardDataProvider
from src.dashboard.live_data_provider import LiveDataProvider
from src.dashboard.charts import (
    create_price_chart,
    create_dvol_chart,
    create_regime_pie_chart,
    create_price_dvol_dual_axis,
    create_candlestick_chart,
)


# =============================================================================
# TERMINAL NOIR THEME
# =============================================================================

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap');

/* Root variables */
:root {
    --bg-primary: #0D0D0F;
    --bg-secondary: #151518;
    --bg-tertiary: #1A1A1F;
    --bg-card: #1E1E24;
    --border-color: #2A2A32;
    --border-glow: #00D9FF;
    --text-primary: #FFFFFF;
    --text-secondary: #A0A0B0;
    --text-muted: #6B6B7B;
    --accent-cyan: #00D9FF;
    --accent-cyan-dim: rgba(0, 217, 255, 0.15);
    --profit-green: #00FF88;
    --profit-green-dim: rgba(0, 255, 136, 0.15);
    --loss-red: #FF3366;
    --loss-red-dim: rgba(255, 51, 102, 0.15);
    --warning-amber: #FFB800;
    --neutral-purple: #8B5CF6;
}

/* Global overrides */
.stApp {
    background: var(--bg-primary);
    font-family: 'Outfit', sans-serif;
}

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Main container */
.main .block-container {
    padding: 2rem 3rem;
    max-width: 100%;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-primary) 100%);
    border-right: 1px solid var(--border-color);
}

[data-testid="stSidebar"] .stMarkdown {
    color: var(--text-secondary);
}

/* Custom metric cards */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
    position: relative;
    overflow: hidden;
    transition: all 0.3s ease;
}

.metric-card:hover {
    border-color: var(--accent-cyan);
    box-shadow: 0 0 20px var(--accent-cyan-dim);
}

.metric-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-cyan), transparent);
    opacity: 0;
    transition: opacity 0.3s ease;
}

.metric-card:hover::before {
    opacity: 1;
}

.metric-label {
    font-family: 'Outfit', sans-serif;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    margin-bottom: 0.5rem;
}

.metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.75rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.2;
}

.metric-value.positive {
    color: var(--profit-green);
    text-shadow: 0 0 20px var(--profit-green-dim);
}

.metric-value.negative {
    color: var(--loss-red);
    text-shadow: 0 0 20px var(--loss-red-dim);
}

.metric-value.accent {
    color: var(--accent-cyan);
    text-shadow: 0 0 20px var(--accent-cyan-dim);
}

/* Section headers */
.section-header {
    font-family: 'Outfit', sans-serif;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
    margin: 2rem 0 1rem 0;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.section-header::before {
    content: '';
    width: 4px;
    height: 1.25rem;
    background: var(--accent-cyan);
    border-radius: 2px;
}

/* Page title */
.page-title {
    font-family: 'Outfit', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
    letter-spacing: -0.02em;
}

.page-subtitle {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-bottom: 2rem;
}

/* Data tables */
.data-table {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
}

/* Regime badges */
.regime-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.375rem 0.75rem;
    border-radius: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.regime-neutral {
    background: var(--profit-green-dim);
    color: var(--profit-green);
    border: 1px solid var(--profit-green);
}

.regime-high_stress, .regime-extreme_fear {
    background: var(--loss-red-dim);
    color: var(--loss-red);
    border: 1px solid var(--loss-red);
}

.regime-high_iv_overpriced {
    background: rgba(255, 184, 0, 0.15);
    color: var(--warning-amber);
    border: 1px solid var(--warning-amber);
}

.regime-low_iv_underpriced, .regime-volatile_fair {
    background: rgba(139, 92, 246, 0.15);
    color: var(--neutral-purple);
    border: 1px solid var(--neutral-purple);
}

/* Greek indicators */
.greek-card {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
    text-align: center;
}

.greek-symbol {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.875rem;
    color: var(--accent-cyan);
    margin-bottom: 0.25rem;
}

.greek-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
}

/* Status indicators */
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 0.5rem;
    animation: pulse 2s infinite;
}

.status-dot.live {
    background: var(--profit-green);
    box-shadow: 0 0 10px var(--profit-green);
}

.status-dot.warning {
    background: var(--warning-amber);
    box-shadow: 0 0 10px var(--warning-amber);
}

.status-dot.error {
    background: var(--loss-red);
    box-shadow: 0 0 10px var(--loss-red);
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

/* Streamlit overrides for dark theme */
.stMetric {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}

.stMetric:hover {
    border-color: var(--accent-cyan) !important;
}

[data-testid="stMetricLabel"] {
    font-family: 'Outfit', sans-serif !important;
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: var(--text-muted) !important;
}

[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 1.5rem !important;
    font-weight: 600 !important;
    color: var(--text-primary) !important;
}

/* Dataframe styling */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* Button styling */
.stButton > button {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important;
    font-family: 'Outfit', sans-serif !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.5rem 1rem !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 15px var(--accent-cyan-dim) !important;
}

/* Select box styling */
.stSelectbox > div > div {
    background: var(--bg-card) !important;
    border-color: var(--border-color) !important;
    color: var(--text-primary) !important;
}

/* Radio buttons */
.stRadio > div {
    background: transparent !important;
}

.stRadio label {
    color: var(--text-secondary) !important;
    font-family: 'Outfit', sans-serif !important;
}

/* Divider */
hr {
    border-color: var(--border-color) !important;
    margin: 2rem 0 !important;
}

/* Info/Warning boxes */
.stAlert {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    color: var(--text-secondary) !important;
}

/* Expander */
.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    font-family: 'Outfit', sans-serif !important;
}

/* Caption */
.stCaption {
    color: var(--text-muted) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
}

/* Custom scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--bg-primary);
}

::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* Grid background pattern */
.grid-bg {
    background-image:
        linear-gradient(var(--border-color) 1px, transparent 1px),
        linear-gradient(90deg, var(--border-color) 1px, transparent 1px);
    background-size: 50px 50px;
    background-position: -1px -1px;
    opacity: 0.3;
}

/* Sidebar navigation styling */
[data-testid="stSidebar"] [data-testid="stMarkdown"] h1 {
    color: var(--accent-cyan) !important;
    font-family: 'Outfit', sans-serif !important;
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
}

/* Logo styling */
.logo-container {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-color);
}

.logo-icon {
    font-size: 2rem;
}

.logo-text {
    font-family: 'Outfit', sans-serif;
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
}

.logo-text span {
    color: var(--accent-cyan);
}
</style>
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def render_metric_card(label: str, value: str, value_class: str = "") -> str:
    """Render a custom styled metric card."""
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value {value_class}">{value}</div>
    </div>
    """


def render_section_header(title: str) -> str:
    """Render a styled section header."""
    return f'<div class="section-header">{title}</div>'


def render_regime_badge(regime: str) -> str:
    """Render a regime badge with appropriate styling."""
    regime_lower = regime.lower().replace(" ", "_")
    display_name = regime.replace("_", " ").title()
    return f'<span class="regime-badge regime-{regime_lower}">{display_name}</span>'


def render_greek_card(symbol: str, name: str, value: str) -> str:
    """Render a Greek letter card."""
    return f"""
    <div class="greek-card">
        <div class="greek-symbol">{symbol} {name}</div>
        <div class="greek-value">{value}</div>
    </div>
    """


def format_pnl(value: float | None) -> tuple[str, str]:
    """Format P&L with appropriate styling class."""
    if value is None:
        return "N/A", ""
    if value > 0:
        return f"+${value:,.2f}", "positive"
    elif value < 0:
        return f"-${abs(value):,.2f}", "negative"
    return "$0.00", ""


# =============================================================================
# PAGE CONFIG & INITIALIZATION
# =============================================================================

st.set_page_config(
    page_title="VEGA Terminal",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom CSS
st.markdown(THEME_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_data_provider() -> DashboardDataProvider:
    """Get cached data provider instance."""
    db = Database("data/paper_trading.db")
    db.initialize()
    return DashboardDataProvider(db)


@st.cache_resource
def get_live_data_provider() -> LiveDataProvider:
    """Get cached live data provider instance."""
    return LiveDataProvider()


@st.cache_resource
def get_dvol_thresholds() -> dict[str, float]:
    """Get DVOL thresholds from config."""
    settings = load_settings()
    return {
        "reduce": settings.risk.dvol_reduce_threshold,
        "halt": settings.risk.dvol_halt_threshold,
    }


@st.cache_resource
def get_trading_currency() -> str:
    """Get trading currency from config."""
    settings = load_settings()
    return settings.trading.currency.upper()


@st.cache_resource
def get_is_linear() -> bool:
    """Check if using USDC-settled linear options."""
    settings = load_settings()
    return settings.trading.settlement == "linear"


# Initialize
provider = get_data_provider()
dvol_thresholds = get_dvol_thresholds()
trading_currency = get_trading_currency()
is_linear = get_is_linear()

# Display unit labels: USDC for linear, crypto currency for inverse
account_unit = "USDC" if is_linear else trading_currency


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    # Logo
    st.markdown("""
    <div class="logo-container">
        <div class="logo-text"><span>VEGA</span> Terminal</div>
    </div>
    """, unsafe_allow_html=True)

    # Navigation
    page = st.radio(
        "Navigation",
        ["Overview", "Live Monitor", "Trade History", "Historical Charts", "Regime Analysis"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Refresh button (for non-live pages)
    if page != "Live Monitor":
        if st.button("Refresh Data", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

    # Data status
    st.markdown("---")
    st.markdown("**Data Status**")

    data_count = provider.get_historical_data_count()
    st.caption(f"Historical: {data_count:,} records")

    start_date, end_date = provider.get_historical_date_range()
    if start_date and end_date:
        st.caption(f"Range: {start_date.date()} to {end_date.date()}")

    # Timestamp
    st.markdown("---")
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# =============================================================================
# OVERVIEW PAGE
# =============================================================================

if page == "Overview":
    # Title
    st.markdown('<div class="page-title">Dashboard Overview</div>', unsafe_allow_html=True)

    market = provider.get_latest_market_state()

    if market:
        st.markdown(f'<div class="page-subtitle">Last updated: {market["timestamp"].strftime("%Y-%m-%d %H:%M:%S UTC")}</div>', unsafe_allow_html=True)

        # Market metrics grid
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(render_metric_card(
                f"{trading_currency} Price",
                f"${market['btc_price']:,.0f}",
                "accent"
            ), unsafe_allow_html=True)

        with col2:
            dvol_val = f"{market['dvol']:.1f}" if market['dvol'] else "N/A"
            st.markdown(render_metric_card(
                "DVOL Index",
                dvol_val,
                ""
            ), unsafe_allow_html=True)

        with col3:
            iv_val = f"{market['iv_rank']:.0%}" if market['iv_rank'] is not None else "N/A"
            st.markdown(render_metric_card(
                "IV Rank",
                iv_val,
                ""
            ), unsafe_allow_html=True)

        with col4:
            regime = market['regime'] or "Unknown"
            regime_html = f"""
            <div class="metric-card">
                <div class="metric-label">Market Regime</div>
                {render_regime_badge(regime)}
            </div>
            """
            st.markdown(regime_html, unsafe_allow_html=True)
    else:
        st.info("No market data available. Run the bot to collect snapshots.")

    st.markdown("---")

    # Open positions section
    st.markdown(render_section_header("Open Positions"), unsafe_allow_html=True)
    positions = provider.get_open_positions()

    if positions:
        st.dataframe(
            positions,
            column_config={
                "strategy_id": st.column_config.TextColumn("ID", width="small"),
                "strategy_type": st.column_config.TextColumn("Strategy"),
                "entry_price": st.column_config.NumberColumn("Entry", format="$%.0f"),
                "current_pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
                "delta": st.column_config.NumberColumn("Delta", format="%.4f"),
                "gamma": st.column_config.NumberColumn("Gamma", format="%.6f"),
                "theta": st.column_config.NumberColumn("Theta", format="%.2f"),
                "vega": st.column_config.NumberColumn("Vega", format="%.2f"),
                "opened_at": st.column_config.DatetimeColumn("Opened"),
            },
            hide_index=True,
            use_container_width=True,
        )

        # Portfolio Greeks
        st.markdown(render_section_header("Portfolio Greeks"), unsafe_allow_html=True)

        total_delta = sum(p.get("delta") or 0 for p in positions)
        total_gamma = sum(p.get("gamma") or 0 for p in positions)
        total_theta = sum(p.get("theta") or 0 for p in positions)
        total_vega = sum(p.get("vega") or 0 for p in positions)

        g1, g2, g3, g4 = st.columns(4)

        with g1:
            st.markdown(render_greek_card("", "Delta", f"{total_delta:.4f}"), unsafe_allow_html=True)
        with g2:
            st.markdown(render_greek_card("", "Gamma", f"{total_gamma:.6f}"), unsafe_allow_html=True)
        with g3:
            st.markdown(render_greek_card("", "Theta", f"{total_theta:.2f}"), unsafe_allow_html=True)
        with g4:
            st.markdown(render_greek_card("", "Vega", f"{total_vega:.2f}"), unsafe_allow_html=True)
    else:
        st.info("No open positions")


# =============================================================================
# LIVE MONITOR PAGE
# =============================================================================

elif page == "Live Monitor":
    st.markdown('<div class="page-title">Live Monitor</div>', unsafe_allow_html=True)

    # Live settings in sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown("**Live Settings**")

        refresh_options = {
            "Manual": 0,
            "5 seconds": 5,
            "10 seconds": 10,
            "30 seconds": 30,
        }
        refresh_label = st.selectbox(
            "Refresh Interval",
            list(refresh_options.keys()),
            index=2,
        )
        refresh_interval = refresh_options[refresh_label]

        st.markdown("---")
        st.markdown("**API Status**")

    # Get live data provider
    live_provider = get_live_data_provider()

    # API status in sidebar
    with st.sidebar:
        if live_provider.has_credentials:
            with st.spinner("Connecting..."):
                auth_success = live_provider.authenticate()
            if auth_success:
                st.markdown('<span class="status-dot live"></span> Connected', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-dot warning"></span> Public only', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-dot error"></span> No credentials', unsafe_allow_html=True)

        if st.button("Refresh Now", use_container_width=True):
            st.rerun()

    # Fetch live data
    with st.spinner("Fetching live data..."):
        market_data, positions, account_info = live_provider.get_all_live_data()

    if market_data:
        st.markdown(f'<div class="page-subtitle"><span class="status-dot live"></span> Live data as of {market_data.timestamp.strftime("%H:%M:%S UTC")}</div>', unsafe_allow_html=True)

    # Market metrics
    col1, col2, col3, col4 = st.columns(4)

    if market_data:
        currency = live_provider.currency
        with col1:
            st.markdown(render_metric_card(
                f"{currency} Price",
                f"${market_data.btc_price:,.0f}",
                "accent"
            ), unsafe_allow_html=True)

        with col2:
            dvol_val = f"{market_data.dvol:.1f}" if market_data.dvol else "N/A"
            st.markdown(render_metric_card("DVOL", dvol_val, ""), unsafe_allow_html=True)

        with col3:
            iv_val = f"{market_data.iv_rank:.0%}" if market_data.iv_rank is not None else "N/A"
            st.markdown(render_metric_card("IV Rank", iv_val, ""), unsafe_allow_html=True)

        with col4:
            regime = market_data.regime.replace("_", " ").title()
            regime_html = f"""
            <div class="metric-card">
                <div class="metric-label">Regime</div>
                {render_regime_badge(regime)}
            </div>
            """
            st.markdown(regime_html, unsafe_allow_html=True)
    else:
        st.warning("Failed to fetch market data. Check API connection.")

    st.markdown("---")

    # Account summary
    if account_info:
        st.markdown(render_section_header("Account Summary"), unsafe_allow_html=True)

        acc1, acc2, acc3, acc4 = st.columns(4)

        with acc1:
            if is_linear:
                equity_str = f"${account_info.equity:,.2f}"
            else:
                equity_str = f"{account_info.equity:.4f} {currency}"
            st.markdown(render_metric_card(
                f"Equity ({account_unit})",
                equity_str,
                "accent"
            ), unsafe_allow_html=True)

        with acc2:
            if is_linear:
                balance_str = f"${account_info.balance:,.2f}"
            else:
                balance_str = f"{account_info.balance:.4f} {currency}"
            st.markdown(render_metric_card(
                f"Balance ({account_unit})",
                balance_str,
                ""
            ), unsafe_allow_html=True)

        with acc3:
            if is_linear:
                margin_str = f"${account_info.initial_margin:,.2f}"
            else:
                margin_str = f"{account_info.initial_margin:.4f} {currency}"
            st.markdown(render_metric_card(
                "Initial Margin",
                margin_str,
                ""
            ), unsafe_allow_html=True)

        with acc4:
            if is_linear:
                maint_str = f"${account_info.maintenance_margin:,.2f}"
            else:
                maint_str = f"{account_info.maintenance_margin:.4f} {currency}"
            st.markdown(render_metric_card(
                "Maint. Margin",
                maint_str,
                ""
            ), unsafe_allow_html=True)

        st.markdown("---")

    # Live positions
    st.markdown(render_section_header("Live Positions"), unsafe_allow_html=True)

    if positions is None:
        if not live_provider.is_authenticated:
            st.info("Authenticate with API credentials to view positions.")
        else:
            st.warning("Failed to fetch positions.")
    elif len(positions) == 0:
        st.info("No open positions")
    else:
        positions_data = [
            {
                "Instrument": p.instrument,
                "Size": p.size,
                "Direction": p.direction,
                "Avg Price": p.average_price,
                "Mark Price": p.mark_price,
                "P&L": p.pnl,
                "Delta": p.delta,
                "Gamma": p.gamma,
                "Theta": p.theta,
                "Vega": p.vega,
            }
            for p in positions
        ]

        # USDC linear: prices are in dollars; inverse: prices in crypto fractions
        price_fmt = "$%.2f" if is_linear else "%.4f"
        st.dataframe(
            positions_data,
            column_config={
                "Instrument": st.column_config.TextColumn("Instrument"),
                "Size": st.column_config.NumberColumn("Size", format="%.4f"),
                "Direction": st.column_config.TextColumn("Dir"),
                "Avg Price": st.column_config.NumberColumn("Avg", format=price_fmt),
                "Mark Price": st.column_config.NumberColumn("Mark", format=price_fmt),
                "P&L": st.column_config.NumberColumn("P&L", format="$%.2f"),
                "Delta": st.column_config.NumberColumn("", format="%.4f"),
                "Gamma": st.column_config.NumberColumn("", format="%.6f"),
                "Theta": st.column_config.NumberColumn("", format="%.4f"),
                "Vega": st.column_config.NumberColumn("", format="%.4f"),
            },
            hide_index=True,
            use_container_width=True,
        )

        # Portfolio Greeks
        st.markdown(render_section_header("Portfolio Greeks"), unsafe_allow_html=True)

        total_delta = sum(p.delta for p in positions)
        total_gamma = sum(p.gamma for p in positions)
        total_theta = sum(p.theta for p in positions)
        total_vega = sum(p.vega for p in positions)

        g1, g2, g3, g4 = st.columns(4)

        with g1:
            st.markdown(render_greek_card("", "Delta", f"{total_delta:.4f}"), unsafe_allow_html=True)
        with g2:
            st.markdown(render_greek_card("", "Gamma", f"{total_gamma:.6f}"), unsafe_allow_html=True)
        with g3:
            st.markdown(render_greek_card("", "Theta", f"{total_theta:.4f}"), unsafe_allow_html=True)
        with g4:
            st.markdown(render_greek_card("", "Vega", f"{total_vega:.4f}"), unsafe_allow_html=True)

    # Auto-refresh
    if refresh_interval > 0:
        time.sleep(refresh_interval)
        st.rerun()


# =============================================================================
# TRADE HISTORY PAGE
# =============================================================================

elif page == "Trade History":
    st.markdown('<div class="page-title">Trade History</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Performance metrics and completed trades</div>', unsafe_allow_html=True)

    stats = provider.get_trade_stats()

    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.markdown(render_metric_card(
            "Total Trades",
            str(stats["total_trades"]),
            "accent"
        ), unsafe_allow_html=True)

    with col2:
        win_rate = f"{stats['win_rate']:.1%}" if stats["total_trades"] > 0 else "N/A"
        st.markdown(render_metric_card("Win Rate", win_rate, ""), unsafe_allow_html=True)

    with col3:
        pnl_str, pnl_class = format_pnl(stats["total_pnl"] if stats["total_trades"] > 0 else None)
        st.markdown(render_metric_card("Total P&L", pnl_str, pnl_class), unsafe_allow_html=True)

    with col4:
        avg_pnl = f"${stats['avg_pnl']:,.2f}" if stats["total_trades"] > 0 else "N/A"
        st.markdown(render_metric_card("Avg P&L", avg_pnl, ""), unsafe_allow_html=True)

    with col5:
        duration = f"{stats['avg_duration_days']:.1f}d" if stats["total_trades"] > 0 else "N/A"
        st.markdown(render_metric_card("Avg Duration", duration, ""), unsafe_allow_html=True)

    st.markdown("---")

    if stats["total_trades"] > 0:
        # Win/Loss breakdown
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(render_metric_card(
                "Winning",
                str(stats["winning_trades"]),
                "positive"
            ), unsafe_allow_html=True)

        with col2:
            st.markdown(render_metric_card(
                "Losing",
                str(stats["losing_trades"]),
                "negative"
            ), unsafe_allow_html=True)

        with col3:
            st.markdown(render_metric_card(
                "Best Trade",
                f"${stats['best_trade']:,.2f}",
                "positive"
            ), unsafe_allow_html=True)

        with col4:
            st.markdown(render_metric_card(
                "Worst Trade",
                f"${stats['worst_trade']:,.2f}",
                "negative"
            ), unsafe_allow_html=True)

        st.markdown("---")

    # Strategy breakdown
    if stats["by_strategy"]:
        st.markdown(render_section_header("Performance by Strategy"), unsafe_allow_html=True)

        strategy_data = []
        for strategy, data in stats["by_strategy"].items():
            win_rate = data["wins"] / data["count"] if data["count"] > 0 else 0
            strategy_data.append({
                "Strategy": strategy.replace("_", " ").title(),
                "Trades": int(data["count"]),
                "Wins": int(data["wins"]),
                "Win Rate": f"{win_rate:.1%}",
                "Total P&L": f"${data['pnl']:,.2f}",
                "Avg P&L": f"${data['pnl'] / data['count']:,.2f}" if data["count"] > 0 else "$0.00",
            })

        st.dataframe(strategy_data, hide_index=True, use_container_width=True)
        st.markdown("---")

    # Closed positions
    st.markdown(render_section_header("Closed Positions"), unsafe_allow_html=True)

    limit_options = {"Last 25": 25, "Last 50": 50, "Last 100": 100}
    limit_label = st.selectbox("Show", list(limit_options.keys()), index=0, label_visibility="collapsed")
    limit = limit_options[limit_label]

    closed_positions = provider.get_closed_positions(limit=limit)

    if closed_positions:
        st.dataframe(
            closed_positions,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "strategy_type": st.column_config.TextColumn("Strategy"),
                "status": st.column_config.TextColumn("Status"),
                "entry_price": st.column_config.NumberColumn("Entry", format="$%.0f"),
                "pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
                "close_reason": st.column_config.TextColumn("Reason"),
                "opened_at": st.column_config.DatetimeColumn("Opened", format="YYYY-MM-DD HH:mm"),
                "closed_at": st.column_config.DatetimeColumn("Closed", format="YYYY-MM-DD HH:mm"),
                "duration_days": st.column_config.NumberColumn("Days", format="%d"),
                "strategy_id": None,
            },
            hide_index=True,
            use_container_width=True,
        )

        with st.expander("Export Data"):
            import json
            export_data = []
            for pos in closed_positions:
                export_pos = pos.copy()
                if export_pos.get("opened_at"):
                    export_pos["opened_at"] = export_pos["opened_at"].isoformat()
                if export_pos.get("closed_at"):
                    export_pos["closed_at"] = export_pos["closed_at"].isoformat()
                export_data.append(export_pos)

            st.download_button(
                label="Download JSON",
                data=json.dumps(export_data, indent=2),
                file_name="closed_positions.json",
                mime="application/json",
            )
    else:
        st.info("No closed positions yet. Positions will appear here after trades are executed and closed.")

    # Individual trades
    st.markdown("---")
    st.markdown(render_section_header("Individual Trades"), unsafe_allow_html=True)

    trades = provider.get_trade_history(limit=limit)

    if trades:
        # USDC linear: prices/fees in dollars; inverse: crypto fractions
        trade_price_fmt = "$%.2f" if is_linear else "%.6f"
        trade_fee_fmt = "$%.4f" if is_linear else "%.6f"
        st.dataframe(
            trades,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "strategy_type": st.column_config.TextColumn("Strategy"),
                "instrument": st.column_config.TextColumn("Instrument"),
                "side": st.column_config.TextColumn("Side"),
                "quantity": st.column_config.NumberColumn("Qty", format="%.4f"),
                "price": st.column_config.NumberColumn("Price", format=trade_price_fmt),
                "fees": st.column_config.NumberColumn("Fees", format=trade_fee_fmt),
                "status": st.column_config.TextColumn("Status"),
                "pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
                "opened_at": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
                "closed_at": None,
                "strategy_id": None,
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No trades yet. Trades will appear here after orders are executed.")


# =============================================================================
# HISTORICAL CHARTS PAGE
# =============================================================================

elif page == "Historical Charts":
    st.markdown('<div class="page-title">Historical Charts</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{trading_currency} price and volatility analysis</div>', unsafe_allow_html=True)

    # Chart controls
    col1, col2 = st.columns([1, 1])

    with col1:
        chart_type = st.selectbox(
            "Chart Type",
            ["Price + Volume", "Candlestick", "Price vs DVOL", "DVOL Only"],
            label_visibility="collapsed",
        )

    with col2:
        days_options = {
            "30 days": 30,
            "90 days": 90,
            "180 days": 180,
            "1 year": 365,
            "All data": 0,
        }
        days_label = st.selectbox("Period", list(days_options.keys()), index=2, label_visibility="collapsed")
        days_back = days_options[days_label]

    # Calculate date range
    end_date_chart = datetime.now(timezone.utc)
    if days_back > 0:
        start_date_chart = end_date_chart - timedelta(days=days_back)
    else:
        bounds = provider.get_historical_date_range()
        start_date_chart = bounds[0] if bounds[0] else end_date_chart - timedelta(days=365)

    # Fetch and display data
    data = provider.get_historical_data(start_date_chart, end_date_chart)

    if data:
        st.caption(f"Showing {len(data)} data points from {data[0].timestamp.date()} to {data[-1].timestamp.date()}")

        if chart_type == "Price + Volume":
            st.plotly_chart(create_price_chart(data, currency=trading_currency), use_container_width=True)
        elif chart_type == "Candlestick":
            st.plotly_chart(create_candlestick_chart(data, currency=trading_currency), use_container_width=True)
        elif chart_type == "Price vs DVOL":
            st.plotly_chart(create_price_dvol_dual_axis(data, currency=trading_currency), use_container_width=True)
        elif chart_type == "DVOL Only":
            st.plotly_chart(
                create_dvol_chart(data, thresholds=dvol_thresholds),
                use_container_width=True
            )

        # Stats
        with st.expander("Statistics"):
            col1, col2, col3 = st.columns(3)

            btc_prices = [d.btc_price for d in data]
            dvol_values = [d.dvol for d in data]

            with col1:
                st.markdown(render_metric_card(f"{trading_currency} High", f"${max(btc_prices):,.0f}", ""), unsafe_allow_html=True)
                st.markdown(render_metric_card(f"{trading_currency} Low", f"${min(btc_prices):,.0f}", ""), unsafe_allow_html=True)

            with col2:
                st.markdown(render_metric_card("DVOL High", f"{max(dvol_values):.1f}", ""), unsafe_allow_html=True)
                st.markdown(render_metric_card("DVOL Low", f"{min(dvol_values):.1f}", ""), unsafe_allow_html=True)

            with col3:
                price_change = (btc_prices[-1] - btc_prices[0]) / btc_prices[0] * 100
                change_class = "positive" if price_change > 0 else "negative" if price_change < 0 else ""
                st.markdown(render_metric_card("Period Return", f"{price_change:+.1f}%", change_class), unsafe_allow_html=True)
    else:
        st.warning("No historical data available.\n\nRun: `python scripts/fetch_historical_data.py --start 2024-01-01`")


# =============================================================================
# REGIME ANALYSIS PAGE
# =============================================================================

elif page == "Regime Analysis":
    st.markdown('<div class="page-title">Regime Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Market regime distribution and classification</div>', unsafe_allow_html=True)

    # Time window selector
    regime_days = st.selectbox(
        "Analysis Period",
        [7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"Last {x} days",
    )

    start_date_regime = datetime.now(timezone.utc) - timedelta(days=regime_days)
    distribution = provider.get_regime_distribution(start=start_date_regime)

    if distribution:
        col1, col2 = st.columns([1, 2])

        with col1:
            chart_title = f"Regime Distribution (Last {regime_days} Days)"
            st.plotly_chart(
                create_regime_pie_chart(distribution, title=chart_title),
                use_container_width=True
            )

        with col2:
            st.markdown(render_section_header("Breakdown"), unsafe_allow_html=True)

            total_snapshots = sum(distribution.values())

            for regime, count in sorted(distribution.items(), key=lambda x: -x[1]):
                pct = count / total_snapshots * 100
                col_badge, col_count = st.columns([2, 1])
                with col_badge:
                    st.markdown(render_regime_badge(regime), unsafe_allow_html=True)
                with col_count:
                    st.caption(f"{count} ({pct:.1f}%)")

            st.markdown("---")
            st.markdown(f"**Total snapshots:** {total_snapshots}")

        # Regime definitions
        with st.expander("Regime Definitions"):
            st.markdown("""
            | Regime | Condition | Strategy | Sizing |
            |--------|-----------|----------|--------|
            | **Extreme Fear** | DVOL > 80 | Halt | 0.0x |
            | **High Stress** | DVOL 60-80 | Iron Condor | 0.5x |
            | **High IV Overpriced** | IV > RV, high rank | Iron Condor | 1.0x |
            | **Low IV Underpriced** | IV < RV, low rank | Gamma Scalp | 1.0x |
            | **Volatile Fair** | IV RV | Gamma Scalp | 1.0x |
            | **Neutral** | Normal | Wheel | 1.0x |
            """)
    else:
        st.info("No regime data available yet. Run the bot to collect market snapshots.")
