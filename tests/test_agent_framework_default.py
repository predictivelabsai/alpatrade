"""Unit tests for the primary DeepAgents framework resolution (DB-free)."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_FRAMEWORK", raising=False)


def test_default_framework_is_deepagents():
    from engine.config import get_settings
    assert get_settings().agent_framework == "deepagents"


def test_registry_default_is_deepagents():
    from engine.agents.runtime import registry
    assert registry._FALLBACK == "deepagents"


def test_unknown_framework_falls_back_to_deepagents():
    from engine.agents.runtime import registry
    rt = registry.get_runtime("not-a-framework")
    assert rt.name == "deepagents"


def test_unavailable_primary_falls_back_to_langgraph(monkeypatch):
    from engine.agents.runtime import registry

    class UnavailableRuntime:
        name = "deepagents"

        @staticmethod
        def available():
            return False

    class AvailableRuntime:
        name = "langgraph"

        @staticmethod
        def available():
            return True

    monkeypatch.setattr(
        registry,
        "_load",
        lambda key: UnavailableRuntime if key == "deepagents" else AvailableRuntime,
    )
    assert registry.get_runtime("deepagents").name == "langgraph"


def test_env_override_still_wins(monkeypatch):
    monkeypatch.setenv("AGENT_FRAMEWORK", "langgraph")
    from engine.config import get_settings
    assert get_settings().agent_framework == "langgraph"


def test_deepagents_runtime_builds_named_graph_with_subagent(monkeypatch):
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.deepagents_rt import DeepAgentsRuntime

    captured = {}
    sentinel_graph = object()

    def create_deep_agent(**kwargs):
        captured.update(kwargs)
        return sentinel_graph

    monkeypatch.setitem(
        sys.modules,
        "deepagents",
        types.SimpleNamespace(create_deep_agent=create_deep_agent),
    )
    model = object()
    specialist = RoleSpec(
        name="portfolio-analyst",
        instructions="Analyse portfolio risk.",
    )
    spec = RoleSpec(
        name="alpatrade-chat",
        instructions="Help with paper trading.",
        tools=[lambda: None],
        model=model,
        subagents=[specialist],
    )

    graph = DeepAgentsRuntime().build(spec)

    assert graph is sentinel_graph
    assert captured["name"] == "alpatrade-chat"
    assert captured["model"] is model
    assert captured["system_prompt"] == "Help with paper trading."
    assert captured["subagents"][0]["name"] == "portfolio-analyst"
    assert captured["subagents"][0]["model"] is model
