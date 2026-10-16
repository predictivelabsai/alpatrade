"""Public MCP protocol, privacy and developer-page contract."""
from __future__ import annotations

import json
import pytest
from fastcore.xml import to_xml
from starlette.testclient import TestClient

from engine.mcp_server import mcp


@pytest.mark.asyncio
async def test_mcp_memory_harness_lists_and_calls_tools(monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session
    from engine import mcp_server

    strategy = {"id": 7, "name": "Public strategy", "author": "Example", "is_public": True,
                "description": "Published rules", "kind": "live", "skill_md": "# Public skill"}
    metrics = {"annualised_pct": 12.0, "return_pct": 1.0, "trading_days": 21,
               "as_of": "2026-10-13", "is_backtest": False}
    monkeypatch.setattr(mcp_server, "_public_rows", lambda: [(strategy, metrics)])
    monkeypatch.setattr(mcp_server, "_public_strategy", lambda sid: (strategy, metrics))

    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"list_public_strategies", "get_public_strategy", "get_public_strategy_skill",
                "list_agent_interfaces"} <= names
        result = await client.call_tool("list_public_strategies", {"query": "Public"})
        assert not result.isError
        assert json.loads(result.content[0].text)["strategies"][0]["id"] == 7
        skill = await client.call_tool("get_public_strategy_skill", {"strategy_id": 7})
        assert not skill.isError and json.loads(skill.content[0].text)["skill_md"] == "# Public skill"
        agents = await client.call_tool("list_agent_interfaces", {})
        assert not agents.isError and json.loads(agents.content[0].text)["agents"]


def test_mcp_never_exposes_private_or_negative_strategies(monkeypatch):
    from engine.mcp_server import _public_strategy
    from engine.leaderboard import store, perf

    monkeypatch.setattr(store, "get", lambda sid: {"id": sid, "is_public": False})
    monkeypatch.setattr(perf, "strategy_metrics", lambda s: pytest.fail("private metrics queried"))
    with pytest.raises(ValueError, match="not found"):
        _public_strategy(1)

    monkeypatch.setattr(store, "get", lambda sid: {"id": sid, "is_public": True})
    monkeypatch.setattr(perf, "strategy_metrics", lambda s: {"annualised_pct": -1.0})
    with pytest.raises(ValueError, match="not found"):
        _public_strategy(2)


def test_http_mcp_exact_path_and_existing_routes(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "ci-import-placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "ci-import-placeholder")
    from app import app

    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "local-harness", "version": "1"}}}
    with TestClient(app) as client:
        response = client.post("/mcp", json=init, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "alpatrade"
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                             headers=headers)
        assert listed.status_code == 200
        assert "list_public_strategies" in {t["name"] for t in listed.json()["result"]["tools"]}
        assert client.get("/").status_code == 200
        assert client.get("/developers").status_code == 200


def test_developers_puts_mcp_before_existing_api_docs():
    from engine.web.ph_landing import developers_page

    html = to_xml(developers_page())
    assert html.index('id="mcp"') < html.index('id="api-docs"')
    assert "https://alpatrade.chat/mcp" in html
    assert "claude mcp add --transport http alpatrade" in html
    assert "get_public_strategy_skill" in html
    assert "https://api.alpatrade.chat/redoc" in html
    assert "Swagger UI" in html and 'id="cli"' in html
