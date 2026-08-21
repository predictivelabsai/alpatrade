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


def test_candidate_paper_endpoint_uses_owned_helper(monkeypatch):
    from api_app import hermes_candidate_paper
    from api_models import HermesPaperRequest
    from engine.agents import hermes_jobs

    captured = {}

    def fake_start(candidate_id, user_id, thread_id, **kwargs):
        captured.update(candidate_id=candidate_id, user_id=user_id,
                        thread_id=thread_id, **kwargs)
        return {"job_id": "job", "run_id": "run", "status": "queued"}

    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", fake_start)
    user = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "thread_id": "22222222-2222-2222-2222-222222222222",
    }
    result = asyncio.run(hermes_candidate_paper(
        "55555555-5555-5555-5555-555555555555",
        HermesPaperRequest(duration="30d", poll=90, email=True),
        user,
    ))
    assert result["status"] == "queued"
    assert captured["user_id"] == user["user_id"]
    assert captured["duration"] == "30d"
    assert captured["email_reports"] is True


def test_paper_control_api_forwards_delegated_owner(monkeypatch):
    from api_app import _hermes_paper_control
    from engine.agents import hermes_jobs

    captured = {}
    monkeypatch.setattr(hermes_jobs, "request_control", lambda job_id, user_id, action: (
        captured.update(job_id=job_id, user_id=user_id, action=action)
        or {"job_id": job_id, "status": "paused"}
    ))
    user = {"user_id": "11111111-1111-1111-1111-111111111111"}
    result = asyncio.run(_hermes_paper_control("job-id", "pause", user))
    assert result["status"] == "paused"
    assert captured == {"job_id": "job-id", "user_id": user["user_id"], "action": "pause"}


def test_chat_dispatch_parses_background_backtest_without_remote_model():
    from engine.web.ph_chat import _hermes_backtest_config

    config = _hermes_backtest_config(
        "start a background buy_the_dip backtest for AAPL, MSFT, GOOGL, AMZN, "
        "META, TSLA and NVDA over the last 3 months; maximize Sharpe"
    )
    assert config["strategy"] == "buy_the_dip"
    assert config["lookback"] == "3m"
    assert config["symbols"] == ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]


def test_chat_result_question_does_not_queue_another_backtest():
    from engine.web.ph_chat import _hermes_backtest_config

    assert _hermes_backtest_config(
        "show me result of this backtest and params used and the period of data"
    ) is None


def test_chat_result_question_returns_latest_completed_job(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "list_owned", lambda *args, **kwargs: [{
        "job_id": "33333333-3333-3333-3333-333333333333",
        "run_id": "44444444-4444-4444-4444-444444444444",
        "candidate_id": "55555555-5555-5555-5555-555555555555",
        "kind": "backtest", "status": "completed",
        "config": {"strategy": "buy_the_dip", "lookback": "3m", "symbols": ["AAPL"]},
        "result": {"best_config": {"params": {"dip_threshold": 0.03},
                                    "sharpe_ratio": 2.5, "total_trades": 10}},
    }])
    reply = asyncio.run(_dispatch_hermes_job_command(
        "show me result of this backtest and params used and the period of data",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes backtest result" in reply
    assert "Data period:** `3m`" in reply
    assert "dip_threshold" in reply


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


def test_chat_dispatch_starts_owned_candidate_in_paper(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}

    def fake_start(candidate_id, user_id, thread_id, **kwargs):
        captured.update(candidate_id=candidate_id, user_id=user_id,
                        thread_id=thread_id, **kwargs)
        return {
            "job_id": "job-paper", "run_id": "run-paper", "status": "queued",
            "candidate_id": candidate_id,
        }

    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", fake_start)
    candidate_id = "55555555-5555-5555-5555-555555555555"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"start candidate {candidate_id} in continuous paper trading and email daily reports",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes paper trading queued" in reply
    assert captured["duration"] == "365d"
    assert captured["email_reports"] is True
    assert captured["poll"] == 60


def test_chat_dispatch_selects_highest_sharpe_candidate(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "list_owned", lambda *args, **kwargs: [
        {"kind": "backtest", "status": "completed", "candidate_id": "candidate-low",
         "result": {"best_config": {"sharpe_ratio": 1.2}}},
        {"kind": "backtest", "status": "completed", "candidate_id": "candidate-best",
         "result": {"best_config": {"sharpe_ratio": 4.8}}},
    ])
    captured = {}

    def fake_start(candidate_id, *args, **kwargs):
        captured["candidate_id"] = candidate_id
        return {"job_id": "job", "run_id": "run", "candidate_id": candidate_id,
                "status": "queued"}

    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", fake_start)
    reply = asyncio.run(_dispatch_hermes_job_command(
        "start my best candidate in continuous paper trading",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "paper trading queued" in reply
    assert captured["candidate_id"] == "candidate-best"


def test_paper_advice_question_does_not_authorize_a_trade(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", lambda *args, **kwargs: (
        (_ for _ in ()).throw(AssertionError("advice must not enqueue paper trading"))
    ))
    reply = asyncio.run(_dispatch_hermes_job_command(
        "what are the best params to use to run paper trading continuously?",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert reply is None


def test_chat_dispatch_controls_only_owned_paper_job(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}

    def fake_control(job_id, user_id, action):
        captured.update(job_id=job_id, user_id=user_id, action=action)
        return {"job_id": job_id, "run_id": "run-paper", "candidate_id": "candidate", "status": "paused"}

    monkeypatch.setattr(hermes_jobs, "request_control", fake_control)
    job_id = "66666666-6666-6666-6666-666666666666"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"pause paper job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "paper job paused" in reply
    assert captured["action"] == "pause"


def test_chat_dispatch_updates_owned_paper_email_schedule(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "set_email_reports", lambda *args: {
        "job_id": args[0], "status": "running",
    })
    job_id = "66666666-6666-6666-6666-666666666666"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"enable daily email reports for paper job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "enabled daily for your login email" in reply


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


def test_worker_requeues_only_explicitly_continuous_paper_jobs():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.recover_stale)
    assert "kind = 'backtest'" in source
    assert "status = 'queued'" in source
    assert "config->>'continuous'" in source
    assert "Continuous paper job requeued" in source
    assert "not replayed to avoid duplicate orders" in source


def test_paper_wait_obeys_durable_stop_without_sleeping_full_poll(monkeypatch):
    from agents.paper_trade_agent import PaperTradeAgent

    class Control:
        def wait_if_paused(self):
            return True

        def is_set(self):
            return True

    assert PaperTradeAgent._interruptible_wait(300, Control()) is True


def test_orchestrator_preserves_candidate_position_size():
    source = inspect.getsource(__import__("agents.orchestrator", fromlist=["Orchestrator"]).Orchestrator.run_paper_trade)
    assert '"position_size": params.get("position_size")' in source
    paper_source = inspect.getsource(
        __import__("agents.paper_trade_agent", fromlist=["PaperTradeAgent"]).PaperTradeAgent.run
    )
    assert "equity * fraction" in paper_source
    assert "fraction <= 0.25" in paper_source


def test_async_job_schema_and_worker_are_alpatrade_scoped():
    migration = Path("sql/19_hermes_jobs.sql").read_text(encoding="utf-8")
    worker = Path("engine/agents/hermes_jobs.py").read_text(encoding="utf-8")
    assert "alpatrade.hermes_jobs" in migration
    assert "CREATE SCHEMA" not in migration.upper()
    assert "alpatrade.hermes_jobs" in worker
    assert "public." not in worker.lower()
    controls = Path("sql/20_hermes_paper_controls.sql").read_text(encoding="utf-8")
    assert "alpatrade.hermes_jobs" in controls
    assert "control_requested" in controls
    assert "'paused'" in controls and "'stopped'" in controls


def test_compose_keeps_executor_credentials_out_of_hermes_model_service():
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    hermes_model = compose.split("\n  api:", 1)[0]
    assert "DATABASE_URL=" not in hermes_model
    assert "ALPACA_PAPER_API_KEY=" not in hermes_model
    assert "hermes-jobs:" in compose
    jobs = compose.split("\n  hermes-jobs:", 1)[1].split("\n  agui:", 1)[0]
    assert "engine.agents.hermes_jobs" in jobs


def test_voice_advertises_authenticated_hermes_command_tool():
    from engine import voice

    names = {tool.get("name") for tool in voice.TOOLS}
    assert "hermes_command" in names
    assert "Never claim" in voice.INSTRUCTIONS
    source = inspect.getsource(voice._voice_ws)
    assert 'session.get("user_id")' in source
    assert "sign in before using voice" in source


def test_daily_report_uses_explicit_owned_recipient(monkeypatch):
    from utils import email_util

    captured = {}
    monkeypatch.setattr(email_util, "send_email_to", lambda to, subject, html: (
        captured.update(to=to, subject=subject) or True
    ))
    monkeypatch.setattr(email_util, "send_email", lambda *args: (_ for _ in ()).throw(
        AssertionError("global recipient must not be used")
    ))
    assert email_util.send_daily_pnl_report(
        date="2026-08-21", pnl=1.0, positions=[], trades=[],
        to_email="owner@example.com",
    ) is True
    assert captured["to"] == "owner@example.com"


def test_hermes_job_config_does_not_duplicate_login_email():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.enqueue_candidate_paper)
    assert '"report_email": report_email' not in source
    target_source = inspect.getsource(hermes_jobs.DatabaseJobControl.report_target)
    assert "JOIN alpatrade.users u ON u.user_id = j.user_id" in target_source
