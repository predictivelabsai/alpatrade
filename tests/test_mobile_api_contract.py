"""DB-free regression tests for the mobile REST contract."""

import hashlib
import hmac
import time
from enum import Enum

import pytest
from fastapi.testclient import TestClient

from api_app import _position_item_from_alpaca, app


class _Side(Enum):
    SHORT = "short"


def test_openapi_includes_direct_paper_order_endpoint():
    assert "/v2/order" in app.openapi()["paths"]


def test_openapi_exposes_docs_auth_and_external_agents():
    spec = app.openapi()

    assert spec["info"]["version"] == "0.8.0"
    assert set(spec["components"]["securitySchemes"]) == {
        "BearerAuth", "ServiceApiKey",
    }
    for path in (
        "/v2/agents",
        "/v2/agents/chat/invoke",
        "/v2/agents/premarket/invoke",
        "/v2/agents/alpha-growth/invoke",
        "/v2/agents/alpha-value/invoke",
        "/v2/agents/alpha-compare/invoke",
        "/v2/agents/autonomy-scout/invoke",
    ):
        assert path in spec["paths"]


def test_api_discovery_and_documentation_routes_are_public():
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["links"] == {
        "swagger": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "health": "/health",
        "agents": "/v2/agents",
    }
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_agent_catalog_covers_core_and_specialized_agents():
    response = TestClient(app).get("/v2/agents")
    slugs = {agent["slug"] for agent in response.json()["agents"]}

    assert response.status_code == 200
    assert {
        "deep-agent", "premarket", "alpha-growth", "alpha-value",
        "alpha-compare", "backtest", "validator", "paper-trader",
        "reconciler", "reporter", "orchestrator", "autonomy-scout",
    } <= slugs


def test_tenant_endpoints_reject_anonymous_and_spoofed_user_headers():
    client = TestClient(app)

    assert client.get("/v2/status").status_code == 401
    assert client.post(
        "/v2/order", json={"symbol": "AAPL", "qty": 1},
    ).status_code == 401
    spoofed = client.get("/v2/status", headers={"X-User-Id": "spoofed-user"})
    assert spoofed.status_code == 401


def test_service_api_key_authenticates_tenant_requests(monkeypatch):
    monkeypatch.setenv("API_SERVICE_KEY", "test-service-key")
    response = TestClient(app).get(
        "/v2/logs",
        headers={
            "X-API-Key": "test-service-key",
            "X-User-Id": "11111111-1111-4111-8111-111111111111",
        },
    )

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    missing_tenant = TestClient(app).get(
        "/v2/status", headers={"X-API-Key": "test-service-key"},
    )
    assert missing_tenant.status_code == 400


def test_internal_user_header_requires_fresh_signature(monkeypatch):
    secret = "test-jwt-secret"
    user_id = "22222222-2222-4222-8222-222222222222"
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(),
        f"{timestamp}:GET:/v2/logs:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    monkeypatch.setenv("JWT_SECRET", secret)

    response = TestClient(app).get(
        "/v2/logs",
        headers={
            "X-User-Id": user_id,
            "X-Internal-Timestamp": timestamp,
            "X-Internal-Signature": signature,
        },
    )
    assert response.status_code == 200


def test_alpaca_position_maps_ratio_pnl_to_percent():
    item = _position_item_from_alpaca({
        "symbol": "AAPL",
        "side": _Side.SHORT,
        "qty": "-3",
        "avg_entry_price": "301.32",
        "current_price": "313.33",
        "market_value": "-939.99",
        "unrealized_pl": "-36.03",
        "unrealized_plpc": "-0.03986",
        "cost_basis": "-903.96",
    })

    assert item.symbol == "AAPL"
    assert item.side == "short"
    assert item.shares == 3
    assert item.unrealized_pnl == pytest.approx(-36.03)
    assert item.unrealized_pnl_pct == pytest.approx(-3.986)
    assert item.status == "open"
