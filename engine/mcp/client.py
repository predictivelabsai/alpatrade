"""Small authenticated HTTP client used by AlpaTrade MCP tools."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx


class AlpaTradeAPIError(RuntimeError):
    """Safe API failure suitable for returning through an MCP tool."""


def _base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("ALPATRADE_API_URL must use HTTPS or loopback HTTP")
    return value


class AlpaTradeAPIClient:
    """Tenant API client; it never connects directly to PostgreSQL or Alpaca."""

    def __init__(self, base_url: str, access_token: str, *, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not access_token.strip():
            raise ValueError("ALPATRADE_ACCESS_TOKEN is required")
        self.base_url = _base_url(base_url)
        self.access_token = access_token.strip()
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_env(cls) -> "AlpaTradeAPIClient":
        return cls(
            os.getenv("ALPATRADE_API_URL", "https://api.alpatrade.chat"),
            os.getenv("ALPATRADE_ACCESS_TOKEN", ""),
            timeout=float(os.getenv("ALPATRADE_MCP_TIMEOUT_SECONDS", "60")),
        )

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None) -> Any:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must be an absolute local path")
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, headers=headers, timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, params=params, json=json)
        except httpx.RequestError as exc:
            raise AlpaTradeAPIError("AlpaTrade API is unavailable") from exc
        if response.is_error:
            message = f"AlpaTrade API returned HTTP {response.status_code}"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, str) and detail:
                    message += f": {detail[:300]}"
            except (ValueError, AttributeError):
                pass
            raise AlpaTradeAPIError(message)
        try:
            return response.json()
        except ValueError as exc:
            raise AlpaTradeAPIError("AlpaTrade API returned invalid JSON") from exc
