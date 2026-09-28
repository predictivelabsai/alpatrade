"""Regression tests for the 2026-09 LLM cost incident (DB- and network-free).

Covers: psycopg2 driver pinning, driver-agnostic INTERVAL SQL, NaN-safe run config,
the autonomy loop back-off / circuit breaker / daily cap, the plain single-call
reason(), current xAI model names with reasoning disabled, news usage accounting,
and the news batch cost ceiling on insert failures.
"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --- DB driver / SQL fixes ---------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("postgresql://u:p@h:5432/db", "postgresql+psycopg2://u:p@h:5432/db"),
    ("postgres://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
    ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_pool_pins_plain_postgres_urls_to_psycopg2(url, expected):
    from engine.db.pool import normalize_driver
    assert normalize_driver(url) == expected


def test_requirements_pin_sqlalchemy_below_2_1():
    root = Path(__file__).resolve().parents[1]
    assert "sqlalchemy>=2.0,<2.1" in (root / "requirements.txt").read_text()
    assert '"sqlalchemy>=2.0,<2.1"' in (root / "pyproject.toml").read_text()


class _Session:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        result = MagicMock()
        result.fetchall.return_value = []
        return result


def _pool_with(session):
    pool = MagicMock()

    @contextmanager
    def get_session():
        yield session
    pool.get_session = get_session
    return pool


def test_recent_day_trades_uses_cast_interval_not_bound_interval_literal():
    from utils import agent_storage
    session = _Session()
    with patch.object(agent_storage, "get_storage_backend", return_value="db"), \
         patch.object(agent_storage, "_get_pool", return_value=_pool_with(session)):
        agent_storage.fetch_recent_day_trades(7, user_id="u", account_id="a")
    sql, params = session.calls[0]
    # psycopg 3 renders "INTERVAL :days" as "INTERVAL $1" → syntax error (Sep 25+).
    assert "INTERVAL :days" not in sql
    assert "CAST(:days AS INTERVAL)" in sql
    assert params["days"] == "7 days"


def test_store_run_writes_strict_json_when_config_has_nan():
    from utils import agent_storage
    session = _Session()
    cfg = {"symbols": ["IBM"], "total_return": float("nan"), "nested": {"x": float("inf")}}
    with patch.object(agent_storage, "get_storage_backend", return_value="db"), \
         patch.object(agent_storage, "_get_pool", return_value=_pool_with(session)):
        agent_storage.store_run("r1", "paper", "buy_the_dip", config=cfg)
    _, params = session.calls[0]
    assert "NaN" not in params["config"] and "Infinity" not in params["config"]
    parsed = json.loads(params["config"], parse_constant=lambda c: pytest.fail(c))
    assert parsed["total_return"] is None and parsed["nested"]["x"] is None


# --- Autonomy loop guard -----------------------------------------------------

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_loop_guard_backs_off_exponentially_and_resets_on_success():
    from engine.autonomy.worker import LoopGuard
    g = LoopGuard(max_failures=10, pause_seconds=600, base_seconds=300, max_backoff=3600,
                  clock=_Clock())
    assert g.sleep_seconds(False) == 300
    waits = []
    for _ in range(5):
        g.record("failed")
        waits.append(g.sleep_seconds(True))
    assert waits == [300, 600, 1200, 2400, 3600]  # never below SCAN, capped
    g.record("ok")
    g.record("failed")
    assert g.sleep_seconds(True) == 300


def test_loop_guard_pauses_after_consecutive_failures_and_logs_event():
    from engine.autonomy.worker import LoopGuard
    clock = _Clock()
    g = LoopGuard(max_failures=3, pause_seconds=600, base_seconds=300, clock=clock)
    with patch("engine.autonomy.worker.store.append_event") as ev:
        g.record("failed")
        g.record("failed")
        assert not g.paused()
        g.record("failed")
    assert g.paused()
    assert ev.call_args.kwargs.get("level") == "error"
    assert "PAUSED" in ev.call_args.args[1]
    clock.t += 601
    assert not g.paused()


def test_self_feed_respects_daily_cap_and_fails_closed():
    from engine.autonomy import worker
    with patch.object(worker.queue, "full_runs_created_today", return_value=23):
        assert worker.self_feed_allowed(24) is True
    with patch.object(worker.queue, "full_runs_created_today", return_value=24):
        assert worker.self_feed_allowed(24) is False
    with patch.object(worker.queue, "full_runs_created_today", side_effect=RuntimeError("db")):
        assert worker.self_feed_allowed(24) is False
    assert worker.self_feed_allowed(0) is False


def test_run_one_reports_failed_outcome():
    from engine.autonomy import worker
    claimed = {"run_id": "r", "kind": "full", "attempt": 1, "config": {},
               "user_id": "u", "account_id": "a"}
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("paper_trade: boom")
    with patch.object(worker.queue, "claim", return_value=claimed), \
         patch.object(worker.queue, "fail", return_value="failed"), \
         patch.object(worker.store, "append_event"), \
         patch.object(worker, "default_pipeline", return_value=pipeline):
        assert worker.run_one("w") is True
    assert worker.last_outcome() == "failed"


def test_worker_loop_sleeps_after_a_failed_run_instead_of_rescouting(monkeypatch):
    """The Sep 2026 hot loop: a failed run immediately triggered a new scout + run."""
    from engine.autonomy import worker
    monkeypatch.setenv("AUTONOMY_ENABLED", "true")
    monkeypatch.setattr(worker.queue, "requeue_unfinished", lambda *_: 0)
    monkeypatch.setattr(worker.queue, "fail_uncertain_trading_jobs", lambda *_: 0)
    monkeypatch.setattr(worker, "sweep_stale_paper_runs", lambda *_: 0)
    monkeypatch.setattr(worker.queue, "pending_count", lambda: 0)
    monkeypatch.setattr(worker, "self_feed_allowed", lambda *a, **k: True)
    enqueued = []
    monkeypatch.setattr("engine.autonomy.scout.enqueue_run",
                        lambda **kw: enqueued.append(kw) or "rid")
    runs = iter([True, False])

    def fake_run_one(worker_id, *, advisor_only=False):
        processed = next(runs, False)
        worker._outcome.value = "failed" if processed else None
        return processed
    monkeypatch.setattr(worker, "run_one", fake_run_one)
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        raise KeyboardInterrupt
    monkeypatch.setattr(worker.time, "sleep", fake_sleep)
    monkeypatch.setattr("engine.premarket_jobs.start", lambda: None)
    monkeypatch.setattr("engine.autonomy.schedule.start", lambda: None)
    monkeypatch.setattr(worker.threading, "Thread", MagicMock())
    with pytest.raises(KeyboardInterrupt):
        worker.loop("w")
    assert len(enqueued) == 1
    assert sleeps and sleeps[0] >= worker.SCAN_SECONDS


def test_compose_keeps_autonomy_paused_by_default():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.yaml").read_text()
    assert "AUTONOMY_ENABLED=${AUTONOMY_SCOUT_ENABLED:-false}" in text
    assert "grok-4-1-fast-reasoning" not in text


# --- Cheaper model calls -----------------------------------------------------

def test_retired_xai_slugs_map_to_current_model():
    from engine.config import MODEL_NAMES, _DEFAULTS, current_xai_model
    assert current_xai_model("grok-4-1-fast-reasoning") == "grok-4.3"
    assert current_xai_model("grok-3-mini") == "grok-4.3"
    assert current_xai_model(None) == "grok-4.3"
    assert current_xai_model("grok-4.5") == "grok-4.5"
    assert _DEFAULTS["model_name"] == "grok-4.3"
    assert MODEL_NAMES["xai"][0] == "grok-4.3"
    assert "grok-4-1-fast-reasoning" not in MODEL_NAMES["xai"]


def test_build_chat_model_forwards_reasoning_effort_for_xai_only():
    from engine.config import Settings, build_chat_model
    s = Settings("xai", "grok-4-1-fast-reasoning", "yfinance", "tavily", "deepagents",
                 api_key="user-key")
    m = build_chat_model(s, streaming=False, max_tokens=50, reasoning_effort="none")
    payload = m._get_request_payload([("user", "hi")])
    assert payload["model"] == "grok-4.3"
    assert payload["reasoning_effort"] == "none"
    s2 = Settings("openai", "gpt-4o-mini", "yfinance", "tavily", "deepagents", api_key="k")
    payload2 = build_chat_model(s2, streaming=False, reasoning_effort="none")._get_request_payload(
        [("user", "hi")])
    assert "reasoning_effort" not in payload2


def test_reason_is_single_plain_call_with_budget_and_usage_logging():
    from engine.autonomy import reason as reason_mod
    from engine.config import Settings
    msg = MagicMock()
    msg.content = "  Params won on trend; watch gap risk.  "
    msg.usage_metadata = {"input_tokens": 120, "output_tokens": 15, "total_tokens": 135}
    model = MagicMock()
    model.invoke.return_value = msg
    model.model_name = "grok-4.3"
    settings = Settings("xai", "grok-4.3", "yfinance", "tavily", "deepagents")
    with patch("engine.config.get_settings", return_value=settings), \
         patch.object(reason_mod, "_build_model", return_value=model), \
         patch("engine.ai.llm_usage.enforce_daily_budget") as budget, \
         patch("engine.ai.llm_usage.record_usage") as record, \
         patch("deepagents.create_deep_agent", create=True) as deep:
        out = reason_mod.reason("why?", job_id="run-1")
    assert out == "Params won on trend; watch gap risk."
    model.invoke.assert_called_once()
    deep.assert_not_called()
    budget.assert_called_once_with(funding_source="platform")
    kw = record.call_args.kwargs
    assert kw["agent"] == "autonomy" and kw["model"] == "grok-4.3" and kw["job_id"] == "run-1"
    assert kw["usage"].input_tokens == 120 and kw["usage"].quality == "measured"


def test_reason_prompt_is_small():
    from engine.autonomy import reason as reason_mod
    assert len(reason_mod.SYSTEM_PROMPT) < 600  # was ~27k chars incl. deepagents tool schemas
    assert reason_mod.MAX_TOKENS <= 400
    assert reason_mod.REASONING_EFFORT == "none"


def test_reason_returns_empty_when_budget_exhausted():
    from engine.ai.llm_usage import DailyBudgetExceeded
    from engine.autonomy import reason as reason_mod
    from engine.config import Settings
    settings = Settings("xai", "grok-4.3", "yfinance", "tavily", "deepagents")
    with patch("engine.config.get_settings", return_value=settings), \
         patch("engine.ai.llm_usage.enforce_daily_budget",
               side_effect=DailyBudgetExceeded("cap")), \
         patch.object(reason_mod, "_build_model") as build:
        assert reason_mod.reason("why?") == ""
    build.assert_not_called()


def _fake_xai_client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.model_dump.return_value = {"prompt_tokens": 300, "completion_tokens": 40,
                                          "total_tokens": 340}
    client.chat.completions.create.return_value = resp
    return client


def test_news_enricher_uses_current_model_no_reasoning_and_logs_usage(monkeypatch):
    from news_scheduler.xai import XAIEnricher
    monkeypatch.setenv("XAI_MODEL", "grok-4-1-fast-reasoning")
    monkeypatch.delenv("XAI_REASONING_EFFORT", raising=False)
    client = _fake_xai_client('{"company": "A", "event": "earnings"}')
    with patch("engine.ai.llm_usage.enforce_daily_budget") as budget, \
         patch("engine.ai.llm_usage.record_usage") as record:
        enricher = XAIEnricher(client=client, account_usage=True)
        out = enricher.metadata({"title": "T", "content": "C"})
    assert out["company"] == "A"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "grok-4.3"
    assert kwargs["reasoning_effort"] == "none"
    budget.assert_called_once_with(funding_source="platform")
    rk = record.call_args.kwargs
    assert rk["agent"] == "news" and rk["job_id"] == "news-metadata"
    assert rk["usage"].input_tokens == 300


def test_news_enricher_budget_exhaustion_skips_provider_call():
    from engine.ai.llm_usage import DailyBudgetExceeded
    from news_scheduler.xai import XAIEnricher
    client = _fake_xai_client("x")
    with patch("engine.ai.llm_usage.enforce_daily_budget",
               side_effect=DailyBudgetExceeded("cap")):
        with pytest.raises(DailyBudgetExceeded):
            XAIEnricher(client=client, account_usage=True).reason({"title_en": "T"})
    client.chat.completions.create.assert_not_called()


def test_news_insert_failures_count_toward_batch_ceiling():
    from sqlalchemy.exc import ProgrammingError
    from news_scheduler.worker import Worker

    class FailingRepo:
        def __init__(self):
            self.state = {"processed_count": 0, "failed_count": 0}
            self.insert_calls = 0

        def checkpoint(self, *a): return dict(self.state)
        def update_checkpoint(self, *a, **v): self.state.update(v)
        def record_event(self, *a, **k): pass

        def insert_pending(self, row):
            self.insert_calls += 1
            raise ProgrammingError("INSERT", {}, Exception("IndeterminateDatatype"))

    repo = FailingRepo()
    publishers = MagicMock()
    publishers.collect.return_value = [{"title": str(i), "publisher": "p", "link": str(i)}
                                       for i in range(50)]
    pipeline = MagicMock()
    w = Worker("realtime", 3, 60, 0, 1, repository=repo, pipeline=pipeline,
               publishers=publishers)
    w._retry = lambda action, attempts=4: action()
    w._realtime_cycle()
    assert repo.insert_calls == 3
    pipeline.enrich_best_effort.assert_not_called()
