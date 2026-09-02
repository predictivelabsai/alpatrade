"""Regression tests for chat command routing.

Pins the two routing paths in the chat product:

1. **CLI command interception** — ``agent:*``, ``trades``, ``runs``, ``top``,
   ``positions``, ``help`` … are intercepted by ``agui_app._command_interceptor``
   and executed directly (never sent to the LLM). Long-running ``agent:*``
   commands return a ``StreamingCommand`` sentinel.

2. **Free-form text → LLM** — anything unrecognised (e.g. ``"backtest AAPL"``)
   returns ``None`` from the interceptor and falls through to the primary agent.
   The system prompt must therefore tell the LLM to redirect backtest / paper /
   full-cycle requests to the exact CLI command, since the LLM has no such tool.
"""
import asyncio

import pytest

from tui.command_processor import CommandProcessor


@pytest.fixture(autouse=True)
def _xai_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")


def test_system_prompt_redirects_backtest_requests_to_cli():
    """The LLM has no backtest tool, so the prompt must point users at the CLI."""
    from agui_app import SYSTEM_PROMPT

    assert "You have NO tool to run a backtest" in SYSTEM_PROMPT
    assert "agent:backtest symbols:AAPL lookback:3m" in SYSTEM_PROMPT
    assert "agent:paper duration:7d" in SYSTEM_PROMPT
    assert "agent:full lookback:1m duration:1m" in SYSTEM_PROMPT


def test_interceptor_routes_backtest_to_streaming_command():
    from agui_app import StreamingCommand, _command_interceptor

    result = asyncio.run(
        _command_interceptor(
            "agent:backtest symbols:AAPL lookback:3m",
            {"user": {"user_id": "user-123"}},
        )
    )

    assert isinstance(result, StreamingCommand)
    assert result.raw_command == "agent:backtest symbols:AAPL lookback:3m"


@pytest.mark.parametrize("command", ["trades", "runs", "top"])
def test_interceptor_routes_query_commands_to_processor(monkeypatch, command):
    from agui_app import _command_interceptor

    calls = []

    async def process(processor, cmd):
        calls.append((processor.user_id, cmd))
        return f"# {command.title()} result"

    monkeypatch.setattr(CommandProcessor, "process_command", process)

    result = asyncio.run(
        _command_interceptor(command, {"user": {"user_id": "user-123"}})
    )

    assert calls == [("user-123", command)]
    assert f"{command.title()} result" in result


def test_interceptor_routes_help_to_help_text():
    from agui_app import _command_interceptor

    result = asyncio.run(
        _command_interceptor("help", {"user": {"user_id": "user-123"}})
    )

    assert "agent:backtest" in result


def test_interceptor_routes_positions_to_alpaca_tool(monkeypatch):
    from agui_app import _command_interceptor

    # The interceptor lives in engine.ai.harness since the Phase 7 split;
    # patch the defining module, not the agui_app re-export.
    monkeypatch.setattr(
        "engine.ai.harness.get_alpaca_positions", lambda: "No open positions."
    )

    result = asyncio.run(
        _command_interceptor("positions", {"user": {"user_id": "user-123"}})
    )

    assert result == "No open positions."


def test_interceptor_returns_none_for_natural_language():
    """Free-form text must fall through to the LLM, not be swallowed."""
    from agui_app import _command_interceptor

    result = asyncio.run(
        _command_interceptor("backtest AAPL", {"user": {"user_id": "user-123"}})
    )

    assert result is None
