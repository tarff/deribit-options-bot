"""Tests for optional dashboard API authentication."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


def test_dashboard_api_requires_token_when_configured(monkeypatch) -> None:
    """Configured dashboard token should protect API endpoints."""
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret-token")
    from main import app

    client = TestClient(app)

    unauthenticated = client.get("/api/health")
    authenticated = client.get(
        "/api/health",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
