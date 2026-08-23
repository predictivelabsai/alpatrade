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
    assert captured["notification_channel"] == "in_app"


def test_candidate_paper_endpoint_forwards_both_notification_channel(monkeypatch):
    from api_app import hermes_candidate_paper
    from api_models import HermesPaperRequest
    from engine.agents import hermes_jobs

    captured = {}
    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", lambda *args, **kwargs: (
        captured.update(kwargs) or {"job_id": "job", "run_id": "run", "status": "queued"}
    ))
    asyncio.run(hermes_candidate_paper(
        "55555555-5555-5555-5555-555555555555",
        HermesPaperRequest(notification_channel="both"),
        {"user_id": "11111111-1111-1111-1111-111111111111",
         "thread_id": "22222222-2222-2222-2222-222222222222"},
    ))
    assert captured["notification_channel"] == "both"


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


def test_chat_dispatch_parses_compact_lookback_parameter():
    from engine.web.ph_chat import _hermes_backtest_config

    colon = _hermes_backtest_config(
        "backtest lookback:6m symbols:AAPL,MSFT objective:sharpe_ratio"
    )
    equals = _hermes_backtest_config(
        "run backtest lookback=1y symbols:AAPL objective:sharpe_ratio"
    )
    assert colon["lookback"] == "6m"
    assert equals["lookback"] == "1y"


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


def test_combined_start_and_notify_both_routes_to_paper_start(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}

    def fake_start(candidate_id, *args, **kwargs):
        captured.update(candidate_id=candidate_id, **kwargs)
        return {
            "job_id": "job", "run_id": "run", "candidate_id": candidate_id,
            "status": "queued",
        }

    monkeypatch.setattr(hermes_jobs, "enqueue_candidate_paper", fake_start)
    candidate_id = "55555555-5555-5555-5555-555555555555"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"start candidate {candidate_id} in continuous paper trading and "
        "email daily reports and notify me both",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes paper trading queued" in reply
    assert captured["email_reports"] is True
    assert captured["notification_channel"] == "both"


def test_chat_dispatch_selects_highest_sharpe_candidate(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_jobs, "list_owned", lambda *args, **kwargs: [
        {"kind": "backtest", "status": "completed", "candidate_id": "candidate-low",
         "result": {"best_config": {"sharpe_ratio": 1.2, "promotion_eligible": True}}},
        {"kind": "backtest", "status": "completed", "candidate_id": "candidate-best",
         "result": {"best_config": {"sharpe_ratio": 4.8, "promotion_eligible": True}}},
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


def test_hermes_help_is_deterministic_and_paper_only():
    from engine.web.ph_chat import _dispatch_hermes_job_command

    reply = asyncio.run(_dispatch_hermes_job_command(
        "help", "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes commands" in reply
    assert "construct a portfolio" in reply
    assert "notify me in app|by email|both" in reply
    assert "paper-only" in reply


def test_chat_constructs_owned_portfolio_advice(monkeypatch):
    from engine.agents import hermes_advice
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_advice, "construct_portfolio", lambda *args: {
        "advice_id": "advice-1",
        "snapshot": {"allocations": {"AAPL": 0.25, "MSFT": 0.25},
                     "cash_reserve": 0.5, "entry": {"dip_threshold_pct": 3},
                     "exit": {"take_profit_pct": 1.5},
                     "construction_method": "inverse_120d_volatility"},
        "rationale": "Paper advice only.",
    })
    candidate = "55555555-5555-5555-5555-555555555555"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"construct an optimal portfolio from candidate {candidate}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes portfolio recommendation" in reply
    assert "AAPL 25.0%" in reply
    assert "Paper advice only" in reply


def test_chat_updates_owned_notification_channel(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}
    monkeypatch.setattr(hermes_jobs, "set_notification_channel", lambda *args: (
        captured.update(job_id=args[0], user_id=args[1], channel=args[2]) or
        {"job_id": args[0]}
    ))
    job_id = "66666666-6666-6666-6666-666666666666"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"notify me both in app and email for paper job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert captured["channel"] == "both"
    assert captured["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert "Delivery:** `both`" in reply


def test_position_advice_uses_approved_entry_exit_thresholds():
    from engine.agents.hermes_advice import position_advice

    items = position_advice(
        [{"symbol": "AAPL", "unrealized_plpc": "0.016"},
         {"symbol": "MSFT", "unrealized_plpc": "-0.006"}],
        ["AAPL", "MSFT", "NVDA"],
        {"take_profit_threshold": 1.5, "stop_loss_threshold": 0.5,
         "dip_threshold": 3.0},
    )
    by_symbol = {item["symbol"]: item for item in items}
    assert by_symbol["AAPL"]["action"] == "EXIT"
    assert by_symbol["MSFT"]["action"] == "EXIT"
    assert by_symbol["NVDA"]["action"] == "WATCH_ENTRY"
    assert all("order" not in item for item in items)


def test_trade_advice_reports_confirmed_paper_entry_without_ordering():
    from agents.paper_trade_agent import PaperTradeAgent

    items = PaperTradeAgent._trade_advice([
        {"symbol": "AAPL", "side": "buy", "dip_pct": 3.2, "qty": 2}
    ], {"dip_threshold": 3.0})
    assert items[0]["action"] == "ENTRY_EXECUTED"
    assert "3.20%" in items[0]["rationale"]
    assert items[0]["snapshot"]["dip_threshold_pct"] == 3.0
    assert "client" not in inspect.getsource(PaperTradeAgent._trade_advice)


def test_advice_email_html_escapes_model_or_market_text():
    from engine.agents.hermes_advice import advice_email_html

    body = advice_email_html([{"summary": "AAPL <EXIT>",
                               "rationale": "price & risk"}])
    assert "&lt;EXIT&gt;" in body
    assert "price &amp; risk" in body


def test_hermes_daily_report_reconciles_loss_and_groups_fills():
    from engine.agents.hermes_advice import build_performance_report

    trades = [
        {"symbol": "AAPL", "side": "buy", "qty": 4, "price": 311.30,
         "timestamp": "2026-08-21T10:00:00+00:00"},
        {"symbol": "AAPL", "side": "buy", "qty": 3, "price": 310.30,
         "timestamp": "2026-08-21T10:05:00+00:00"},
        {"symbol": "AAPL", "side": "sell", "qty": 7, "exit_price": 309.0,
         "exit_time": "2026-08-21T15:00:00+00:00", "pnl": -665.87,
         "reason": "STOP_LOSS (-0.82%)"},
        {"symbol": "AMZN", "side": "sell", "qty": 5, "exit_price": 259.0,
         "exit_time": "2026-08-21T15:05:00+00:00", "pnl": -411.88,
         "reason": "STOP_LOSS (-0.56%)"},
        {"symbol": "NVDA", "side": "sell", "qty": 5, "exit_price": 217.0,
         "exit_time": "2026-08-21T15:10:00+00:00", "pnl": -374.93,
         "reason": "STOP_LOSS (-0.51%)"},
    ]
    report = build_performance_report(
        date="2026-08-21", positions=[], trades=trades, advice=[],
        job_id="job-1", run_id="run-1", candidate_id="candidate-1",
    )
    assert report["realized_today"] == -1452.68
    assert report["realized_session"] == -1452.68
    assert report["status"] == "RED"
    assert report["win_rate"] == 0.0
    assert report["validated"] is True
    assert report["grouped_entries"][0]["fills"] == 2
    assert report["grouped_entries"][0]["quantity"] == 7
    assert "pause paper job job-1" in report["commands"][0]


def test_hermes_green_report_explains_gain_and_keeps_strategy():
    from engine.agents.hermes_advice import build_performance_report

    report = build_performance_report(
        date="2026-08-21",
        positions=[{"symbol": "AAPL", "unrealized_pl": 25}],
        trades=[{"symbol": "MSFT", "side": "sell", "exit_price": 102,
                 "exit_time": "2026-08-21T15:00:00+00:00", "pnl": 50,
                 "reason": "TAKE_PROFIT"}],
        advice=[], job_id="job-1", run_id="run-1", candidate_id="candidate-1",
    )
    assert report["status"] == "GREEN"
    assert report["realized_today"] == 50
    assert "Keep the approved configuration" in report["decision"]
    assert any("AAPL" in reason for reason in report["reasons"])
    assert any("without changing my running paper job" in command
               for command in report["commands"])


def test_immediate_alert_has_reason_context_and_loss_color():
    from engine.agents.hermes_advice import build_advice_alert_email

    subject, body = build_advice_alert_email([{
        "summary": "NVDA: EXIT_EXECUTED", "action": "EXIT_EXECUTED",
        "rationale": "Approved stop loss crossed.",
        "snapshot": {"pnl": -374.93, "reason": "STOP_LOSS"},
    }], {"job_id": "job-1", "run_id": "run-1", "candidate_id": "candidate-1"})
    assert "RED" in subject
    assert "-$374.93" in body
    assert "#c53b3b" in body
    assert "Approved stop loss crossed" in body
    assert "job-1" in body and "run-1" in body and "candidate-1" in body


def test_hermes_daily_email_uses_one_report_and_red_loss(monkeypatch):
    from utils import email_util

    captured = {}
    monkeypatch.setattr(email_util, "send_email_to", lambda to, subject, body: (
        captured.update(to=to, subject=subject, body=body) or True
    ))
    report = {
        "date": "2026-08-21", "status": "RED", "status_color": "#c53b3b",
        "decision": "Pause and review.", "reasons": ["Three stop-loss exits."],
        "realized_today": -1452.68, "realized_session": -1452.68,
        "unrealized": 100.0, "combined_current": -1352.68,
        "completed_exits": 3, "wins": 0, "losses": 3, "win_rate": 0,
        "positions": [], "closed_today": [], "grouped_entries": [], "advice": [],
        "commands": ["/hermes pause paper job job-1"],
        "job_id": "job-1", "run_id": "run-1", "candidate_id": "candidate-1",
    }
    assert email_util.send_hermes_daily_report(
        report, account_name="Raslen", user_name="raslen",
        to_email="owner@example.com",
    )
    assert "-$1,452.68 realized" in captured["subject"]
    assert "#c53b3b" in captured["body"]
    assert "-$1,452.68" in captured["body"]
    assert "/hermes pause paper job job-1" in captured["body"]
    assert captured["to"] == "owner@example.com"


def test_chat_analyzes_only_owned_paper_job(monkeypatch):
    from engine.agents import hermes_advice
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}
    monkeypatch.setattr(hermes_advice, "analyze_owned_paper_job", lambda job, user: (
        captured.update(job=job, user=user) or {
            "status": "RED", "job_id": job, "job_status": "running",
            "run_id": "run-1", "realized_today": -10, "realized_session": -10,
            "completed_exits": 1, "win_rate": 0, "active_duplicate_jobs": 0,
            "other_active_account_runs": 0,
            "reasons": ["Loss detected."], "decision": "Pause and review.",
            "commands": [f"/hermes pause paper job {job}"],
        }
    ))
    job_id = "66666666-6666-6666-6666-666666666666"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"analyze paper job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert captured["user"] == "11111111-1111-1111-1111-111111111111"
    assert "Hermes paper analysis" in reply
    assert "Loss detected" in reply
    assert "No parameters or orders were changed automatically" in reply


def test_portfolio_risk_weights_fall_back_without_complete_market_data(monkeypatch):
    from engine.agents import hermes_advice

    monkeypatch.setattr(
        "engine.feeds.market_data.get_historical_data", lambda *args, **kwargs: None
    )
    weights, method = hermes_advice._risk_weights(["AAPL", "MSFT"], 0.5, 0.25)
    assert weights == {"AAPL": 0.25, "MSFT": 0.25}
    assert method == "capped_equal_weight"


def test_default_agent_does_not_enable_hermes_advice():
    from agents.orchestrator import Orchestrator

    source = inspect.getsource(Orchestrator.run_paper_trade)
    assert 'config.get("agent_framework") == "hermes"' in source
    assert 'else False' in source


def test_advice_channel_does_not_change_daily_report_schedule():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.set_notification_channel)
    assert '"notification_channel": channel' in source
    assert '"email_notifications"' not in source


def test_running_paper_agent_refreshes_advice_preferences():
    from agents.paper_trade_agent import PaperTradeAgent

    source = inspect.getsource(PaperTradeAgent.run)
    assert 'stop_event.advice_settings()' in source
    assert 'live_advice.get("enabled"' in source


def test_hermes_daily_report_loads_durable_owned_run_trades():
    from agents.paper_trade_agent import PaperTradeAgent

    source = inspect.getsource(PaperTradeAgent._send_daily_email)
    assert "fetch_paper_trades" in source


def test_daily_email_keeps_default_and_hermes_templates_separate():
    """Hermes reporting must not replace the established default-agent email."""
    import inspect
    from agents.paper_trade_agent import PaperTradeAgent

    source = inspect.getsource(PaperTradeAgent._send_daily_email)
    assert 'if report_format != "hermes"' in source
    assert "send_daily_pnl_report" in source
    assert "send_hermes_daily_report" in source
    assert "user_id=self.user_id" in source


def test_analysis_checks_all_account_paper_runs_not_only_hermes():
    from engine.agents import hermes_advice

    source = inspect.getsource(hermes_advice.analyze_owned_paper_job)
    assert "FROM alpatrade.runs" in source
    assert "mode = 'paper'" in source
    assert "other_active_account_runs" in source


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


def test_worker_finalizes_orphaned_stop_request():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.recover_stale)
    assert "control_requested = 'stop'" in source
    assert "status = 'stopped'" in source
    assert "INTERVAL '30 seconds'" in source


def test_completed_worker_releases_claim():
    from engine.agents import hermes_jobs

    assert "claimed_by = NULL" in inspect.getsource(hermes_jobs.finish)
    assert "claimed_by = NULL" in inspect.getsource(hermes_jobs.fail)


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
    advice = Path("sql/21_hermes_portfolio_advice.sql").read_text(encoding="utf-8")
    assert "alpatrade.hermes_advice" in advice
    assert "REFERENCES alpatrade.users" in advice
    assert "CREATE SCHEMA" not in advice.upper()


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


def test_daily_report_includes_hermes_advice(monkeypatch):
    from utils import email_util

    captured = {}
    monkeypatch.setattr(email_util, "send_email_to", lambda to, subject, body: (
        captured.update(to=to, body=body) or True
    ))
    assert email_util.send_daily_pnl_report(
        date="2026-08-21", pnl=1.0, positions=[], trades=[],
        to_email="owner@example.com",
        agent_advice=[{"summary": "AAPL: WATCH_EXIT",
                       "rationale": "Near take-profit."}],
    )
    assert "Hermes Agent Advice" in captured["body"]
    assert "AAPL: WATCH_EXIT" in captured["body"]


def test_hermes_job_config_does_not_duplicate_login_email():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.enqueue_candidate_paper)
    assert '"report_email": report_email' not in source
    target_source = inspect.getsource(hermes_jobs.DatabaseJobControl.report_target)
    assert "JOIN alpatrade.users u ON u.user_id = j.user_id" in target_source


def test_backtest_result_request_is_not_routed_to_jobs_list(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    job_id = "66666666-6666-6666-6666-666666666666"
    monkeypatch.setattr(hermes_jobs, "list_owned", lambda *args, **kwargs: [{
        "job_id": job_id, "run_id": "run-1", "kind": "backtest",
        "status": "completed", "candidate_id": "candidate-1",
        "config": {"strategy": "buy_the_dip", "lookback": "1y", "symbols": ["SPY"]},
        "result": {"best_config": {
            "params": {"dip_threshold": 0.05}, "sharpe_ratio": 1.8,
            "validation_metrics": {"sharpe_ratio": 2.0},
            "benchmark": {"symbol": "SPY", "excess_return": 0.4},
            "robustness_windows": [{"total_return": 0.2}],
            "promotion_eligible": True,
        }},
    }])
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"show result for backtest job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "Hermes backtest result" in reply
    assert "Hermes jobs" not in reply
    assert "excess_return" in reply
    assert "Robustness windows" in reply


def test_notification_history_shows_delivery_channels(monkeypatch):
    from engine.agents import hermes_advice
    from engine.web.ph_chat import _dispatch_hermes_job_command

    monkeypatch.setattr(hermes_advice, "list_owned", lambda *args, **kwargs: [{
        "summary": "Hermes notification test", "delivered_in_app": True,
        "delivered_email": False, "created_at": "2026-08-23T00:00:00Z",
    }])
    reply = asyncio.run(_dispatch_hermes_job_command(
        "show my notification history",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert "notification history" in reply
    assert "in-app: `delivered`" in reply
    assert "email: `not delivered`" in reply


def test_notification_test_routes_to_owned_job(monkeypatch):
    from engine.agents import hermes_jobs
    from engine.web.ph_chat import _dispatch_hermes_job_command

    captured = {}
    monkeypatch.setattr(hermes_jobs, "send_test_notification", lambda job, user, channel: (
        captured.update(job=job, user=user, channel=channel) or
        {"job_id": job, "in_app": True, "email": True}
    ))
    job_id = "66666666-6666-6666-6666-666666666666"
    reply = asyncio.run(_dispatch_hermes_job_command(
        f"send a test notification both in app and email for paper job {job_id}",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ))
    assert captured["channel"] == "both"
    assert captured["user"] == "11111111-1111-1111-1111-111111111111"
    assert "In-app:** `delivered`" in reply
    assert "Email:** `delivered`" in reply


def test_drift_guard_waits_for_evidence_then_detects_degradation():
    from engine.agents.hermes_advice import assess_performance_drift

    insufficient = assess_performance_drift(
        2.0, [{"pnl_pct": -1.0, "exit_time": f"2026-08-{i % 4 + 1:02d}"}
              for i in range(19)], minimum_exits=20
    )
    returns = [1.0, -2.0, 0.5, -1.5, 0.25] * 4
    degraded = assess_performance_drift(
        2.0,
        [{"pnl_pct": value, "exit_time": f"2026-08-{index % 5 + 1:02d}"}
         for index, value in enumerate(returns)],
        minimum_exits=20,
    )
    assert insufficient["drift"] is False
    assert insufficient["paper_sharpe"] is None
    assert degraded["drift"] is True
    assert degraded["threshold"] == 1.0
    assert degraded["observed_days"] == 5


def test_daily_report_reconciles_run_positions_against_broker():
    from engine.agents.hermes_advice import build_performance_report

    report = build_performance_report(
        date="2026-08-23",
        positions=[{"symbol": "SPY", "qty": 2, "unrealized_pl": 0}],
        trades=[{"symbol": "SPY", "direction": "buy", "shares": 3,
                 "entry_time": "2026-08-23T10:00:00Z"}],
        advice=[], job_id="job-1", run_id="run-1", candidate_id="candidate-1",
    )
    assert report["reconciliation"]["ok"] is False
    assert report["reconciliation"]["differences"][0]["difference"] == -1
    assert report["status"] == "RED"
    assert "reconcile" in report["decision"].lower()


def test_hermes_paper_config_enables_drift_guard_only_on_hermes_path():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.enqueue_candidate_paper)
    assert '"drift_guard_enabled": True' in source
    default_source = inspect.getsource(
        __import__("agents.orchestrator", fromlist=["Orchestrator"]).Orchestrator.run_paper_trade
    )
    assert "drift_guard_enabled" not in default_source
