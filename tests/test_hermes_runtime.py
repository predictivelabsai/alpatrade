"""DB-free tests for the remote Hermes runtime and chat overrides."""
from pathlib import Path
import json
import sys

import httpx
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
        "stream_options": {"include_usage": True},
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


def test_hermes_run_parses_usage(monkeypatch):
    import httpx

    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesRuntime

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "Done"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return Response()

    monkeypatch.setenv("HERMES_API_URL", "http://hermes.test:8642/v1")
    monkeypatch.setenv("HERMES_API_SERVER_KEY", "test-only-secret")
    monkeypatch.setattr("engine.agents.runtime.hermes_rt.httpx.Client", Client)
    runtime = HermesRuntime()
    agent = runtime.build(RoleSpec(name="test"))

    result = runtime.run(agent, "hello")

    assert result.text == "Done"
    assert runtime.last_usage == {"prompt_tokens": 11, "completion_tokens": 4}


class _FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return None


class _FakeStreamResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://hermes.test:8642/v1/chat/completions"),
                response=self,
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    """AsyncClient stand-in returning one queued stream response per call."""

    def __init__(self, responses, **kwargs):
        self._responses = list(responses)
        self.stream_payloads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, method, url, headers=None, json=None):
        self.stream_payloads.append(json)
        return _FakeStreamCtx(self._responses.pop(0))


def _drain_astream(runtime, agent, prompt, **kwargs):
    import asyncio

    async def _run():
        out = []
        async for text in runtime.astream(agent, prompt, **kwargs):
            out.append(text)
        return out

    return asyncio.run(_run())


def test_hermes_astream_handles_usage_chunk_with_empty_choices(monkeypatch):
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesRuntime

    usage_chunk = {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
    lines = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}',
        f"data: {json.dumps(usage_chunk)}",
        "data: [DONE]",
    ]

    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__([_FakeStreamResponse(lines)], **kwargs)

    monkeypatch.setenv("HERMES_API_URL", "http://hermes.test:8642/v1")
    monkeypatch.setenv("HERMES_API_SERVER_KEY", "test-only-secret")
    monkeypatch.setattr("engine.agents.runtime.hermes_rt.httpx.AsyncClient", Client)
    runtime = HermesRuntime()
    agent = runtime.build(RoleSpec(name="test"))

    seen_usage = []
    chunks = _drain_astream(
        runtime, agent, "hello", usage_callback=seen_usage.append
    )

    assert chunks == ["Hi"]
    assert seen_usage == [{"prompt_tokens": 5, "completion_tokens": 2}]
    assert runtime.last_usage == {"prompt_tokens": 5, "completion_tokens": 2}


def test_hermes_astream_retries_without_stream_options_on_4xx(monkeypatch, caplog):
    from engine.agents.runtime.base import RoleSpec
    from engine.agents.runtime.hermes_rt import HermesRuntime

    lines = ['data: {"choices": [{"delta": {"content": "Ok"}}]}', "data: [DONE]"]

    class Client(_FakeAsyncClient):
        payloads = []
        responses = [
            _FakeStreamResponse([], status=400),
            _FakeStreamResponse(lines),
        ]

        def __init__(self, **kwargs):
            # The runtime builds one AsyncClient per attempt; the response
            # queue and the captured payloads are class-level so attempts
            # share them in order.
            super().__init__([], **kwargs)

        def stream(self, method, url, headers=None, json=None):
            Client.payloads.append(json)
            return _FakeStreamCtx(Client.responses.pop(0))

    monkeypatch.setenv("HERMES_API_URL", "http://hermes.test:8642/v1")
    monkeypatch.setenv("HERMES_API_SERVER_KEY", "test-only-secret")
    monkeypatch.setattr("engine.agents.runtime.hermes_rt.httpx.AsyncClient", Client)
    runtime = HermesRuntime()
    agent = runtime.build(RoleSpec(name="test"))

    with caplog.at_level("WARNING", logger="engine.agents.runtime.hermes_rt"):
        chunks = _drain_astream(runtime, agent, "hello")

    assert chunks == ["Ok"]
    assert len(Client.payloads) == 2
    # First attempt opts in, retry strips the parameter.
    assert Client.payloads[0].get("stream_options") == {"include_usage": True}
    assert "stream_options" not in Client.payloads[1]


def test_agent_override_is_one_message_only():
    from engine.agents.routing import agent_override

    assert agent_override("/hermes optimize AAPL") == ("hermes", "optimize AAPL")
    assert agent_override("/deepagents explain this") == ("deepagents", "explain this")
    assert agent_override("/langgraph   compare") == ("langgraph", "compare")
    assert agent_override("ordinary message") == (None, "ordinary message")
    assert agent_override("/hermes") == ("hermes", "")
