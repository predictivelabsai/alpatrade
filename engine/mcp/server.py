"""AlpaTrade MCP server for Codex, Claude, Grok-compatible clients, and CLIs.

The adapter intentionally delegates authorization and tenant isolation to the
canonical AlpaTrade REST API. It contains no database or broker credentials.
"""
from __future__ import annotations

import argparse
import os
import uuid
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from engine.mcp.client import AlpaTradeAPIClient

ClientFactory = Callable[[], AlpaTradeAPIClient]


def build_server(client_factory: ClientFactory = AlpaTradeAPIClient.from_env) -> FastMCP:
    mcp = FastMCP(
        "AlpaTrade",
        instructions=(
            "Authenticated, tenant-scoped AlpaTrade research and paper-trading tools. "
            "Never describe paper results as live returns. Never place an order unless "
            "the user explicitly asks and the confirmation argument is PAPER."
        ),
    )

    async def call(method: str, path: str, **kwargs: Any) -> Any:
        return await client_factory().request(method, path, **kwargs)

    @mcp.tool
    async def get_platform_health() -> dict:
        """Check that the configured AlpaTrade API is reachable."""
        return await call("GET", "/health")

    @mcp.tool
    async def list_agents() -> dict:
        """List AlpaTrade agents, skills, execution modes, and safety levels."""
        return await call("GET", "/v2/agents")

    @mcp.tool
    async def list_runs(limit: int = 20) -> dict:
        """List the authenticated user's recent backtest and paper runs."""
        return await call("GET", "/v2/runs", params={"limit": max(1, min(limit, 200))})

    @mcp.tool
    async def list_trades(run_id: str | None = None, trade_type: str | None = None,
                          symbol: str | None = None, limit: int = 50) -> dict:
        """List tenant-owned trades, optionally filtered by run, type, or symbol."""
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if run_id:
            params["run_id"] = run_id
        if trade_type:
            params["type"] = trade_type
        if symbol:
            params["symbol"] = symbol.upper()
        return await call("GET", "/v2/trades", params=params)

    @mcp.tool
    async def get_run_report(run_id: str) -> dict:
        """Get the authenticated user's detailed performance report for one run."""
        return await call("GET", f"/v2/report/{run_id}")

    @mcp.tool
    async def get_positions() -> dict:
        """Get positions for the authenticated user's linked paper account."""
        return await call("GET", "/v2/positions")

    @mcp.tool
    async def get_agent_status() -> dict:
        """Get tenant-scoped running agent and paper-session status."""
        return await call("GET", "/v2/status")

    @mcp.tool
    async def run_backtest(strategy: str = "buy_the_dip", symbols: str = "AAPL",
                           lookback: str = "3m", capital: float = 10_000,
                           pdt: bool = True) -> dict:
        """Run a tenant-owned research backtest; this does not place orders."""
        return await call("POST", "/v2/backtest", json={
            "strategy": strategy, "symbols": symbols, "lookback": lookback,
            "capital": capital, "pdt": pdt,
        })

    @mcp.tool
    async def start_paper_trading(strategy: str = "buy_the_dip", symbols: str = "AAPL",
                                  duration: str = "7d", poll_seconds: int = 60,
                                  source_run_id: str | None = None) -> dict:
        """Start a background PAPER session. This endpoint cannot trade live money."""
        payload: dict[str, Any] = {
            "strategy": strategy, "symbols": symbols, "duration": duration,
            "poll": max(10, poll_seconds), "pdt": True,
        }
        if source_run_id:
            payload["source_run_id"] = source_run_id
        return await call("POST", "/v2/paper", json=payload)

    @mcp.tool
    async def stop_agent(run_id: str | None = None) -> dict:
        """Stop one tenant-owned background agent, or the most recent one."""
        params = {"run_id": run_id} if run_id else None
        return await call("POST", "/v2/stop", params=params)

    @mcp.tool
    async def ask_alpatrade(message: str, thread_id: str | None = None) -> dict:
        """Ask the canonical DeepAgents assistant and continue an optional thread."""
        payload: dict[str, Any] = {
            "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": message}],
            "stream": False,
        }
        if thread_id:
            payload["thread_id"] = thread_id
        return await call("POST", "/v2/deepagents", json=payload)

    @mcp.tool
    async def place_paper_order(symbol: str, qty: float, side: str = "buy",
                                order_type: str = "market", limit_price: float | None = None,
                                confirmation: str = "") -> dict:
        """Place an order in PAPER mode only; confirmation must equal PAPER."""
        if confirmation != "PAPER":
            raise ValueError("No order placed: set confirmation to PAPER after explicit approval")
        payload: dict[str, Any] = {
            "symbol": symbol.upper(), "qty": qty, "side": side,
            "order_type": order_type, "time_in_force": "day",
        }
        if limit_price is not None:
            payload["limit_price"] = limit_price
        return await call("POST", "/v2/order", json=payload)

    return mcp


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AlpaTrade MCP server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--path", default="/mcp")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.transport == "http" and args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "Remote HTTP is disabled: deploy standards-based MCP OAuth before binding publicly"
        )
    server = build_server()
    if args.transport == "stdio":
        server.run(transport="stdio", show_banner=False)
    else:
        server.run(transport="http", host=args.host, port=args.port, path=args.path,
                   show_banner=False)


if __name__ == "__main__":
    main()
