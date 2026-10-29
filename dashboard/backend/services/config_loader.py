"""Configuration loading helpers for dashboard backend services."""

import os
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_dashboard_config_path() -> Path | None:
    """Return the selected bot config path for dashboard services."""
    explicit = os.environ.get("OPTIONS_BOT_CONFIG") or os.environ.get("VEGA_CONFIG_PATH")
    if explicit:
        return Path(explicit)

    project_root = _project_root()
    for relative in (
        "config/settings.yaml",
        "config/settings.mainnet.yaml",
        "config/settings.testnet.yaml",
    ):
        candidate = project_root / relative
        if candidate.exists():
            return candidate
    return None


def load_dashboard_config() -> dict[str, Any]:
    """Load the selected bot YAML config with environment substitution."""
    config_path = get_dashboard_config_path()
    if config_path is None or not config_path.exists():
        return {}

    content = config_path.read_text()
    for key, value in os.environ.items():
        content = content.replace(f"${{{key}}}", value)
    loaded = yaml.safe_load(content)
    return loaded if isinstance(loaded, dict) else {}


def get_configured_database_path() -> str:
    """Return dashboard database path from env or selected bot config."""
    explicit = os.environ.get("VEGA_DB_PATH")
    if explicit:
        return explicit

    config = load_dashboard_config()
    db_path = config.get("database", {}).get("path")
    if db_path:
        path = Path(str(db_path))
        return str(path if path.is_absolute() else _project_root() / path)

    return str(_project_root() / "data" / "paper_trading.db")
