"""DB-free tests for the remote Hermes runtime and chat overrides."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_hermes_build_is_remote_role_not_langgraph():
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesAgent, HermesRuntime

    agent = HermesRuntime().build(RoleSpec(name="test", instructions="Be concise."))
    assert isinstance(agent, HermesAgent)
    assert agent.spec.instructions == "Be concise."


def test_hermes_payload_contains_role_history_and_prompt(monkeypatch):
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesRuntime

    monkeypatch.setenv("HERMES_API_MODEL", "hermes-agent-test")
    runtime = HermesRuntime()
    agent = runtime.build(RoleSpec(name="test", instructions="Trade safely."))
    payload = runtime._payload(
        agent,
        "Optimize AAPL",
        [{"role": "assistant", "content": "Ready."}],
        stream=True,
    )
    assert payload == {
        "model": "hermes-agent-test",
        "messages": [
            {"role": "system", "content": "Trade safely."},
            {"role": "assistant", "content": "Ready."},
            {"role": "user", "content": "Optimize AAPL"},
        ],
        "stream": True,
    }


def test_hermes_headers_scope_sessions_and_require_secret(monkeypatch):
    from engine.agents.runtime.hermes_rt import HermesRuntime

    monkeypatch.delenv("HERMES_API_SERVER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HERMES_API_SERVER_KEY"):
        HermesRuntime._headers()

    monkeypatch.setenv("HERMES_API_SERVER_KEY", "test-only-secret")
    headers = HermesRuntime._headers(session_id="thread-1", session_key="user-1")
    assert headers == {
        "Authorization": "Bearer test-only-secret",
        "X-Hermes-Session-Id": "thread-1",
        "X-Hermes-Session-Key": "user-1",
    }


def test_hermes_run_calls_openai_compatible_endpoint(monkeypatch):
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesRuntime

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Hermes reply"}}]}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            return Response()

    monkeypatch.setenv("HERMES_API_URL", "http://hermes.test:8642/v1/")
    monkeypatch.setenv("HERMES_API_SERVER_KEY", "test-only-secret")
    monkeypatch.setattr("engine.agents.runtime.hermes_rt.httpx.Client", Client)
    runtime = HermesRuntime()
    agent = runtime.build(RoleSpec(name="test"))

    result = runtime.run(agent, "hello")

    assert result.text == "Hermes reply"
    assert result.runtime == "hermes"
    assert captured["url"] == "http://hermes.test:8642/v1/chat/completions"
    assert captured["request"]["headers"]["Authorization"] == "Bearer test-only-secret"
    assert captured["request"]["json"]["stream"] is False


def test_agent_override_is_one_message_only():
    from engine.agents.routing import agent_override

    assert agent_override("/hermes optimize AAPL") == ("hermes", "optimize AAPL")
    assert agent_override("/deepagents explain this") == ("deepagents", "explain this")
    assert agent_override("/langgraph   compare") == ("langgraph", "compare")
    assert agent_override("ordinary message") == (None, "ordinary message")
    assert agent_override("/hermes") == ("hermes", "")
