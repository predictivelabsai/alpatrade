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
        model = default_model(spec)
        kwargs = {
            "model": model,
            "tools": list(spec.tools),
            "name": spec.name,
        }
        if spec.name == "alpatrade-chat":
            from engine.ai.deepagents import BLOCKED_TOOLS, BlockedToolMiddleware
            from deepagents.profiles import (
                GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile,
            )

            kwargs["middleware"] = [BlockedToolMiddleware()]
            # Match the API policy, including disabling the unguarded default
            # subagent so it cannot bypass the coordinator's tool restrictions.
            model_name = getattr(model, "model_name", None) or getattr(model, "model", None)
            if model_name:
                provider = "anthropic" if model._llm_type == "anthropic-chat" else "openai"
                register_harness_profile(
                    f"{provider}:{model_name}",
                    HarnessProfile(
                        excluded_tools=BLOCKED_TOOLS,
                        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                    ),
                )
        if spec.instructions:
            kwargs["system_prompt"] = spec.instructions
        if spec.subagents:
            kwargs["subagents"] = [
                {
                    "name": s.name,
                    "description": s.instructions,
                    "system_prompt": s.instructions,
                    "tools": list(s.tools),
                    "model": s.model or model,
                }
                for s in spec.subagents
            ]
        return create_deep_agent(**kwargs)

    def supports_subagents(self) -> bool:
        return True
