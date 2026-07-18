"""Pluggable, LLM-agnostic agent-runtime adapters.

The LLM axis (which model) is handled by :mod:`engine.config`. This package is the
*framework* axis (how a role reasons / calls tools): one small ``AgentRuntime``
adapter per backend (LangGraph, DeepAgents, Pydantic AI, Hermes), selected by the
``AGENT_FRAMEWORK`` setting. The durable autonomy pipeline stays framework-agnostic
and calls agents only through :class:`~engine.agents.runtime.base.AgentRuntime`.

    from engine.agents.runtime import get_runtime, RoleSpec
    rt = get_runtime()                       # AGENT_FRAMEWORK, falls back to langgraph
    agent = rt.build(RoleSpec(name="scout", instructions="...", tools=[...]))
    result = rt.run(agent, "What are today's movers?")
"""
from engine.agents.runtime.base import AgentRuntime, RoleSpec, RunResult
from engine.agents.runtime.registry import get_runtime, available_runtimes

__all__ = ["AgentRuntime", "RoleSpec", "RunResult", "get_runtime", "available_runtimes"]
