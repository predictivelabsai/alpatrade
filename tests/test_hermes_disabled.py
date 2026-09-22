"""DB-free regression tests for the reversible Hermes shutdown."""
from pathlib import Path
import asyncio
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_hermes_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_ENABLED", raising=False)
    from engine.agents.hermes_feature import hermes_enabled
    from engine.agents.runtime.hermes_rt import HermesRuntime

    assert hermes_enabled() is False
    assert HermesRuntime.available() is False


def test_hermes_prefix_returns_explicit_disabled_route(monkeypatch):
    monkeypatch.delenv("HERMES_ENABLED", raising=False)
    from engine.agents.routing import agent_override

    assert agent_override("/hermes optimize AAPL") == (
        "hermes_disabled", "optimize AAPL",
    )
    assert agent_override("compare AAPL and MSFT") == (
        None, "compare AAPL and MSFT",
    )


def test_saved_hermes_preference_falls_back_to_deepagents(monkeypatch):
    monkeypatch.setenv("AGENT_FRAMEWORK", "hermes")
    from engine.config import get_settings

    assert get_settings().agent_framework == "deepagents"


def test_hermes_broker_rejects_requests_while_disabled(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException
    from api_app import require_hermes_user

    monkeypatch.delenv("HERMES_ENABLED", raising=False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_hermes_user("unused", "unused"))
    assert error.value.status_code == 503
    assert error.value.detail == "Hermes is disabled"


def test_compose_keeps_hermes_code_but_requires_explicit_profile():
    compose = (Path(__file__).parents[1] / "docker-compose.yaml").read_text()

    assert '  hermes:\n    profiles: ["hermes"]' in compose
    assert '  hermes-jobs:\n    profiles: ["hermes"]' in compose
    assert "hermes-data:" in compose
