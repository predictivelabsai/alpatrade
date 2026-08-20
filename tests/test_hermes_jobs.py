"""Contracts for durable, scoped Hermes background execution."""
import asyncio
import inspect
from pathlib import Path


def test_backtest_endpoint_enqueues_and_preserves_delegated_identity(monkeypatch):
    from api_app import hermes_backtest
    from api_models import HermesBacktestRequest
    from engine.agents import hermes_jobs

    captured = {}

    def fake_enqueue(kind, user_id, thread_id, config, **kwargs):
        captured.update(kind=kind, user_id=user_id, thread_id=thread_id,
                        config=config, kwargs=kwargs)
        return {"job_id": "job-1", "run_id": "run-1", "status": "queued"}

    monkeypatch.setattr(hermes_jobs, "enqueue", fake_enqueue)
    request = HermesBacktestRequest(
        symbols="AAPL,MSFT", lookback="3m", capital=25000,
        objective={"maximize": "sharpe_ratio"},
    )
    user = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "thread_id": "22222222-2222-2222-2222-222222222222",
        "auth_type": "hermes",
    }
    response = asyncio.run(hermes_backtest(request, user))

    assert response["status"] == "queued"
    assert captured["kind"] == "backtest"
    assert captured["user_id"] == user["user_id"]
    assert captured["thread_id"] == user["thread_id"]
    assert captured["config"]["symbols"] == ["AAPL", "MSFT"]
    assert captured["config"]["initial_capital"] == 25000


def test_chat_dispatch_parses_background_backtest_without_remote_model():
    from engine.web.ph_chat import _hermes_backtest_config

    config = _hermes_backtest_config(
        "start a background buy_the_dip backtest for AAPL, MSFT, GOOGL, AMZN, "
        "META, TSLA and NVDA over the last 3 months; maximize Sharpe"
    )
    assert config["strategy"] == "buy_the_dip"
    assert config["lookback"] == "3m"
    assert config["symbols"] == ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]


def test_chat_dispatch_returns_queue_ack_immediately(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "enqueue", lambda *args, **kwargs: {
        "job_id": "job-1", "run_id": "run-1", "status": "queued",
    })
    reply = asyncio.run(_dispatch_hermes_job_command(
        "run a buy_the_dip backtest for AAPL over 1 month",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes backtest queued" in reply
    assert "`job-1`" in reply
    assert "You may leave this page" in reply


def test_durable_dispatch_precedes_remote_hermes_runtime():
    from engine.web import ph_chat

    source = inspect.getsource(ph_chat._stream)
    assert source.index("_dispatch_hermes_job_command") < source.index("get_runtime")


def test_worker_uses_owned_orchestrator_and_creates_candidate(monkeypatch):
    from agents import orchestrator as orchestrator_module
    from engine.agents import hermes_jobs

    seen = {}

    class FakeState:
        run_id = None

    class FakeOrchestrator:
        def __init__(self, user_id=None, account_id=None):
            seen.update(user_id=user_id, account_id=account_id)
            self.run_id = "generated"
            self.state = FakeState()

        def run_backtest(self, config):
            seen["run_id"] = self.run_id
            seen["config"] = config
            return {"run_id": self.run_id, "total_variations": 2,
                    "best_config": {"params": {"dip_threshold": 0.03},
                                    "sharpe_ratio": 2.5}}

    monkeypatch.setattr(orchestrator_module, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(hermes_jobs, "_save_candidate", lambda job, result: "candidate-1")
    job = {
        "job_id": "33333333-3333-3333-3333-333333333333",
        "run_id": "44444444-4444-4444-4444-444444444444",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "account_id": None, "config": {"strategy": "buy_the_dip"},
    }
    result, candidate_id, message = hermes_jobs._backtest(job)

    assert seen["user_id"] == job["user_id"]
    assert seen["run_id"] == job["run_id"]
    assert seen["config"]["agent_framework"] == "hermes"
    assert result["best_config"]["sharpe_ratio"] == 2.5
    assert candidate_id == "candidate-1"
    assert "Hermes backtest completed" in message


def test_worker_never_replays_interrupted_paper_jobs():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.recover_stale)
    assert "kind = 'backtest'" in source
    assert "status = 'queued'" in source
    assert "kind = 'paper'" in source
    assert "not replayed to avoid duplicate orders" in source


def test_async_job_schema_and_worker_are_alpatrade_scoped():
    migration = Path("sql/19_hermes_jobs.sql").read_text(encoding="utf-8")
    worker = Path("engine/agents/hermes_jobs.py").read_text(encoding="utf-8")
    assert "alpatrade.hermes_jobs" in migration
    assert "CREATE SCHEMA" not in migration.upper()
    assert "alpatrade.hermes_jobs" in worker
    assert "public." not in worker.lower()


def test_compose_keeps_executor_credentials_out_of_hermes_model_service():
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    hermes_model = compose.split("\n  api:", 1)[0]
    assert "DATABASE_URL=" not in hermes_model
    assert "ALPACA_PAPER_API_KEY=" not in hermes_model
    assert "hermes-jobs:" in compose
    jobs = compose.split("\n  hermes-jobs:", 1)[1].split("\n  agui:", 1)[0]
    assert "engine.agents.hermes_jobs" in jobs
