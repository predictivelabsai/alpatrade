"""Pydantic AI adapter — type-safe tools + native async streaming.

Builds a ``pydantic_ai.Agent`` against the configured provider (OpenAI-compatible
base URL for xAI/OpenAI). LangChain ``StructuredTool``s are registered best-effort
by their underlying function. Falls back to LangGraph (via the registry) when
``pydantic_ai`` isn't installed.
"""
from __future__ import annotations

import os
from typing import Any, Iterator, Optional

from engine.agents.runtime.base import RoleSpec, RunResult


class PydanticAIRuntime:
    name = "pydantic_ai"

    @staticmethod
    def available() -> bool:
        try:
            import pydantic_ai  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def _model(self, spec: RoleSpec):
        """Map engine.config provider/model → a pydantic_ai model (OpenAI-compatible)."""
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from engine.config import get_settings, _OPENAI_COMPAT, _resolve_xai_model
        s = get_settings()
        provider = (s.model_provider or "xai").lower()
        model = s.model_name
        base_url, key_env = _OPENAI_COMPAT.get(provider, _OPENAI_COMPAT["xai"])
        if provider == "xai":
            model = _resolve_xai_model(model)
        return OpenAIModel(model, provider=OpenAIProvider(
            base_url=base_url, api_key=os.getenv(key_env)))

    def build(self, spec: RoleSpec) -> Any:
        from pydantic_ai import Agent
        agent = Agent(self._model(spec), system_prompt=spec.instructions or "")
        for t in spec.tools:
            fn = getattr(t, "func", None) or (t if callable(t) else None)
            if fn is None:
                continue
            name = getattr(t, "name", getattr(fn, "__name__", "tool"))
            desc = getattr(t, "description", fn.__doc__ or "")
            try:
                agent.tool_plain(fn, name=name, description=desc)
            except Exception:  # noqa: BLE001 — signature/translation mismatch; skip the tool
                continue
        return agent

    def run(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> RunResult:
        res = agent.run_sync(prompt)
        text = getattr(res, "output", None) or getattr(res, "data", "") or str(res)
        return RunResult(text=str(text), raw=res, runtime=self.name)

    def stream(self, agent: Any, prompt: str, *, history: Optional[list] = None) -> Iterator[str]:
        # Minimal: pydantic-ai streaming is async; yield the final text once for the sync path.
        yield self.run(agent, prompt, history=history).text

    def supports_subagents(self) -> bool:
        return False
