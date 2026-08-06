import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from engine.research import alpha_agents
from engine.research.alpha_agents import AlphaComparisonResult, AlphaResearchResult
from tui.command_processor import CommandProcessor

RUN_ID = "12345678-1234-1234-1234-123456789abc"

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

COMPACT_REPORT = """## Thesis

Compact evidence-led thesis.

## Methodology scorecard

| Criterion | Score | Confidence | Evidence |
|---|---:|---|---|
| Test | 3 | medium | Supplied evidence |

## Top catalyst

- Evidence-backed catalyst.

## Top risk

- Evidence-backed risk.

## Overall research view

hold — compact test view.

## Sources and limitations

- Company profile only.
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


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "<uuid>",
        "not-a-uuid",
        "12345678123412341234123456789abc",
        "12345678-1234-1234-1234-123456789abz",
    ],
)
def test_normalize_run_id_rejects_nonstandard_uuids(raw):
    with pytest.raises(ValueError):
        alpha_agents.normalize_run_id(raw)


def test_normalize_run_id_accepts_and_canonicalizes_standard_uuid():
    assert alpha_agents.normalize_run_id(RUN_ID.upper()) == RUN_ID


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


def test_comparison_collects_sources_once_and_runs_two_compact_models(monkeypatch):
    from utils import market_research_util

    created, finished = _patch_storage(monkeypatch)
    source_calls = []
    prompts = []
    model_kwargs = []
    settings_users = []

    class FakeResearch:
        def __init__(self):
            assert len(created) == 2

        def profile(self, ticker):
            source_calls.append(("profile", ticker))
            return "profile evidence"

        def financials(self, ticker, period):
            source_calls.append(("financials", ticker, period))
            return "annual evidence"

        def valuation(self, tickers):
            source_calls.append(("valuation", tickers))
            return "valuation evidence"

        def analysts(self, ticker):
            source_calls.append(("analysts", ticker))
            return "analyst evidence"

        def news(self, ticker, limit):
            source_calls.append(("news", ticker, limit))
            return "five recent headlines"

    class FakeModel:
        def invoke(self, messages):
            prompts.append([message.content for message in messages])
            return SimpleNamespace(content=COMPACT_REPORT)

    def settings(user_id):
        settings_users.append(user_id)
        return _settings()

    def build_model(_settings_value, **kwargs):
        model_kwargs.append(kwargs)
        return FakeModel()

    monkeypatch.setattr(market_research_util, "MarketResearch", FakeResearch)
    monkeypatch.setattr(alpha_agents, "get_settings", settings)
    monkeypatch.setattr(alpha_agents, "build_chat_model", build_model)

    result = asyncio.run(alpha_agents.run_alpha_comparison("aapl", "user-123"))

    assert result.status == "completed"
    assert result.ticker == "AAPL"
    assert settings_users == ["user-123"]
    assert sorted(call[0] for call in source_calls) == [
        "analysts",
        "financials",
        "news",
        "profile",
        "valuation",
    ]
    assert ("financials", "AAPL", "annual") in source_calls
    assert ("valuation", ["AAPL"]) in source_calls
    assert ("news", "AAPL", 5) in source_calls
    assert sorted(args[2] for args in created) == ["growth", "value"]
    assert len(prompts) == 2
    system_prompts = [messages[0] for messages in prompts]
    assert any("Alpha Growth Agent" in prompt for prompt in system_prompts)
    assert any("Alpha Value Agent" in prompt for prompt in system_prompts)
    assert all("under 450 words" in prompt for prompt in system_prompts)
    assert model_kwargs == [
        {"streaming": False, "temperature": 0.1, "max_tokens": 1400},
        {"streaming": False, "temperature": 0.1, "max_tokens": 1400},
    ]
    assert sorted(args[1] for args in finished) == ["completed", "completed"]
    markdown = result.as_markdown()
    assert "# Alpha Combined View — AAPL" in markdown
    assert "**Status:** completed" in markdown
    assert result.growth.run_id in markdown
    assert result.value.run_id in markdown
    assert "## Growth view" in markdown
    assert "## Value view" in markdown
    assert "### Thesis" in markdown
    assert "Use `alpha:runs`" in markdown


def test_comparison_preserves_completed_and_partial_results(monkeypatch):
    _, finished = _patch_storage(monkeypatch)

    async def collect(_ticker):
        return _evidence()

    class SelectiveModel:
        def invoke(self, messages):
            if "Alpha Value Agent" in messages[0].content:
                raise RuntimeError("Authorization: Bearer comparison-secret")
            return SimpleNamespace(content=COMPACT_REPORT)

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(
        alpha_agents,
        "build_chat_model",
        lambda *_args, **_kwargs: SelectiveModel(),
    )

    result = asyncio.run(alpha_agents.run_alpha_comparison("AAPL", "user-123"))

    assert result.status == "partial"
    assert result.growth.status == "completed"
    assert result.value.status == "partial"
    assert sorted(args[1] for args in finished) == ["completed", "partial"]
    assert "Synthesis unavailable" in result.value.report
    assert "comparison-secret" not in result.as_markdown()
    assert "**Status:** partial" in result.as_markdown()


def test_comparison_fails_both_rows_without_evidence_or_model_calls(monkeypatch):
    _, finished = _patch_storage(monkeypatch)
    collections = []

    async def collect(ticker):
        collections.append(ticker)
        return {
            label: {"status": "unavailable", "content": f"{label} unavailable."}
            for label in _evidence()
        }

    def unexpected_model(*_args, **_kwargs):
        raise AssertionError("model provider must not be called without evidence")

    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(alpha_agents, "build_chat_model", unexpected_model)

    result = asyncio.run(alpha_agents.run_alpha_comparison("AAPL"))

    assert collections == ["AAPL"]
    assert result.status == "failed"
    assert result.growth.status == "failed"
    assert result.value.status == "failed"
    assert sorted(args[1] for args in finished) == ["failed", "failed"]
    assert "**Status:** failed" in result.as_markdown()


def test_comparison_tracks_one_persistence_update_failure_independently(monkeypatch):
    created_modes = {}
    finish_attempts = []

    def create(run_id, _user_id, mode, *_args):
        created_modes[run_id] = mode

    def finish(run_id, *_args):
        finish_attempts.append(run_id)
        if created_modes[run_id] == "value":
            raise RuntimeError("postgres password=comparison-database-secret")

    async def collect(_ticker):
        return _evidence()

    class FakeModel:
        def invoke(self, _messages):
            return SimpleNamespace(content=COMPACT_REPORT)

    monkeypatch.setattr(alpha_agents, "_create_run", create)
    monkeypatch.setattr(alpha_agents, "_finish_run", finish)
    monkeypatch.setattr(alpha_agents, "_collect_evidence", collect)
    monkeypatch.setattr(alpha_agents, "get_settings", lambda _uid: _settings())
    monkeypatch.setattr(
        alpha_agents,
        "build_chat_model",
        lambda *_args, **_kwargs: FakeModel(),
    )

    result = asyncio.run(alpha_agents.run_alpha_comparison("AAPL", "user-123"))

    assert result.status == "completed"
    assert result.growth.saved is True
    assert result.value.saved is False
    assert len(finish_attempts) == 2
    markdown = result.as_markdown()
    assert "Value not saved" in markdown
    assert "PostgreSQL could not update" in markdown
    assert "comparison-database-secret" not in markdown


class _FakeQueryResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


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


@pytest.mark.parametrize(
    ("user_id", "where_clause", "expected_params"),
    [
        (
            "user-123",
            "user_id = :uid",
            {"rid": RUN_ID, "uid": "user-123"},
        ),
        (None, "user_id IS NULL", {"rid": RUN_ID}),
    ],
)
def test_saved_run_query_is_user_isolated_and_parameterized(
    monkeypatch, user_id, where_clause, expected_params
):
    row = (RUN_ID, "growth", "AAPL", "completed", REPORT)
    session = _FakeSession([row])
    monkeypatch.setattr(alpha_agents, "get_pool", lambda: _FakePool(session))

    saved = alpha_agents.get_research_run(user_id, RUN_ID.upper())

    sql, params = session.calls[0]
    assert "run_id = :rid" in sql
    assert where_clause in sql
    assert params == expected_params
    assert "error" not in sql.lower()
    assert saved == {
        "run_id": RUN_ID,
        "mode": "growth",
        "ticker": "AAPL",
        "status": "completed",
        "report_markdown": REPORT,
    }


@pytest.mark.parametrize(
    ("status", "report", "expected"),
    [
        ("completed", REPORT, "Evidence-led test thesis."),
        ("partial", "## Research status\n\nPartial evidence.", "Partial evidence."),
        ("failed", "## Research status\n\nNo usable evidence.", "No usable evidence."),
        ("running", None, "No report Markdown was saved for this run."),
        ("completed", "", "No report Markdown was saved for this run."),
    ],
)
def test_saved_run_renders_status_and_stored_report(
    monkeypatch, status, report, expected
):
    def saved(_user_id, _run_id):
        return {
            "run_id": RUN_ID,
            "mode": "growth",
            "ticker": "AAPL",
            "status": status,
            "report_markdown": report,
        }

    def unexpected(*_args, **_kwargs):
        raise AssertionError("saved report retrieval called a data or model provider")

    monkeypatch.setattr(alpha_agents, "get_research_run", saved)
    monkeypatch.setattr(alpha_agents, "get_settings", unexpected)
    monkeypatch.setattr(alpha_agents, "build_chat_model", unexpected)
    monkeypatch.setattr(alpha_agents, "_collect_evidence", unexpected)

    markdown = alpha_agents.saved_run_markdown("user-123", RUN_ID)

    assert "# Alpha Growth Agent — AAPL" in markdown
    assert f"**Saved run ID:** `{RUN_ID}`" in markdown
    assert f"**Status:** {status}" in markdown
    assert expected in markdown
    assert "Read-only research; no orders were placed" in markdown
    assert "Use `alpha:runs`" in markdown


def test_missing_and_unauthorized_saved_runs_share_not_found_response(monkeypatch):
    monkeypatch.setattr(alpha_agents, "get_research_run", lambda *_args: None)

    missing = alpha_agents.saved_run_markdown("user-123", RUN_ID)
    unauthorized = alpha_agents.saved_run_markdown("other-user", RUN_ID)

    assert missing == unauthorized
    assert "No saved report was found" in missing
    assert "Use `alpha:runs`" in missing


def test_saved_run_returns_migration_guidance_without_leaking_storage_error(
    monkeypatch,
):
    def unavailable(*_args):
        raise RuntimeError("connection password=saved-report-secret")

    monkeypatch.setattr(alpha_agents, "get_research_run", unavailable)

    markdown = alpha_agents.saved_run_markdown("user-123", RUN_ID)

    assert "sql/17_alpha_research_runs.sql" in markdown
    assert "saved-report-secret" not in markdown


def test_invalid_saved_run_id_returns_usage_without_querying_database(monkeypatch):
    def unexpected_pool():
        raise AssertionError("invalid run ID queried PostgreSQL")

    monkeypatch.setattr(alpha_agents, "get_pool", unexpected_pool)

    markdown = alpha_agents.saved_run_markdown("user-123", "not-a-uuid")

    assert "Usage: `alpha:show run-id:<uuid>`" in markdown


def test_recent_runs_returns_migration_guidance_instead_of_crashing(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("connection included a sensitive credential")

    monkeypatch.setattr(alpha_agents, "list_research_runs", unavailable)

    markdown = alpha_agents.recent_runs_markdown("user-123", 10)

    assert "sql/17_alpha_research_runs.sql" in markdown
    assert "sensitive credential" not in markdown


def test_recent_runs_includes_saved_report_hint(monkeypatch):
    monkeypatch.setattr(
        alpha_agents,
        "list_research_runs",
        lambda *_args: [
            {
                "run_id": RUN_ID,
                "mode": "growth",
                "ticker": "AAPL",
                "status": "completed",
                "model_provider": "openai",
                "model_name": "test-model",
                "created_at": datetime(2026, 8, 6, tzinfo=UTC),
                "completed_at": datetime(2026, 8, 6, tzinfo=UTC),
            }
        ],
    )

    markdown = alpha_agents.recent_runs_markdown("user-123", 10)

    assert RUN_ID in markdown
    assert "Open one with `alpha:show run-id:<uuid>`" in markdown


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


def _comparison_result(ticker="AAPL"):
    return AlphaComparisonResult(
        ticker=ticker,
        growth=AlphaResearchResult(
            run_id="11111111-1111-1111-1111-111111111111",
            mode="growth",
            ticker=ticker,
            status="completed",
            report=COMPACT_REPORT,
            saved=True,
        ),
        value=AlphaResearchResult(
            run_id="22222222-2222-2222-2222-222222222222",
            mode="value",
            ticker=ticker,
            status="completed",
            report=COMPACT_REPORT,
            saved=True,
        ),
    )


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


def test_alpha_compare_bypasses_chat_and_dispatches_combined_view(monkeypatch):
    calls = []

    async def compare(ticker, user_id):
        calls.append((ticker, user_id))
        return _comparison_result(ticker)

    async def unexpected_chat(_input):
        raise AssertionError("structured alpha command reached free-form chat")

    monkeypatch.setattr(alpha_agents, "run_alpha_comparison", compare)
    processor = _processor()
    processor._chat_agent = unexpected_chat

    result = asyncio.run(processor.process_command("alpha:compare ticker:brk.b"))

    assert calls == [("BRK.B", "user-123")]
    assert "# Alpha Combined View — BRK.B" in result
    assert "11111111-1111-1111-1111-111111111111" in result
    assert "22222222-2222-2222-2222-222222222222" in result


@pytest.mark.parametrize(
    "command",
    [
        "alpha:growth",
        "alpha:growth ticker:<ticker>",
        "alpha:growth ticker:AAPL,MSFT",
        "alpha:growth ticker:AAPL/MSFT",
        "alpha:growth ticker:AAPL ticker:MSFT",
        "alpha:growth ticker:AAPL MSFT",
        "alpha:compare",
        "alpha:compare ticker:<ticker>",
        "alpha:compare ticker:AAPL,MSFT",
        "alpha:compare ticker:AAPL/MSFT",
        "alpha:compare ticker:AAPL ticker:MSFT",
        "alpha:compare ticker:AAPL MSFT",
    ],
)
def test_invalid_alpha_tickers_return_usage_without_running(monkeypatch, command):
    async def unexpected_run(*_args):
        raise AssertionError("invalid ticker called data/model runner")

    monkeypatch.setattr(alpha_agents, "run_alpha_research", unexpected_run)
    monkeypatch.setattr(alpha_agents, "run_alpha_comparison", unexpected_run)

    result = asyncio.run(_processor().process_command(command))

    subcommand = command.split()[0]
    assert f"Usage: `{subcommand} ticker:AAPL`" in result
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


def test_alpha_show_bypasses_chat_and_dispatches_user_scoped_saved_report(monkeypatch):
    calls = []

    def show(user_id, run_id):
        calls.append((user_id, run_id))
        return "# Alpha Growth Agent — AAPL\n\nsaved report"

    async def unexpected_chat(_input):
        raise AssertionError("structured alpha command reached free-form chat")

    monkeypatch.setattr(alpha_agents, "saved_run_markdown", show)
    processor = _processor()
    processor._chat_agent = unexpected_chat

    result = asyncio.run(
        processor.process_command(f"alpha:show run-id:{RUN_ID.upper()}")
    )

    assert calls == [("user-123", RUN_ID)]
    assert "saved report" in result


@pytest.mark.parametrize(
    "command",
    [
        "alpha:show",
        "alpha:show run-id:<uuid>",
        "alpha:show run-id:not-a-uuid",
        "alpha:show run-id:12345678123412341234123456789abc",
        f"alpha:show run-id:{RUN_ID} run-id:{RUN_ID}",
        f"alpha:show {RUN_ID}",
        f"alpha:show run-id:{RUN_ID} extra:true",
    ],
)
def test_invalid_alpha_show_arguments_return_usage_without_loading(
    monkeypatch, command
):
    def unexpected_show(*_args):
        raise AssertionError("invalid command loaded a saved report")

    monkeypatch.setattr(alpha_agents, "saved_run_markdown", unexpected_show)

    result = asyncio.run(_processor().process_command(command))

    assert "Usage: `alpha:show run-id:<uuid>`" in result
    assert "Provide exactly one standard UUID" in result


@pytest.mark.parametrize(
    "command",
    ["alpha:value ticker:BBY", "alpha:compare ticker:AAPL"],
)
def test_web_interceptor_marks_alpha_analysis_as_streaming(monkeypatch, command):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    from agui_app import StreamingCommand, _command_interceptor

    result = asyncio.run(
        _command_interceptor(
            command,
            {"user": {"user_id": "user-123"}},
        )
    )

    assert isinstance(result, StreamingCommand)
    assert result.raw_command == command


@pytest.mark.parametrize(
    "command",
    ["alpha:runs limit:7", f"alpha:show run-id:{RUN_ID}"],
)
def test_web_interceptor_routes_immediate_alpha_commands_without_streaming(
    monkeypatch, command
):
    monkeypatch.setenv("XAI_API_KEY", "test-placeholder")
    from agui_app import _command_interceptor

    calls = []

    async def process(processor, command):
        calls.append((processor.user_id, command))
        return "# Alpha Research Runs\n\nweb history"

    monkeypatch.setattr(CommandProcessor, "process_command", process)

    result = asyncio.run(
        _command_interceptor(
            command,
            {"user": {"user_id": "user-123"}},
        )
    )

    assert calls == [("user-123", command)]
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

    for command in (
        "alpha:growth",
        "alpha:value",
        "alpha:compare",
        "alpha:runs",
        "alpha:show",
    ):
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
