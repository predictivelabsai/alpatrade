"""DB-free regressions for honest strategy advice and pasted chat commands."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from tui.command_processor import CommandProcessor


@pytest.fixture(autouse=True)
def _offline_model(monkeypatch):
    from engine import config

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    monkeypatch.setattr(config, "_resolve_xai_model", lambda model: model)


@pytest.fixture
def harness(monkeypatch):
    from engine.ai import harness

    monkeypatch.setattr(harness, "_app_states", {})
    return harness


def test_prompt_lists_real_strategies_and_capability_limits(harness):
    from utils.paper_strategies import STRATEGY_NAMES, PARAM_SCHEMA

    assert set(STRATEGY_NAMES) == set(PARAM_SCHEMA) == {
        "buy_the_dip", "momentum", "vix", "box_wedge",
    }
    supported = f"The only supported backtest strategies are: {', '.join(STRATEGY_NAMES)}."
    assert supported in harness.SYSTEM_PROMPT
    assert "Never invent strategy names" in harness.SYSTEM_PROMPT
    assert "cannot create, write or save strategy code or files" in harness.SYSTEM_PROMPT
    assert "say plainly that it is not supported" in harness.SYSTEM_PROMPT
    assert "closest supported strategy" in harness.SYSTEM_PROMPT
    assert "Give one command per message" in harness.SYSTEM_PROMPT


def test_chat_graph_excludes_file_tools_and_unguarded_subagent(monkeypatch, harness):
    import deepagents
    from engine.ai.deepagents import BLOCKED_TOOLS, BlockedToolMiddleware
    from engine.agents.runtime.deepagents_rt import DeepAgentsRuntime
    from langchain_openai import ChatOpenAI

    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    visible_tools = []

    def bind_tools(self, tools, **kwargs):
        visible_tools.extend(tool.name for tool in tools)
        return RunnableLambda(lambda messages: AIMessage(content="Supported strategies only."))

    monkeypatch.setattr(ChatOpenAI, "bind_tools", bind_tools)
    captured = []
    factory = deepagents.create_deep_agent

    def build(**kwargs):
        captured.append(kwargs)
        return factory(**kwargs)

    monkeypatch.setattr(deepagents, "create_deep_agent", build)
    model = ChatOpenAI(model="gpt-4o-mini", api_key="test-placeholder")
    graph = DeepAgentsRuntime().build(harness._chat_role(model))
    assert isinstance(captured[0]["middleware"][0], BlockedToolMiddleware)
    asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "List strategies"}]}))
    assert visible_tools
    assert not BLOCKED_TOOLS.intersection(visible_tools)
    assert "task" not in visible_tools
    assert "get_stock_price" in visible_tools

    # A per-user model override takes the same guarded construction path.
    from engine.config import Settings
    monkeypatch.setattr(harness, "_agent_cache", {})
    monkeypatch.setattr(harness, "get_settings", lambda uid=None: Settings(
        model_provider="openai", model_name="user-model" if uid else "default-model",
        agent_framework="deepagents", market_data_provider="yfinance", search_provider="tavily",
    ))
    monkeypatch.setattr(harness, "build_chat_model", lambda *a, **kw: model)
    harness.agent_for_user("user-1")
    assert len(captured) == 2
    assert isinstance(captured[1]["middleware"][0], BlockedToolMiddleware)


@pytest.mark.parametrize("tool", [
    "ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute",
])
def test_chat_tool_guard_rejects_sync_and_async_calls(tool):
    from engine.ai.deepagents import BlockedToolMiddleware

    request = SimpleNamespace(tool_call={"name": tool, "id": "call-1"})

    def executor(_request):
        pytest.fail("A blocked tool must never execute")

    guard = BlockedToolMiddleware()
    assert guard.wrap_tool_call(request, executor).status == "error"
    assert asyncio.run(guard.awrap_tool_call(request, executor)).status == "error"


def test_all_command_paste_executes_in_order_with_headings(monkeypatch, harness):
    calls = []
    commands = [f"agent:backtest strategy:{name}" for name in (
        "buy_the_dip", "momentum", "vix", "box_wedge",
    )]

    async def process(cp, command):
        calls.append((cp.user_id, command))
        await asyncio.sleep(0)
        return f"Result {len(calls)}"

    monkeypatch.setattr(CommandProcessor, "process_command", process)

    async def run():
        result = await harness._command_interceptor(
            "\n" + "\n\n".join(commands) + "\n", {"user": {"user_id": "user-1"}},
        )
        assert isinstance(result, harness.StreamingCommand)
        assert not calls
        return await result.run(CommandProcessor(result.app_state, user_id="user-1"))

    output = asyncio.run(run())
    assert calls == [("user-1", command) for command in commands]
    for index, command in enumerate(commands, 1):
        assert f"## Command {index}: `{command}`\n\nResult {index}" in output


@pytest.mark.parametrize("message", [
    "agent:backtest strategy:momentum\nPlease explain what this does.",
    "Please compare these:\nagent:backtest strategy:vix",
    "runs\nWhat do these results mean?",
])
def test_mixed_prose_is_not_intercepted(monkeypatch, harness, message):
    async def process(*args):
        pytest.fail("Mixed prose must not execute any command")

    monkeypatch.setattr(CommandProcessor, "process_command", process)
    assert asyncio.run(harness._command_interceptor(message, {})) is None


def test_paste_preserves_special_command_paths_and_continues_after_error(monkeypatch, harness):
    monkeypatch.setattr(harness, "get_alpaca_positions", lambda: "Positions result")

    async def process(cp, command):
        if command == "agent:backtest strategy:vix":
            raise ValueError("Invalid input")
        assert command == "runs"
        return "Runs result"

    monkeypatch.setattr(CommandProcessor, "process_command", process)

    async def run():
        result = await harness._command_interceptor(
            "help\npositions\nagent:backtest strategy:vix\nruns", {},
        )
        return await result.run(CommandProcessor(result.app_state))

    output = asyncio.run(run())
    assert harness._AGUI_HELP in output
    assert "Positions result" in output
    assert "Invalid input" in output
    assert "Runs result" in output


def test_web_paste_preserves_heartbeats_and_per_command_enrichment(monkeypatch, harness):
    from engine.web import ph_chat

    calls = []
    enriched = []

    async def process(cp, command):
        calls.append(command)
        await asyncio.sleep(0.01)
        return f"Output for {command}"

    def enrich(command, output, user_id):
        enriched.append((command, user_id))
        return output + " [chart]"

    real_wait_for = asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.001)

    monkeypatch.setattr(CommandProcessor, "process_command", process)
    monkeypatch.setattr(ph_chat.asyncio, "wait_for", short_wait)
    monkeypatch.setattr(ph_chat, "_save_chat_message", lambda *a, **kw: None)
    monkeypatch.setattr(ph_chat, "_load_owned_history", lambda *a: [])
    monkeypatch.setattr(ph_chat, "_maybe_append_equity", enrich)
    monkeypatch.setattr(ph_chat, "_HISTORY", {})

    commands = ["agent:backtest strategy:momentum", "agent:backtest strategy:vix"]

    async def run():
        response = await ph_chat._stream("\n".join(commands), {"user_id": "user-1"})
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(run())
    events = [json.loads(line[6:]) for chunk in chunks for line in chunk.splitlines()
              if line.startswith("data: ")]
    assert calls == commands
    assert enriched == [(command, "user-1") for command in commands]
    assert any("elapsed_seconds" in event for event in events)
    output = next(event["text"] for event in events if "text" in event)
    assert output.count("[chart]") == 2
    assert "## Command 1:" in output and "## Command 2:" in output


@pytest.mark.parametrize("command", [
    "agent:backtest strategy:momentum STRATEGY:vix",
    "agent:backtest lookback:1m\nagent:backtest lookback:3m",
    "runs limit:5 limit:10",
])
def test_duplicate_keys_return_clear_error_without_execution(monkeypatch, command):
    cp = CommandProcessor(SimpleNamespace())

    async def backtest(*args):
        pytest.fail("Invalid parameters must not execute a backtest")

    monkeypatch.setattr(cp, "_agent_backtest", backtest)
    monkeypatch.setattr(cp, "_agent_runs", lambda **kw: pytest.fail("Invalid query executed"))
    output = asyncio.run(cp.process_command(command))
    assert "Invalid command" in output
    assert "Duplicate parameter" in output
    assert "separate commands on separate lines" in output


def test_kv_parser_rejects_duplicates_and_keeps_unique_values():
    cp = CommandProcessor(SimpleNamespace())
    with pytest.raises(ValueError, match="Duplicate parameter 'strategy'"):
        cp._parse_kv_params(["strategy:momentum", "Strategy:vix"])
    assert cp._parse_kv_params(["strategy:momentum", "lookback:3m", "AAPL"]) == {
        "strategy": "momentum", "lookback": "3m", "_positional": "AAPL",
    }


def test_legacy_agui_paste_runs_each_command_and_appends_each_chart(monkeypatch, harness):
    from engine.ai import core
    from utils import equity_chart

    calls = []
    charts = []
    sent = []
    session = {"user": {"user_id": "user-1"}}
    commands = ["agent:backtest strategy:momentum", "agent:backtest strategy:vix"]

    async def process(cp, command):
        calls.append(command)
        return f"Run ID: `{len(calls):08d}`"

    def show_curve(run_id):
        charts.append(run_id)
        return f"__CHART_DATA__{run_id}__END_CHART__"

    async def send(value=None):
        sent.append(value)

    monkeypatch.setattr(CommandProcessor, "process_command", process)
    monkeypatch.setattr(equity_chart, "show_equity_curve", show_curve)
    monkeypatch.setattr(core, "save_conversation", lambda *a, **kw: None)
    monkeypatch.setattr(core, "save_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_enrich_result", lambda *a: None)
    thread = SimpleNamespace(
        _messages=[], thread_id="thread-1", _user_id="user-1", send=send,
        _send_js=send, _refresh_conv_list=send, set_suggestions=send,
        ui=SimpleNamespace(_clear_input=lambda: ""),
    )

    async def run():
        msg = "\n".join(commands)
        result = await harness._command_interceptor(msg, session)
        await core.AGUIThread._handle_streaming_command(thread, msg, result, session)

    asyncio.run(run())
    assert calls == commands
    assert charts == ["00000001", "00000002"]
    output = thread._messages[-1]["content"]
    assert "## Command 1:" in output and "## Command 2:" in output
    assert output.count("__CHART_DATA__") == 2
