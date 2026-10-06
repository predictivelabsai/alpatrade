from __future__ import annotations

import httpx
import pytest
from fastmcp import Client

from engine.mcp.client import AlpaTradeAPIClient, AlpaTradeAPIError, _base_url
from engine.mcp.server import build_server, main


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"ok": True, "method": method, "path": path, **kwargs}


def test_api_url_requires_https_except_loopback():
    assert _base_url("http://127.0.0.1:5001/") == "http://127.0.0.1:5001"
    assert _base_url("https://api.alpatrade.chat/") == "https://api.alpatrade.chat"
    with pytest.raises(ValueError, match="HTTPS"):
        _base_url("http://api.alpatrade.chat")


def test_public_http_binding_is_refused(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["alpatrade-mcp", "--transport", "http", "--host", "0.0.0.0"],
    )
    with pytest.raises(SystemExit, match="OAuth"):
        main()


@pytest.mark.asyncio
async def test_api_client_forwards_bearer_without_exposing_it():
    observed = {}

    def handler(request: httpx.Request):
        observed["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"runs": [], "total": 0})

    client = AlpaTradeAPIClient(
        "https://api.alpatrade.chat", "private-test-token",
        transport=httpx.MockTransport(handler),
    )
    assert await client.request("GET", "/v2/runs") == {"runs": [], "total": 0}
    assert observed["auth"] == "Bearer private-test-token"


@pytest.mark.asyncio
async def test_api_error_is_sanitized():
    client = AlpaTradeAPIClient(
        "https://api.alpatrade.chat", "private-test-token",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, json={"detail": "Invalid token"})
        ),
    )
    with pytest.raises(AlpaTradeAPIError, match="HTTP 401: Invalid token") as exc:
        await client.request("GET", "/v2/runs")
    assert "private-test-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_server_exposes_bounded_tool_catalog_and_routes_reads():
    fake = FakeAPI()
    server = build_server(lambda: fake)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert names == {
            "get_platform_health", "list_agents", "list_runs", "list_trades",
            "get_run_report", "get_positions", "get_agent_status", "run_backtest",
            "start_paper_trading", "stop_agent", "ask_alpatrade",
            "place_paper_order",
        }
        result = await client.call_tool("list_trades", {
            "run_id": "run-1", "symbol": "aapl", "limit": 999,
        })
    assert result.data["ok"] is True
    assert fake.calls == [("GET", "/v2/trades", {
        "params": {"limit": 500, "run_id": "run-1", "symbol": "AAPL"}
    })]


@pytest.mark.asyncio
async def test_paper_order_requires_explicit_confirmation():
    fake = FakeAPI()
    async with Client(build_server(lambda: fake)) as client:
        with pytest.raises(Exception, match="confirmation to PAPER"):
            await client.call_tool("place_paper_order", {
                "symbol": "AAPL", "qty": 1, "side": "buy",
            })
    assert fake.calls == []


@pytest.mark.asyncio
async def test_actions_use_only_paper_endpoints_and_payloads():
    fake = FakeAPI()
    async with Client(build_server(lambda: fake)) as client:
        order = await client.call_tool("place_paper_order", {
            "symbol": "aapl", "qty": 2, "side": "buy", "confirmation": "PAPER",
        })
        paper = await client.call_tool("start_paper_trading", {
            "strategy": "buy_the_dip", "symbols": "AAPL,MSFT", "duration": "1d",
        })
    assert order.data["path"] == "/v2/order"
    assert paper.data["path"] == "/v2/paper"
    assert fake.calls[0][2]["json"]["symbol"] == "AAPL"
    assert fake.calls[1][2]["json"]["pdt"] is True
