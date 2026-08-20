"""DB-free coverage for the tenant-scoped daily trading advisor."""
from __future__ import annotations

from datetime import date, datetime, timezone
from contextlib import contextmanager
from html import escape
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from api_app import app, require_tenant_user
from engine.ai.deepagent_tools import (
    DeepAgentContext,
    get_latest_advisor_report,
    queue_advisor_backtest,
    queue_paper_from_backtest,
)
from engine.autonomy import schedule
from engine.reporting.advisor import (
    _database_evidence,
    AdvisorDraft,
    AdvisorSelection,
    AdvisorThresholds,
    canonical_backtest_grid,
    candidate_actions,
    classify_evidence,
    collect_evidence,
    consecutive_losing_sessions,
    finalize_advisory,
    generate_account_report,
    max_drawdown_pct,
    max_losing_streak,
    normalize_parameter,
    normalize_parameters,
    render_advisor_email,
    run_user_batch,
    select_latest_matching_backtest,
    stored_backtest_candidate_grid,
)

USER_ID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"
REPORT_ID = "33333333-3333-4333-8333-333333333333"
EASTERN = ZoneInfo("America/New_York")


def _evidence(**overrides):
    evidence = {
        "report_id": REPORT_ID,
        "session_date": "2026-08-19",
        "account": {
            "account_id": ACCOUNT_ID,
            "account_name": "Paper One",
            "paper_only": True,
        },
        "broker": {
            "available": True,
            "history_available": True,
            "positions_available": True,
            "daily_pnl": -10.0,
            "daily_pct": -0.1,
            "drawdown_20_pct": 1.0,
            "consecutive_losing_sessions": 1,
            "unrealized_pnl": -2.0,
        },
        "paper": {
            "closed_trades": 5,
            "session_realized_pnl": -8.0,
            "realized_pnl": 20.0,
            "sharpe": 1.0,
            "window_start": "2026-07-22",
            "window_end": "2026-08-19",
        },
        "backtest": {
            "available": True,
            "run_id": "bt-1",
            "sharpe": 1.5,
            "refined_grid": {"dip_threshold": [0.04, 0.05]},
        },
        "strategy": {
            "name": "buy_the_dip",
            "slug": "btd-5dp",
            "symbols": ["AAPL"],
            "lookback": "3m",
            "params_raw": {"dip_threshold": 0.05},
        },
        "regime": {"state": "normal", "preset_raw": {}},
        "risk": {"breaches": [], "gross_exposure_pct": 25.0},
        "quality": {"warnings": []},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(evidence.get(key), dict):
            evidence[key] = {**evidence[key], **value}
        else:
            evidence[key] = value
    severity, triggers = classify_evidence(evidence)
    evidence["severity"] = severity
    evidence["triggers"] = triggers
    return evidence


def _record(account_name="Paper One", report_id=REPORT_ID):
    evidence = _evidence()
    evidence["account"]["account_name"] = account_name
    evidence["report_id"] = report_id
    advisory = finalize_advisory(
        evidence, candidate_actions(evidence, evidence["severity"]), None,
        AdvisorThresholds(),
    )
    return {
        "report_id": report_id,
        "user_id": USER_ID,
        "account_id": ACCOUNT_ID,
        "session_date": "2026-08-19",
        "status": "partial",
        "severity": evidence["severity"],
        "evidence": evidence,
        "advisory": advisory,
        "narrative": advisory["summary"],
        "model_provider": None,
        "model_name": None,
        "error_code": "model_unavailable",
        "created_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
    }


def test_parameter_units_are_normalized_without_turning_half_percent_into_fifty():
    assert normalize_parameter("dip_threshold", 0.05) == 5.0
    assert normalize_parameter("dip_threshold", 5) == 5.0
    assert normalize_parameter("take_profit", 0.01) == 1.0
    assert normalize_parameter("vol_target", 0.12) == 12.0
    assert normalize_parameter("stop_loss_threshold", 0.5) == 0.5
    assert canonical_backtest_grid({
        "dip_threshold": 5,
        "take_profit_threshold": 1,
        "stop_loss_threshold": 0.5,
        "hold_days": 2,
        "capital_per_trade": 1000,
    }) == {
        "dip_threshold": [0.05],
        "take_profit": [0.01],
        "stop_loss": [0.005],
        "hold_days": [2],
    }
    assert normalize_parameters(
        {"dip_threshold": 0.5}, paper_percent=True
    ) == {"dip_threshold": 0.5}
    assert canonical_backtest_grid(
        {"dip_threshold": 0.5}, paper_percent=True
    ) == {"dip_threshold": [0.005]}


def test_standalone_paper_run_persists_resolved_params_and_exact_slug(monkeypatch):
    from agents.orchestrator import Orchestrator

    observed = {}

    class AgentState:
        iteration_count = 0

        def set_running(self, _task):
            pass

        def set_completed(self):
            pass

        def set_error(self, _error):
            pass

    class PaperTrader:
        def run(self, request, stop_event=None, run_id=None):
            observed["request"] = request
            observed["run_id"] = run_id
            return {"total_trades": 0, "total_pnl": 0.0}

    state = SimpleNamespace(
        mode=None,
        best_config={
            "params": {
                "dip_threshold": 0.05,
                "take_profit": 0.01,
                "stop_loss": 0.005,
                "hold_days": 2,
                "min_hold_days": 3,
                "symbols": ["AAPL"],
            },
        },
        paper_trade_session=None,
        save=lambda: None,
        get_agent=lambda _name: AgentState(),
    )
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.user_id = None
    orchestrator.account_id = None
    orchestrator.run_id = "paper-run"
    orchestrator._mode = None
    orchestrator._config = None
    orchestrator.state = state
    orchestrator.paper_trader = PaperTrader()
    orchestrator.bus = SimpleNamespace(publish=lambda **_kwargs: None)

    monkeypatch.setattr(
        "agents.orchestrator.load_parameters",
        lambda: {
            "buy_the_dip": {"capital_per_trade": 1000},
            "general": {"polling_interval": 300},
        },
    )

    def store_run(*args, **kwargs):
        observed["stored_args"] = args
        observed["stored"] = kwargs

    monkeypatch.setattr("agents.orchestrator.store_run", store_run)
    monkeypatch.setattr("agents.orchestrator.update_run", lambda *_args, **_kwargs: None)

    orchestrator.run_paper_trade({
        "strategy": "buy_the_dip",
        "lookback": "3m",
        "approved_best_config": state.best_config,
    })

    assert observed["request"]["params"] == {
        "dip_threshold": 5.0,
        "take_profit_threshold": 1.0,
        "stop_loss_threshold": 0.5,
        "hold_days": 2,
        "min_hold_days": 3,
        "capital_per_trade": 1000,
    }
    assert observed["stored"]["config"]["params"] == observed["request"]["params"]
    assert observed["stored"]["strategy_slug"] == "btd-5dp-05sl-1tp-2d-3min-3m"


def test_fixed_paper_service_can_bind_runs_and_trades_to_an_owned_account(monkeypatch):
    from scripts import run_paper_strategy

    observed = {}
    monkeypatch.setenv("PAPER_USER_ID", USER_ID)
    monkeypatch.setenv("PAPER_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("PAPER_DURATION_SECONDS", "0")
    monkeypatch.setattr(
        "engine.auth.get_alpaca_keys", lambda *_args: ("owned-key", "owned-secret")
    )
    monkeypatch.setattr(
        "engine.auth.get_user_accounts",
        lambda *_args: [{"account_id": ACCOUNT_ID, "account_name": "Paper One"}],
    )

    def store_run(*_args, **kwargs):
        observed["stored"] = kwargs

    class PaperAgent:
        def __init__(self, **kwargs):
            observed["agent"] = kwargs

        def run(self, _request, run_id=None):
            observed["run_id"] = run_id
            return {"session_id": run_id, "total_trades": 0}

    monkeypatch.setattr("utils.agent_storage.store_run", store_run)
    monkeypatch.setattr("agents.paper_trade_agent.PaperTradeAgent", PaperAgent)

    assert run_paper_strategy.main() == 0
    assert observed["stored"]["user_id"] == USER_ID
    assert observed["stored"]["account_id"] == ACCOUNT_ID
    assert observed["agent"]["user_id"] == USER_ID
    assert observed["agent"]["account_id"] == ACCOUNT_ID
    assert observed["agent"]["alpaca_api_key"] == "owned-key"


def test_loss_classification_follows_deterministic_precedence():
    insufficient = _evidence(paper={"closed_trades": 4, "session_realized_pnl": -50})
    assert insufficient["severity"] == "insufficient_data"

    monitor = _evidence()
    assert monitor["severity"] == "monitor"
    assert monitor["triggers"]["loss_detected"] is True

    drift = _evidence(paper={
        "closed_trades": 5, "session_realized_pnl": -10, "sharpe": 0.2,
    })
    assert drift["severity"] == "review"

    streak = _evidence(broker={
        "daily_pct": -0.5, "drawdown_20_pct": 2,
        "consecutive_losing_sessions": 3, "unrealized_pnl": 0,
    })
    assert streak["severity"] == "review"

    urgent = _evidence(
        paper={"closed_trades": 1, "session_realized_pnl": -100},
        broker={
            "daily_pct": -2.0, "drawdown_20_pct": 2,
            "consecutive_losing_sessions": 1, "unrealized_pnl": 0,
        },
    )
    assert urgent["severity"] == "urgent"


def test_profitable_and_no_trade_days_still_explain_why_parameters_stay_put():
    profitable = _evidence(
        broker={
            "daily_pct": 0.8, "daily_pnl": 80.0, "drawdown_20_pct": 0,
            "consecutive_losing_sessions": 0, "unrealized_pnl": 12.0,
        },
        paper={
            "closed_trades": 8, "session_realized_pnl": 25.0,
            "realized_pnl": 120.0, "sharpe": 1.2,
        },
    )
    profitable_advisory = finalize_advisory(
        profitable, candidate_actions(profitable, profitable["severity"]), None,
        AdvisorThresholds(),
    )
    assert profitable["severity"] == "monitor"
    assert profitable["triggers"]["loss_detected"] is False
    assert "remain unchanged" in profitable_advisory["why_no_change"]

    no_trades = _evidence(paper={
        "closed_trades": 0, "session_realized_pnl": 0.0,
        "realized_pnl": 0.0, "sharpe": None,
    })
    no_trade_advisory = finalize_advisory(
        no_trades, candidate_actions(no_trades, no_trades["severity"]), None,
        AdvisorThresholds(),
    )
    assert no_trades["severity"] == "insufficient_data"
    assert "only 0 closed paper trades" in no_trade_advisory["why_no_change"]


def test_five_percent_rolling_drawdown_triggers_review():
    evidence = _evidence(
        broker={
            "daily_pct": 0.1, "daily_pnl": 10.0, "drawdown_20_pct": 5.0,
            "consecutive_losing_sessions": 0, "unrealized_pnl": 0.0,
        },
    )

    assert evidence["severity"] == "review"


def test_sharpe_drift_uses_the_same_half_baseline_formula_for_negative_values():
    above_half = _evidence(
        paper={"closed_trades": 5, "session_realized_pnl": 0, "sharpe": -0.4},
        backtest={"available": True, "run_id": "bt-1", "sharpe": -1.0},
        broker={
            "daily_pct": 0.1, "daily_pnl": 10.0, "drawdown_20_pct": 0,
            "consecutive_losing_sessions": 0, "unrealized_pnl": 0.0,
        },
    )
    below_half = _evidence(
        paper={"closed_trades": 5, "session_realized_pnl": 0, "sharpe": -0.6},
        backtest={"available": True, "run_id": "bt-1", "sharpe": -1.0},
        broker={
            "daily_pct": 0.1, "daily_pnl": 10.0, "drawdown_20_pct": 0,
            "consecutive_losing_sessions": 0, "unrealized_pnl": 0.0,
        },
    )

    assert above_half["severity"] == "monitor"
    assert below_half["severity"] == "review"


def test_equity_drawdown_and_session_streak_metrics():
    assert max_drawdown_pct([100, 110, 99, 105]) == 10.0
    assert consecutive_losing_sessions([2, -1, -3, -4]) == 3
    assert consecutive_losing_sessions([-1, 0]) == 0
    assert max_losing_streak([-1, -2, 3, -4, -5, -6, 2]) == 3


def test_latest_backtest_selection_requires_the_exact_strategy_slug():
    candidates = [
        {"strategy_slug": "btd-7dp", "run_id": "new-wrong"},
        {"strategy_slug": "btd-5dp", "run_id": "new-exact"},
        {"strategy_slug": "btd-5dp", "run_id": "old-exact"},
    ]
    assert select_latest_matching_backtest("btd-5dp", candidates)["run_id"] == "new-exact"
    assert select_latest_matching_backtest("btd", candidates) is None


def test_stored_candidate_grid_never_creates_new_parameter_values():
    variations = [
        {
            "params": {"dip_threshold": 0.05, "take_profit": 0.01},
            "_score": 4.0,
        },
        {
            "params": {"dip_threshold": 0.07, "take_profit": 0.015},
            "_score": 3.0,
        },
    ]

    assert stored_backtest_candidate_grid(variations) == {
        "dip_threshold": [0.05, 0.07],
        "take_profit": [0.01, 0.015],
    }


def test_database_evidence_scopes_trades_to_exact_slug_and_counts_legacy_exit_reasons(
    monkeypatch,
):
    observed = {}
    when = datetime(2026, 8, 19, 20, tzinfo=timezone.utc)

    class Result:
        def __init__(self, *, one=None, all_rows=None):
            self.one = one
            self.all_rows = all_rows or []

        def fetchone(self):
            return self.one

        def fetchall(self):
            return self.all_rows

    class Session:
        def execute(self, statement, params):
            query = str(statement)
            if "SELECT run_id, strategy, strategy_slug" in query:
                return Result(one=(
                    "paper-run", "buy_the_dip", "btd-5dp", {
                        "params": {"dip_threshold": 5}, "symbols": ["AAPL"],
                    }, {}, "completed", when,
                ))
            if "SELECT t.run_id, t.symbol" in query:
                observed["trade_query"] = query
                observed["trade_params"] = params
                return Result(all_rows=[
                    ("paper-run", "AAPL", 10, 1.0, 0.2, "TAKE_PROFIT (1.00%)",
                     False, False, when, when),
                    ("paper-run", "MSFT", -5, -0.5, 0.1, "STOP_LOSS (-0.50%)",
                     False, False, when, when),
                ])
            if "SELECT r.run_id, bs.total_return" in query:
                return Result(all_rows=[])
            if "SELECT source, status, anomalies_found" in query:
                return Result(one=None)
            if "SELECT status, results, completed_at" in query:
                return Result(one=None)
            raise AssertionError(query)

    class Pool:
        @contextmanager
        def get_session(self):
            yield Session()

    monkeypatch.setattr("engine.reporting.advisor.DatabasePool", lambda: Pool())
    result = _database_evidence(
        USER_ID, ACCOUNT_ID, date(2026, 8, 19),
        [{"date": "2026-08-19", "equity": 10_000, "pnl": 5}],
    )

    assert "r.strategy_slug = :slug" in observed["trade_query"]
    assert observed["trade_params"]["slug"] == "btd-5dp"
    assert result["paper"]["trade_scope"] == "exact_strategy_slug"
    assert result["paper"]["target_exits"] == 1
    assert result["paper"]["stop_loss_exits"] == 1
    assert result["paper"]["total_fees"] == 0.3


def test_missing_broker_snapshot_is_explicitly_flagged_without_fabricating_a_loss(
    monkeypatch,
):
    monkeypatch.setattr(
        "engine.reporting.advisor._broker_evidence",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        "engine.reporting.advisor._database_evidence",
        lambda *_args: {
            "strategy": {
                "name": "buy_the_dip", "slug": "btd-5dp",
                "params_raw": {"dip_threshold": 0.05},
                "params_display": {"dip_threshold": 5.0},
                "symbols": ["AAPL"], "lookback": "3m",
                "grid_backtest_compatible": True,
                "unsupported_backtest_parameters": [],
            },
            "paper": {
                "trade_scope": "exact_strategy_slug", "strategy_slug": "btd-5dp",
                "window_start": "2026-06-20", "window_end": "2026-08-19",
                "closed_trades": 0, "session_realized_pnl": 0.0,
                "realized_pnl": 0.0, "sharpe": None,
            },
            "backtest": {"available": False, "sharpe": None},
            "validation": {"available": False},
            "reconciliation": {"available": False},
        },
    )
    monkeypatch.setattr(
        "engine.regime.classify_regime_cached",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    evidence = collect_evidence(
        REPORT_ID, USER_ID,
        {"account_id": ACCOUNT_ID, "account_name": "Paper One"},
        date(2026, 8, 19), AdvisorThresholds(),
    )

    assert evidence["broker"]["available"] is False
    assert evidence["severity"] == "insufficient_data"
    assert evidence["triggers"]["urgent_daily_loss"] is False
    assert evidence["attribution"]["broker_daily_pnl"] is None
    assert evidence["attribution"]["unattributed_residual"] is None
    assert any("broker snapshot was unavailable" in item
               for item in evidence["quality"]["warnings"])
    advisory = finalize_advisory(
        evidence, [], None, AdvisorThresholds(), fallback_reason="model_unavailable"
    )
    assert "Broker account P&L was unavailable" in advisory["summary"]


def test_candidate_values_come_from_stored_grid_and_fallback_explains_no_ai():
    evidence = _evidence(paper={
        "closed_trades": 5, "session_realized_pnl": -10, "sharpe": 0.2,
    })
    candidates = candidate_actions(evidence, evidence["severity"])

    assert candidates[0]["candidate_id"] == "retest-refined-grid"
    assert candidates[0]["test_config"]["variations"] == {
        "dip_threshold": [0.04, 0.05],
    }
    advisory = finalize_advisory(
        evidence, candidates, None, AdvisorThresholds()
    )
    assert advisory["ai_status"] == "unavailable"
    assert "deterministic fallback" in advisory["generation_note"]
    assert advisory["why_no_change"]
    assert advisory["approval_required"] is True


@pytest.mark.asyncio
async def test_model_unavailability_persists_a_deterministic_partial_report(monkeypatch):
    evidence = _evidence(paper={
        "closed_trades": 5, "session_realized_pnl": -10, "sharpe": 0.2,
    })
    saved = {}
    monkeypatch.setattr(
        "engine.reporting.advisor.reserve_report",
        lambda *_args: {
            "report_id": REPORT_ID, "account_id": ACCOUNT_ID,
            "status": "generating", "advisory": None,
        },
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.collect_evidence",
        lambda *_args: evidence,
    )

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("engine.reporting.advisor._deepagent_draft", unavailable)
    monkeypatch.setattr(
        "engine.reporting.advisor.save_report",
        lambda _report_id, **kwargs: saved.update(kwargs),
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.get_report_for_user", lambda *_args: None,
    )

    report = await generate_account_report(
        USER_ID, {"account_id": ACCOUNT_ID, "account_name": "Paper One"},
        date(2026, 8, 19),
    )

    assert report["status"] == "partial"
    assert saved["status"] == "partial"
    assert saved["error_code"] == "model_unavailable"
    assert saved["advisory"]["ai_status"] == "unavailable"
    assert "configured model was unavailable" in saved["advisory"]["generation_note"]


def test_incomplete_grid_backtest_is_not_recommended_for_minimum_hold_strategy():
    evidence = _evidence(
        paper={"closed_trades": 5, "session_realized_pnl": -10, "sharpe": 0.2},
        strategy={
            "name": "buy_the_dip",
            "slug": "btd-5dp-05sl-1tp-20d-3min-1y",
            "symbols": ["AAPL"],
            "lookback": "1y",
            "params_raw": {"min_hold_days": 3, "dip_threshold": 5},
            "grid_backtest_compatible": False,
            "unsupported_backtest_parameters": ["min_hold_days"],
        },
    )

    candidates = candidate_actions(evidence, evidence["severity"])
    advisory = finalize_advisory(
        evidence, candidates, None, AdvisorThresholds()
    )

    assert not [item for item in candidates if item["kind"] == "backtest"]
    assert "min_hold_days" in advisory["why_no_change"]


def test_unknown_or_altered_model_selection_is_rejected():
    evidence = _evidence(paper={
        "closed_trades": 5, "session_realized_pnl": -10, "sharpe": 0.2,
    })
    candidates = candidate_actions(evidence, evidence["severity"])
    unknown = AdvisorDraft(
        selections=[AdvisorSelection(
            candidate_id="invented", explanation="Do it",
            evidence_refs=["paper.sharpe"],
        )],
    )
    with pytest.raises(ValueError, match="unknown"):
        finalize_advisory(evidence, candidates, unknown, AdvisorThresholds())

    altered = AdvisorDraft(
        selections=[AdvisorSelection(
            candidate_id="retest-refined-grid",
            explanation="Paper Sharpe is 99, so test it.",
            evidence_refs=["paper.sharpe"],
        )],
    )
    with pytest.raises(ValueError, match="altered or invented"):
        finalize_advisory(evidence, candidates, altered, AdvisorThresholds())

    unsupported = AdvisorDraft(
        selections=[AdvisorSelection(
            candidate_id="retest-refined-grid",
            explanation="An earnings surprise caused the paper loss.",
            evidence_refs=["paper.sharpe"],
        )],
    )
    with pytest.raises(ValueError, match="unsupported advisor claim"):
        finalize_advisory(evidence, candidates, unsupported, AdvisorThresholds())

    supported = AdvisorDraft(
        selections=[AdvisorSelection(
            candidate_id="retest-refined-grid",
            explanation=candidates[0]["rationale"],
            evidence_refs=["paper.sharpe"],
        )],
    )
    result = finalize_advisory(
        evidence, candidates, supported, AdvisorThresholds()
    )
    assert result["ai_status"] == "available"


def test_model_cannot_omit_an_urgent_risk_candidate():
    evidence = _evidence(
        broker={
            "daily_pct": -2.1,
            "daily_pnl": -210.0,
            "drawdown_20_pct": 5.5,
            "consecutive_losing_sessions": 3,
            "unrealized_pnl": -20.0,
        },
        risk={"breaches": [], "gross_exposure_pct": 25.0},
    )
    candidates = candidate_actions(evidence, evidence["severity"])
    backtest_candidate = next(item for item in candidates if item["kind"] == "backtest")
    draft = AdvisorDraft(
        selections=[AdvisorSelection(
            candidate_id=backtest_candidate["candidate_id"],
            explanation=backtest_candidate["rationale"],
            evidence_refs=["paper.sharpe"],
        )],
    )

    with pytest.raises(ValueError, match="omitted"):
        finalize_advisory(evidence, candidates, draft, AdvisorThresholds())


def test_nyse_due_time_handles_holiday_early_close_and_dst():
    assert schedule.advisor_is_due(
        datetime(2026, 7, 3, 18, tzinfo=timezone.utc), None
    ) is False
    early_close = datetime(2026, 11, 27, 13, 0, tzinfo=EASTERN)
    assert not schedule.advisor_is_due(
        datetime(2026, 11, 27, 18, 14, tzinfo=timezone.utc), early_close
    )
    assert schedule.advisor_is_due(
        datetime(2026, 11, 27, 18, 15, tzinfo=timezone.utc), early_close
    )
    standard_close = datetime(2026, 3, 6, 16, 0, tzinfo=EASTERN)
    daylight_close = datetime(2026, 3, 9, 16, 0, tzinfo=EASTERN)
    assert schedule.advisor_is_due(
        datetime(2026, 3, 6, 21, 15, tzinfo=timezone.utc), standard_close
    )
    assert schedule.advisor_is_due(
        datetime(2026, 3, 9, 20, 15, tzinfo=timezone.utc), daylight_close
    )


def test_scheduler_enqueues_once_per_user_and_session(monkeypatch):
    schedule._enqueued_users.clear()
    schedule._session_closes.clear()
    users = [{"user_id": USER_ID, "email": "owner@example.com"}]
    monkeypatch.setattr("engine.reporting.advisor.active_advisor_users", lambda: users)
    monkeypatch.setattr(
        "engine.reporting.advisor.market_session_close",
        lambda _day: datetime(2026, 8, 19, 16, 0, tzinfo=EASTERN),
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.usable_paper_accounts",
        lambda _uid: [{"account_id": ACCOUNT_ID}],
    )
    calls = []
    monkeypatch.setattr(
        "engine.autonomy.queue.enqueue",
        lambda **kwargs: calls.append(kwargs) or "job-1",
    )
    now = datetime(2026, 8, 19, 20, 15, tzinfo=timezone.utc)

    assert schedule.enqueue_due_advisor_jobs(now) == ["job-1"]
    assert schedule.enqueue_due_advisor_jobs(now) == []
    assert calls[0]["kind"] == "deepagent_advisor"
    assert calls[0]["account_id"] is None
    assert calls[0]["config"]["account_ids"] == [ACCOUNT_ID]
    assert calls[0]["dedupe_key"].startswith("advisor:")


def test_scheduler_caches_a_non_trading_day(monkeypatch):
    schedule._enqueued_users.clear()
    schedule._session_closes.clear()
    monkeypatch.setattr(
        "engine.reporting.advisor.active_advisor_users",
        lambda: [{"user_id": USER_ID, "email": "owner@example.com"}],
    )
    calls = []
    monkeypatch.setattr(
        "engine.reporting.advisor.market_session_close",
        lambda day: calls.append(day) or None,
    )
    now = datetime(2026, 7, 4, 18, 0, tzinfo=timezone.utc)

    assert schedule.enqueue_due_advisor_jobs(now) == []
    assert schedule.enqueue_due_advisor_jobs(now) == []
    assert calls == [date(2026, 7, 4)]


def test_scheduled_pipeline_checkpoints_only_report_references_and_never_actions(
    monkeypatch,
):
    from engine.autonomy.graph import deepagent_job_pipeline

    monkeypatch.setattr(
        "engine.reporting.advisor.run_user_batch_sync",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "reports": [{
                "report_id": REPORT_ID,
                "evidence": {"must_not_be_duplicated": True},
                "advisory": {"summary": "Stored only in advisor_reports"},
            }],
            "delivery": {"delivery_id": "delivery-1", "status": "disabled"},
        },
    )

    pipeline = deepagent_job_pipeline("deepagent_advisor", USER_ID, None)
    assert [name for name, _node in pipeline.nodes] == ["daily_advisor"]
    output = pipeline.nodes[0][1]({
        "config": {"session_date": "2026-08-19"},
    })["result"]

    assert output == {
        "status": "completed",
        "report_ids": [REPORT_ID],
        "delivery": {"delivery_id": "delivery-1", "status": "disabled"},
    }
    assert "evidence" not in output


def test_consolidated_email_uses_both_stored_account_reports_and_escapes_html():
    first = _record("Growth <Paper>")
    second = _record("Income & Paper", "44444444-4444-4444-8444-444444444444")
    second["account_id"] = "55555555-5555-4555-8555-555555555555"

    body = render_advisor_email(
        {"display_name": "Owner <Admin>", "email": "owner@example.com"},
        [first, second],
    )

    assert body.count("Daily Paper Advisor") == 1
    assert "Growth &lt;Paper&gt;" in body
    assert "Income &amp; Paper" in body
    assert "Owner &lt;Admin&gt;" in body
    assert "explicit approval" in body
    assert escape(first["advisory"]["summary"]) in body


@pytest.mark.asyncio
async def test_consolidated_delivery_waits_until_every_account_report_is_ready(
    monkeypatch,
):
    accounts = [
        {"account_id": ACCOUNT_ID, "account_name": "Paper One"},
        {
            "account_id": "55555555-5555-4555-8555-555555555555",
            "account_name": "Paper Two",
        },
    ]
    monkeypatch.setattr(
        "engine.auth.get_user_by_id",
        lambda _uid: {"user_id": USER_ID, "email": "owner@example.com"},
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.usable_paper_accounts", lambda _uid: accounts,
    )

    async def generate(_uid, account, _day):
        if account["account_id"] == ACCOUNT_ID:
            return _record()
        return {
            "report_id": "44444444-4444-4444-8444-444444444444",
            "account_id": account["account_id"],
            "status": "failed",
        }

    monkeypatch.setattr(
        "engine.reporting.advisor.generate_account_report", generate
    )

    def unexpected_delivery(*_args, **_kwargs):
        raise AssertionError("an incomplete consolidated email must not be reserved")

    monkeypatch.setattr(
        "engine.reporting.advisor._reserve_delivery", unexpected_delivery
    )
    result = await run_user_batch(USER_ID, date(2026, 8, 19))

    assert result["status"] == "partial"
    assert result["reason"] == "account_report_failed"
    assert len(result["reports"]) == 2


@pytest.mark.asyncio
async def test_consolidated_delivery_is_atomically_claimed_before_email(monkeypatch):
    monkeypatch.setenv("ADVISOR_EMAIL_ENABLED", "true")
    monkeypatch.setattr(
        "engine.auth.get_user_by_id",
        lambda _uid: {"user_id": USER_ID, "email": "owner@example.com"},
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.usable_paper_accounts",
        lambda _uid: [{"account_id": ACCOUNT_ID, "account_name": "Paper One"}],
    )

    async def generate(*_args, **_kwargs):
        return _record()

    monkeypatch.setattr("engine.reporting.advisor.generate_account_report", generate)
    monkeypatch.setattr(
        "engine.reporting.advisor._reserve_delivery",
        lambda *_args: {
            "delivery_id": "delivery-1",
            "status": "pending",
            "attempts": 0,
            "report_ids": [REPORT_ID],
            "sent_at": None,
        },
    )
    monkeypatch.setattr(
        "engine.reporting.advisor._claim_delivery", lambda *_args: False
    )
    monkeypatch.setattr(
        "utils.email_util.send_email_to",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("a worker that did not claim delivery must not send")
        ),
    )

    result = await run_user_batch(USER_ID, date(2026, 8, 19))

    assert result["status"] == "completed"
    assert result["delivery"]["status"] == "sending"


def test_advisor_api_is_authenticated_and_filters_by_tenant_account(monkeypatch):
    client = TestClient(app)
    assert client.get("/v2/advisor/reports").status_code == 401

    observed = {}

    async def owned_user():
        return {"user_id": USER_ID, "auth_type": "test"}

    app.dependency_overrides[require_tenant_user] = owned_user
    monkeypatch.setattr(
        "engine.auth.get_user_accounts",
        lambda uid: [{"account_id": ACCOUNT_ID, "account_name": "Paper One"}],
    )

    def list_reports(uid, account_id=None, limit=20):
        observed.update(uid=uid, account_id=account_id, limit=limit)
        return [_record()]

    monkeypatch.setattr("engine.reporting.advisor.list_reports_for_user", list_reports)
    monkeypatch.setattr(
        "engine.reporting.advisor.get_report_for_user",
        lambda report_id, uid: _record()
        if report_id == REPORT_ID and uid == USER_ID else None,
    )
    try:
        response = client.get(
            f"/v2/advisor/reports?account_id={ACCOUNT_ID}&limit=7"
        )
        assert response.status_code == 200
        assert response.json()[0]["report_id"] == REPORT_ID
        assert observed == {
            "uid": USER_ID, "account_id": ACCOUNT_ID, "limit": 7,
        }
        foreign = client.get(
            "/v2/advisor/reports?account_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )
        assert foreign.status_code == 404
        detail = client.get(f"/v2/advisor/reports/{REPORT_ID}")
        assert detail.status_code == 200
        assert detail.json()["summary"] == _record()["advisory"]["summary"]
        foreign_detail = client.get(
            "/v2/advisor/reports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )
        assert foreign_detail.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_advisor_backtest_tool_requires_explicit_intent(monkeypatch):
    monkeypatch.setattr(
        "engine.reporting.advisor.recommendation_config",
        lambda *_args, **_kwargs: {"strategy": "buy_the_dip"},
    )
    runtime = SimpleNamespace(
        context=DeepAgentContext(
            user_id=USER_ID,
            account_id=ACCOUNT_ID,
            thread_id="thread",
            request_message_id="message",
            response_id="response",
            auth_type="jwt",
            request_id="request",
            current_user_text="Should we queue this advisor backtest?",
        ),
        tool_call_id="call-1",
    )
    with pytest.raises(PermissionError, match="advisory or hypothetical"):
        queue_advisor_backtest.func(REPORT_ID, "retest-refined-grid", runtime=runtime)

    runtime.context = SimpleNamespace(**{
        **runtime.context.__dict__,
        "current_user_text": "Queue this advisor backtest now",
    })
    # Use a proper trusted context after changing the final user text.
    runtime.context = DeepAgentContext(**runtime.context.__dict__)
    monkeypatch.setattr(
        "engine.ai.deepagent_tools._enqueue",
        lambda _runtime, tool_name, kind, config, **kwargs: {
            "tool": tool_name, "kind": kind, "config": config, **kwargs,
        },
    )
    result = queue_advisor_backtest.func(
        REPORT_ID, "retest-refined-grid", runtime=runtime
    )
    assert result["kind"] == "deepagent_backtest"
    assert result["config"] == {"strategy": "buy_the_dip"}


def test_advisor_chat_tool_preserves_partial_report_status(monkeypatch):
    monkeypatch.setattr(
        "engine.ai.deepagent_tools._effective_account_id",
        lambda _context: ACCOUNT_ID,
    )
    monkeypatch.setattr(
        "engine.reporting.advisor.list_reports_for_user",
        lambda *_args, **_kwargs: [_record()],
    )
    runtime = SimpleNamespace(context=DeepAgentContext(
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        thread_id="thread",
        request_message_id="message",
        response_id="response",
        auth_type="jwt",
        request_id="request",
        current_user_text="Show my latest advisor report",
    ))

    report = get_latest_advisor_report.func(runtime=runtime)

    assert report["status"] == "partial"
    assert "error_code" not in report


def test_paper_from_backtest_uses_only_validated_owned_stored_config(monkeypatch):
    observed = {}

    class Result:
        def fetchone(self):
            return (
                "buy_the_dip",
                {"lookback": "6m", "symbols": "AAPL,MSFT"},
                {"dip_threshold": 0.05, "take_profit": 0.01},
            )

    class Session:
        def execute(self, statement, params):
            observed["query"] = str(statement)
            observed["query_params"] = params
            return Result()

    class Pool:
        @contextmanager
        def get_session(self):
            yield Session()

    context = DeepAgentContext(
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        thread_id="thread",
        request_message_id="message",
        response_id="response",
        auth_type="jwt",
        request_id="request",
        current_user_text="Start paper trading from validated backtest bt-1",
    )
    runtime = SimpleNamespace(context=context, tool_call_id="call-2")
    monkeypatch.setattr("engine.ai.deepagent_tools.DatabasePool", lambda: Pool())
    monkeypatch.setattr("engine.ai.deepagent_tools._broker", lambda _context: object())
    monkeypatch.setattr(
        "engine.ai.deepagent_tools._effective_account_id", lambda _context: ACCOUNT_ID
    )
    monkeypatch.setattr(
        "engine.ai.deepagent_tools._enqueue",
        lambda _runtime, tool_name, kind, config, **_kwargs: {
            "tool": tool_name, "kind": kind, "config": config,
        },
    )

    result = queue_paper_from_backtest.func("bt-1", 900, runtime=runtime)

    assert observed["query_params"] == {
        "rid": "bt-1", "uid": USER_ID, "aid": ACCOUNT_ID,
    }
    assert "v.source = 'backtest'" in observed["query"]
    assert "COALESCE(v.total_checked, 0) > 0" in observed["query"]
    assert "COALESCE(bs.total_trades, 0) > 0" in observed["query"]
    assert result["kind"] == "deepagent_paper"
    assert result["config"]["approved_best_config"] == {
        "params": {"dip_threshold": 0.05, "take_profit": 0.01},
    }
    assert result["config"]["symbols"] == ["AAPL", "MSFT"]
    assert result["config"]["email_notifications"] is False


def test_paper_from_backtest_rejects_a_strategy_the_paper_engine_cannot_run(
    monkeypatch,
):
    class Result:
        def fetchone(self):
            return ("momentum", {"lookback": "3m"}, {"lookback_period": 20})

    class Session:
        def execute(self, _statement, _params):
            return Result()

    class Pool:
        @contextmanager
        def get_session(self):
            yield Session()

    runtime = SimpleNamespace(context=DeepAgentContext(
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        thread_id="thread",
        request_message_id="message",
        response_id="response",
        auth_type="jwt",
        request_id="request",
        current_user_text="Start paper trading from validated backtest bt-2",
    ))
    monkeypatch.setattr("engine.ai.deepagent_tools.DatabasePool", lambda: Pool())
    monkeypatch.setattr("engine.ai.deepagent_tools._broker", lambda _context: object())
    monkeypatch.setattr(
        "engine.ai.deepagent_tools._effective_account_id", lambda _context: ACCOUNT_ID
    )

    with pytest.raises(ValueError, match="supports only buy_the_dip"):
        queue_paper_from_backtest.func("bt-2", 900, runtime=runtime)


def test_validation_persistence_maps_nonempty_validator_count(monkeypatch):
    from utils import agent_storage

    observed = {}

    class Session:
        def execute(self, _statement, params):
            observed.update(params)

    class Pool:
        @contextmanager
        def get_session(self):
            yield Session()

    monkeypatch.setattr(agent_storage, "get_storage_backend", lambda: "db")
    monkeypatch.setattr(agent_storage, "_get_pool", lambda: Pool())

    agent_storage.store_validation("bt-1", {
        "source": "backtest",
        "status": "passed",
        "total_trades_checked": 7,
    }, user_id=USER_ID)

    assert observed["total_checked"] == 7


def test_advisor_migration_has_account_and_delivery_dedupe_constraints():
    sql = (Path(__file__).parents[1] / "sql" / "19_daily_advisor.sql").read_text()
    assert "uq_advisor_reports_user_account_session" in sql
    assert "ON alpatrade.advisor_reports (user_id, account_id, session_date)" in sql
    assert "uq_advisor_deliveries_user_session_channel_recipient" in sql
    assert "ON alpatrade.advisor_deliveries (user_id, session_date, channel, recipient)" in sql
    assert "FOREIGN KEY (user_id, account_id)" in sql
    assert "REFERENCES alpatrade.user_accounts(user_id, account_id)" in sql
    assert "ADD COLUMN IF NOT EXISTS strategy_slug" in sql
    assert "narrative       TEXT" in sql
