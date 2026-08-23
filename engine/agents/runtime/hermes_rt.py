"""Remote Nous Hermes Agent runtime.

Hermes runs as an isolated gateway service and exposes an OpenAI-compatible API.
This adapter deliberately does not give Hermes database or broker credentials;
AlpaTrade-owned trading tools are added through scoped API endpoints in Phase 2.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, Optional

import httpx

from engine.agents.runtime.base import RoleSpec, RunResult


@dataclass(frozen=True)
class HermesAgent:
    """Role information sent to the remote Hermes gateway."""

    spec: RoleSpec


class HermesRuntime:
    name = "hermes"

    @staticmethod
    def available() -> bool:
        # The HTTP adapter has no optional dependency. Connectivity is checked per
        # request so a temporarily unavailable sidecar can fall back cleanly.
        return True

    @staticmethod
    def _base_url() -> str:
        return os.getenv("HERMES_API_URL", "http://hermes:8642/v1").rstrip("/")

    @staticmethod
    def _headers(*, session_id: str | None = None,
                 session_key: str | None = None) -> dict[str, str]:
        key = os.getenv("HERMES_API_SERVER_KEY")
        if not key:
            raise RuntimeError("HERMES_API_SERVER_KEY is not configured")
        headers = {"Authorization": f"Bearer {key}"}
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        if session_key:
            headers["X-Hermes-Session-Key"] = session_key
        return headers

    def build(self, spec: RoleSpec) -> HermesAgent:
        return HermesAgent(spec=spec)

    @staticmethod
    def _messages(agent: HermesAgent, prompt: str,
                  history: Optional[list]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if agent.spec.instructions:
            messages.append({"role": "system", "content": agent.spec.instructions})
        for message in history or []:
            role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "user")
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": str(content)})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _payload(self, agent: HermesAgent, prompt: str,
                 history: Optional[list], *, stream: bool) -> dict[str, Any]:
        return {
            "model": os.getenv("HERMES_API_MODEL", "hermes-agent"),
            "messages": self._messages(agent, prompt, history),
            "stream": stream,
        }

    def run(self, agent: HermesAgent, prompt: str, *,
            history: Optional[list] = None) -> RunResult:
        timeout = float(os.getenv("HERMES_API_TIMEOUT_SECONDS", "180"))
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{self._base_url()}/chat/completions",
                headers=self._headers(),
                json=self._payload(agent, prompt, history, stream=False),
            )
            response.raise_for_status()
            raw = response.json()
        text = raw["choices"][0]["message"].get("content", "")
        return RunResult(text=text, raw=raw, runtime=self.name)

    async def astream(self, agent: HermesAgent, prompt: str, *,
                      history: Optional[list] = None,
                      session_id: str | None = None,
                      session_key: str | None = None) -> AsyncIterator[str]:
        """Stream content deltas without blocking the AlpaTrade web event loop."""
        timeout = float(os.getenv("HERMES_API_TIMEOUT_SECONDS", "180"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url()}/chat/completions",
                headers=self._headers(session_id=session_id, session_key=session_key),
                json=self._payload(agent, prompt, history, stream=True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    text = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if text:
                        yield text

    def stream(self, agent: HermesAgent, prompt: str, *,
               history: Optional[list] = None) -> Iterator[str]:
        # Retain the synchronous runtime contract for CLI callers.
        yield self.run(agent, prompt, history=history).text

    def supports_subagents(self) -> bool:
        return True

    def notify(self, text: str) -> bool:
        """Preserve the existing optional autonomy notification integration."""
        url = os.getenv("HERMES_WEBHOOK_URL")
        if not url:
            return False
        headers = {}
        if os.getenv("HERMES_TOKEN"):
            headers["Authorization"] = f"Bearer {os.getenv('HERMES_TOKEN')}"
        try:
            response = httpx.post(url, json={"text": text}, headers=headers, timeout=15)
            return response.status_code < 400
        except Exception:  # noqa: BLE001
            return False
