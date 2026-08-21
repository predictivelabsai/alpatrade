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

    assert spec["info"]["version"] == "0.11.0"
    assert set(spec["components"]["securitySchemes"]) == {
        "BearerAuth", "ServiceApiKey",
    }
    for path in (
        "/v2/agents",
        "/v2/deepagents",
        "/v2/agents/chat/invoke",
        "/v2/agents/premarket/invoke",
        "/v2/agents/alpha-growth/invoke",
        "/v2/agents/alpha-value/invoke",
        "/v2/agents/alpha-compare/invoke",
        "/v2/agents/autonomy-scout/invoke",
        "/v2/advisor/reports",
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
    agents = response.json()["agents"]
    slugs = {agent["slug"] for agent in agents}

    assert response.status_code == 200
    assert {
        "deep-agent", "premarket", "alpha-growth", "alpha-value",
        "alpha-compare", "backtest", "validator", "paper-trader",
        "reconciler", "reporter", "orchestrator", "autonomy-scout",
    } <= slugs
    assert all(agent["category"] for agent in agents)
    assert all(len(agent["skills"]) >= 4 for agent in agents)


def test_browser_navigation_uses_formatted_docs_while_api_clients_get_json():
    client = TestClient(app, follow_redirects=False)

    catalog = client.get("/v2/agents", headers={"Accept": "text/html"})
    schema = client.get("/openapi.json", headers={"Accept": "text/html"})

    assert catalog.status_code == 307
    assert catalog.headers["location"] == "/redoc#tag/agent-invocation"
    assert catalog.headers["vary"] == "Accept"
    assert schema.status_code == 307
    assert schema.headers["location"] == "/redoc"
    assert schema.headers["vary"] == "Accept"
    json_catalog = client.get("/v2/agents", headers={"Accept": "application/json"})
    json_schema = client.get("/openapi.json", headers={"Accept": "application/json"})
    assert json_catalog.status_code == 200
    assert json_catalog.headers["vary"] == "Accept"
    assert json_schema.status_code == 200
    assert json_schema.headers["vary"] == "Accept"


def test_openapi_documents_agent_skills_and_redoc_groups():
    spec = app.openapi()
    operation = spec["paths"]["/v2/deepagents"]["post"]

    assert operation["x-agent-slug"] == "deep-agent"
    assert "Portfolio and position analysis" in operation["x-agent-skills"]
    assert "### Agent skills" in operation["description"]
    assert spec["x-tagGroups"][0]["name"] == "Agent APIs"
    assert spec["externalDocs"]["url"] == "https://alpatrade.chat/developers"
    assert spec["paths"]["/health"]["get"]["security"] == []
    assert operation["security"]


def test_openapi_documents_premarket_filters_and_additive_response_fields():
    spec = app.openapi()
    request = spec["components"]["schemas"]["PremarketAgentRequest"]["properties"]
    response = spec["components"]["schemas"]["PremarketAgentResponse"]["properties"]

    assert {"refresh", "limit", "date", "sector", "ticker", "chart"} <= set(request)
    assert request["chart"]["enum"] == ["auto", "breadth", "movers", "none"]
    assert {"report", "top", "effective_date", "as_of", "freshness", "commentary", "chart"} <= set(response)


def test_premarket_refresh_returns_scheduler_managed_conflict(monkeypatch):
    monkeypatch.setenv("API_SERVICE_KEY", "premarket-service-key")
    response = TestClient(app).post(
        "/v2/agents/premarket/invoke",
        json={"refresh": True},
        headers={
            "X-API-Key": "premarket-service-key",
            "X-User-Id": "11111111-1111-4111-8111-111111111111",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "scheduler_managed"


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
