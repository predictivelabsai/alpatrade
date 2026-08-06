import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from engine.research import alpha_agents
from engine.research.alpha_agents import AlphaResearchResult
from tui.command_processor import CommandProcessor

REPORT = """## Thesis

Evidence-led test thesis.

## Methodology scorecard

| Criterion | Score | Confidence | Evidence |
|---|---:|---|---|
| Test | 3 | medium | Supplied evidence |

## Supporting evidence

- Supplied evidence.

## Catalysts

- None established.

## Risks and red flags

- Evidence is incomplete.

## Overall research view

hold — test view.

## Sources and limitations

Company profile only.
"""


def _evidence(**overrides):
    evidence = {
        "Company profile": {
            "status": "available",
            "content": "AAPL designs consumer technology products.",
        },
        "Annual financials": {
            "status": "available",
            "content": "Revenue grew in the supplied annual statements.",
        },
        "Valuation": {
            "status": "available",
            "content": "Forward P/E: 20.",
        },
        "Analyst ratings": {
            "status": "available",
            "content": "Consensus rating: Hold.",
        },
        "Recent news": {
            "status": "available",
            "content": "Five supplied headlines.",
        },
    }
    evidence.update(overrides)
    return evidence


def _settings():
    return SimpleNamespace(
        model_provider="openai",
        model_name="test-model",
        market_data_provider="yfinance",
        search_provider="tavily",
        agent_framework="langgraph",
    )


def _patch_storage(monkeypatch):
    created = []
    finished = []
    monkeypatch.setattr(alpha_agents, "_create_run", lambda *args: created.append(args))
    monkeypatch.setattr(
        alpha_agents, "_finish_run", lambda *args: finished.append(args)
    )
    return created, finished


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aapl", "AAPL"),
        ("brk.b", "BRK.B"),
        ("bf-b", "BF-B"),
        ("1234", "1234"),
    ],
)
def test_normalize_ticker_accepts_supported_single_symbols(raw, expected):
    assert alpha_agents.normalize_ticker(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "<ticker>", "AAPL,MSFT", "AAPL/MSFT", "$AAPL", "AAPL MSFT"],
)
def test_normalize_ticker_rejects_missing_placeholder_multiple_and_invalid(raw):
    with pytest.raises(ValueError):
        alpha_agents.normalize_ticker(raw)


def test_collect_evidence_uses_all_existing_research_calls_and_sanitizes_failures(
    monkeypatch,
):
    from utils import market_research_util

    calls = []

    class FakeResearch:
        def profile(self, ticker):
            calls.append(("profile", ticker))
            return "profile evidence"

        def financials(self, ticker, period):
            calls.append(("financials", ticker, period))
            return "annual evidence"

        def valuation(self, tickers):
            calls.append(("valuation", tickers))
            return "valuation evidence"

        def analysts(self, ticker):
            calls.append(("analysts", ticker))
            raise RuntimeError("Authorization: Bearer super-secret")

        def news(self, ticker, limit):
            calls.append(("news", ticker, limit))
            return "five recent headlines"

    monkeypatch.setattr(market_research_util, "MarketResearch", FakeResearch)

    evidence = asyncio.run(alpha_agents._collect_evidence("AAPL"))

    assert sorted(call[0] for call in calls) == [
        "analysts",
        "financials",
        "news",
        "profile",
        "valuation",
    ]
    assert ("financials", "AAPL", "annual") in calls
    assert ("valuation", ["AAPL"]) in calls
    assert ("news", "AAPL", 5) in calls
    assert evidence["Company profile"]["status"] == "available"
    assert evidence["Analyst ratings"] == {
        "status": "unavailable",
        "content": "Analyst ratings was unavailable for this run.",
    }
    assert "super-secret" not in str(evidence)


@pytest.mark.parametrize(
    ("mode", "methodology_phrase"),
    [
        ("growth", "Moat durability"),
        ("value", "Value-trap risk and red flags"),
    ],
)
def test_runner_uses_mode_prompt_user_model_and_persists_success(
    monkeypatch, mode, methodology_phrase
):
    created, finished = _patch_storage(monkeypatch)
    captured = {}

    async def collect(ticker):
        assert len(created) == 1
        captured["evidence_ticker"] = ticker
        return _evidence()

    class FakeModel:
        def invoke(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(content=REPORT)

    def get_settings(user_id):
        captured["settings_user"] = user_id
        return _settings()

    def build_model(settings, **kwargs):
        captured["model_settings"] = settings
        captured["model_kwargs"] = kwargs
        return FakeModel()

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", get_settings)
    monkeypatch.setattr(alpha_agents, "build_chat_model", build_model)

    result = asyncio.run(alpha_agents.run_alpha_research(mode, "aapl", "user-123"))

    assert result.status == "completed"
    assert result.saved is True
    assert result.ticker == "AAPL"
    assert captured["settings_user"] == "user-123"
    assert captured["evidence_ticker"] == "AAPL"
    assert captured["model_settings"].model_name == "test-model"
    assert captured["model_kwargs"] == {
        "streaming": False,
        "temperature": 0.1,
        "max_tokens": 2500,
    }
    system_prompt = captured["messages"][0].content
    user_prompt = captured["messages"][1].content
    assert methodology_phrase in system_prompt
    assert "Use only the supplied evidence" in system_prompt
    assert '"ticker": "AAPL"' in user_prompt
    assert "Forward P/E: 20" in user_prompt
    assert len(created) == 1
    assert created[0][1:] == (
        "user-123",
        mode,
        "AAPL",
        "openai",
        "test-model",
    )
    assert len(finished) == 1
    assert finished[0][1] == "completed"
    assert finished[0][4] is None
    markdown = result.as_markdown()
    assert f"**Saved run ID:** `{result.run_id}`" in markdown
    assert "Use `alpha:runs`" in markdown
    assert "no orders were placed" in markdown


def test_model_failure_returns_and_saves_sanitized_partial_evidence(monkeypatch):
    _, finished = _patch_storage(monkeypatch)

    async def collect(_ticker):
        return _evidence()

    class FailingModel:
        def invoke(self, _messages):
            raise RuntimeError("Authorization: Bearer model-secret")

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(
        alpha_agents,
        "build_chat_model",
        lambda *_args, **_kwargs: FailingModel(),
    )

    result = asyncio.run(alpha_agents.run_alpha_research("value", "BBY", "user-123"))

    assert result.status == "partial"
    assert "Model synthesis was unavailable" in result.report
    assert "Forward P/E: 20" in result.report
    assert "model-secret" not in result.as_markdown()
    assert finished[0][1] == "partial"
    assert finished[0][4] == "Model synthesis failed (RuntimeError)."


def test_no_evidence_records_failed_without_calling_model(monkeypatch):
    _, finished = _patch_storage(monkeypatch)

    async def collect(_ticker):
        return {
            label: {"status": "unavailable", "content": f"{label} unavailable."}
            for label in _evidence()
        }

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("model provider must not be called without evidence")

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(alpha_agents, "build_chat_model", unexpected_model)

    result = asyncio.run(alpha_agents.run_alpha_research("growth", "AAPL"))

    assert result.status == "failed"
    assert "Evidence could not be collected" in result.report
    assert finished[0][1] == "failed"
    assert finished[0][4] == "No research source returned usable evidence."


def test_persistence_failure_does_not_discard_completed_analysis(monkeypatch):
    async def collect(_ticker):
        return _evidence()

    class FakeModel:
        def invoke(self, _messages):
            return SimpleNamespace(content=REPORT)

    def fail_create(*_args):
        raise RuntimeError("postgres password=database-secret")

    def unexpected_finish(*_args):
        raise AssertionError("an unsaved run cannot be updated")

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(
        alpha_agents,
        "build_chat_model",
        lambda *_args, **_kwargs: FakeModel(),
    )
    monkeypatch.setattr(alpha_agents, "_create_run", fail_create)
    monkeypatch.setattr(alpha_agents, "_finish_run", unexpected_finish)

    result = asyncio.run(alpha_agents.run_alpha_research("growth", "AAPL"))

    assert result.status == "completed"
    assert result.saved is False
    assert "Not saved" in result.as_markdown()
    assert "Run ID (not saved)" in result.as_markdown()
    assert "sql/17_alpha_research_runs.sql" in result.as_markdown()
    assert "database-secret" not in result.as_markdown()


class _FakeQueryResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _FakeSession:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _FakeQueryResult(self.rows)


class _FakePool:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def get_session(self):
        yield self.session


@pytest.mark.parametrize(
    ("user_id", "requested_limit", "where_clause", "expected_params"),
    [
        ("user-123", 999, "user_id = :uid", {"uid": "user-123", "limit": 20}),
        (None, -5, "user_id IS NULL", {"limit": 1}),
    ],
)
def test_recent_run_query_is_user_isolated_and_limit_is_clamped(
    monkeypatch, user_id, requested_limit, where_clause, expected_params
):
    row = (
        "12345678-1234-1234-1234-123456789abc",
        "growth",
        "AAPL",
        "completed",
        "openai",
        "test-model",
        datetime(2026, 8, 6, tzinfo=UTC),
        datetime(2026, 8, 6, tzinfo=UTC),
    )
    session = _FakeSession([row])
    monkeypatch.setattr(alpha_agents, "get_pool", lambda: _FakePool(session))

    rows = alpha_agents.list_research_runs(user_id, requested_limit)

    sql, params = session.calls[0]
    assert where_clause in sql
    assert params == expected_params
    assert rows[0]["run_id"] == row[0]


def test_recent_runs_returns_migration_guidance_instead_of_crashing(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("connection included a sensitive credential")

    monkeypatch.setattr(alpha_agents, "list_research_runs", unavailable)

    markdown = alpha_agents.recent_runs_markdown("user-123", 10)

    assert "sql/17_alpha_research_runs.sql" in markdown
    assert "sensitive credential" not in markdown


def test_actual_storage_queries_bind_run_fields_and_json(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(alpha_agents, "get_pool", lambda: _FakePool(session))

    alpha_agents._create_run(
        "run-id",
        "user-123",
        "growth",
        "AAPL",
        "openai",
        "test-model",
    )
    alpha_agents._finish_run(
        "run-id",
        "partial",
        _evidence(),
        "partial report",
        "Model synthesis failed (RuntimeError).",
    )

    create_sql, create_params = session.calls[0]
    finish_sql, finish_params = session.calls[1]
    assert "INSERT INTO alpatrade.alpha_research_runs" in create_sql
    assert create_params["uid"] == "user-123"
    assert create_params["provider"] == "openai"
    assert "UPDATE alpatrade.alpha_research_runs" in finish_sql
    assert finish_params["status"] == "partial"
    assert '"Company profile"' in finish_params["evidence"]
    assert "password" not in finish_params["error"]


def _processor(user_id="user-123"):
    return CommandProcessor(SimpleNamespace(), user_id=user_id)


def test_alpha_commands_bypass_chat_and_dispatch_valid_growth_and_value(monkeypatch):
    calls = []

    async def run(mode, ticker, user_id):
        calls.append((mode, ticker, user_id))
        return AlphaResearchResult(
            run_id="12345678-1234-1234-1234-123456789abc",
            mode=mode,
            ticker=ticker,
            status="completed",
            report=REPORT,
            saved=True,
        )

    async def unexpected_chat(_input):
        raise AssertionError("structured alpha command reached free-form chat")

    monkeypatch.setattr(alpha_agents, "run_alpha_research", run)
    processor = _processor()
    processor._chat_agent = unexpected_chat

    growth_result = asyncio.run(processor.process_command("alpha:growth ticker:brk.b"))
    value_result = asyncio.run(processor.process_command("alpha:value ticker:bf-b"))

    assert calls == [
        ("growth", "BRK.B", "user-123"),
        ("value", "BF-B", "user-123"),
    ]
    assert "12345678-1234-1234-1234-123456789abc" in growth_result
    assert "12345678-1234-1234-1234-123456789abc" in value_result


@pytest.mark.parametrize(
    "command",
    [
        "alpha:growth",
        "alpha:growth ticker:<ticker>",
        "alpha:growth ticker:AAPL,MSFT",
        "alpha:growth ticker:AAPL/MSFT",
        "alpha:growth ticker:AAPL ticker:MSFT",
        "alpha:growth ticker:AAPL MSFT",
    ],
)
def test_invalid_alpha_tickers_return_usage_without_running(monkeypatch, command):
    async def unexpected_run(*_args):
        raise AssertionError("invalid ticker called data/model runner")

    monkeypatch.setattr(alpha_agents, "run_alpha_research", unexpected_run)

    result = asyncio.run(_processor().process_command(command))

    assert "Usage: `alpha:growth ticker:AAPL`" in result
    assert "Provide exactly one ticker" in result


def test_alpha_runs_command_formats_current_user_history(monkeypatch):
    calls = []

    def recent(user_id, limit):
        calls.append((user_id, limit))
        return "# Alpha Research Runs\n\nrecent rows"

    monkeypatch.setattr(alpha_agents, "recent_runs_markdown", recent)

    result = asyncio.run(_processor().process_command("alpha:runs limit:12"))

    assert calls == [("user-123", 12)]
    assert "recent rows" in result


def test_web_interceptor_marks_alpha_analysis_as_streaming(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    from agui_app import StreamingCommand, _command_interceptor

    result = asyncio.run(
        _command_interceptor(
            "alpha:value ticker:BBY",
            {"user": {"user_id": "user-123"}},
        )
    )

    assert isinstance(result, StreamingCommand)
    assert result.raw_command == "alpha:value ticker:BBY"


def test_web_interceptor_routes_alpha_runs_without_free_form_chat(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    from agui_app import _command_interceptor

    calls = []

    async def process(processor, command):
        calls.append((processor.user_id, command))
        return "# Alpha Research Runs\n\nweb history"

    monkeypatch.setattr(CommandProcessor, "process_command", process)

    result = asyncio.run(
        _command_interceptor(
            "alpha:runs limit:7",
            {"user": {"user_id": "user-123"}},
        )
    )

    assert calls == [("user-123", "alpha:runs limit:7")]
    assert "web history" in result


def test_alpha_help_and_completion_surfaces_are_present(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    from agui_app import _AGUI_HELP
    from tui.completer import COMMANDS

    output = StringIO()
    processor = _processor()
    processor.console = Console(file=output, width=220)
    processor._show_help()
    cli_help = output.getvalue()

    for command in ("alpha:growth", "alpha:value", "alpha:runs"):
        assert command in COMMANDS
        assert command in _AGUI_HELP
        assert command in cli_help


def test_alpha_migration_declares_idempotent_user_scoped_schema():
    sql = (Path(__file__).parents[1] / "sql" / "17_alpha_research_runs.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS alpatrade.alpha_research_runs" in sql
    assert "user_id UUID REFERENCES alpatrade.users(user_id) ON DELETE CASCADE" in sql
    assert "CHECK (mode IN ('growth', 'value'))" in sql
    assert "CHECK (ticker ~ '^[A-Z0-9][A-Z0-9.-]{0,15}$')" in sql
    assert "CHECK (status IN ('running', 'completed', 'partial', 'failed'))" in sql
    assert "evidence JSONB" in sql
    assert sql.count("CREATE INDEX IF NOT EXISTS") >= 2
