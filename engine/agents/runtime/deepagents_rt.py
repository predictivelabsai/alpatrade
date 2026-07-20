"""DeepAgents adapter — LangChain's planning + isolated-context-subagents harness.

DeepAgents graphs are LangGraph-compatible, so run/stream are inherited from
:class:`LangGraphRuntime`; only construction differs. Falls back automatically (via
the registry) to LangGraph when the ``deepagents`` package isn't installed.
"""
from __future__ import annotations

from typing import Any

from engine.agents.runtime.base import RoleSpec, default_model
from engine.agents.runtime.langgraph_rt import LangGraphRuntime


class DeepAgentsRuntime(LangGraphRuntime):
    name = "deepagents"

    @staticmethod
    def available() -> bool:
        try:
            import deepagents  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def build(self, spec: RoleSpec) -> Any:
        # deepagents>=0.6: create_deep_agent(model, tools, *, system_prompt, subagents, …)
        from deepagents import create_deep_agent
        kwargs = {"model": default_model(spec), "tools": list(spec.tools)}
        if spec.instructions:
            kwargs["system_prompt"] = spec.instructions
        if spec.subagents:
            kwargs["subagents"] = [
                {"name": s.name, "description": s.instructions,
                 "system_prompt": s.instructions, "tools": list(s.tools)}
                for s in spec.subagents
            ]
        return create_deep_agent(**kwargs)

    def supports_subagents(self) -> bool:
        return True
