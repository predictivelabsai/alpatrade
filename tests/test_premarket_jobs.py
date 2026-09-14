"""DB-free scheduling and worker contracts; SQL concurrency has its own suite."""
from datetime import date, datetime, time
from unittest.mock import Mock

import pytest

from engine import premarket_jobs as jobs, premarket_data as data
from engine import premarket_analysis as analysis, premarket_providers as provider

DAY = date(2026, 8, 7)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("PREMARKET_V2_ENABLED", "true")
    monkeypatch.setenv("PREMARKET_WORKER_ENABLED", "true")
    monkeypatch.setenv("AUTONOMY_ENABLED", "false")


@pytest.mark.parametrize("at,kinds", [("04:15:59", []), ("04:16:00", ["previous_closes"]),
    ("09:16:19", ["previous_closes"]), ("09:16:20", ["previous_closes", "finalize"]),
    ("15:00:00", ["previous_closes", "finalize"])])
def test_schedule_boundaries_and_late_start(enabled, monkeypatch, at, kinds):
    enqueue = Mock(side_effect=lambda kind, day: {"kind": kind, "day": day})
    monkeypatch.setattr(jobs, "enqueue", enqueue)
    result = jobs.schedule(datetime.combine(DAY, time.fromisoformat(at), data.ET))
    assert [job["kind"] for job in result] == kinds
    assert all(job["day"] == DAY for job in result)  # no automatic historical backfill


@pytest.mark.parametrize("day", [date(2026, 8, 8), date(2026, 9, 7)])
def test_closed_sessions_never_schedule(enabled, monkeypatch, day):
    enqueue = Mock()
    monkeypatch.setattr(jobs, "enqueue", enqueue)
    assert jobs.schedule(datetime.combine(day, time(10), data.ET)) == []
    enqueue.assert_not_called()


def test_dedicated_worker_starts_when_autonomy_is_disabled(enabled, monkeypatch):
    monkeypatch.setattr(jobs, "_started", False)
    thread = Mock()
    monkeypatch.setattr(jobs.threading, "Thread", Mock(return_value=thread))
    jobs.start()
    jobs.start()
    thread.start.assert_called_once()


def test_disabled_worker_does_not_schedule(monkeypatch):
    monkeypatch.setenv("PREMARKET_V2_ENABLED", "false")
    assert jobs.schedule(datetime.combine(DAY, time(10), data.ET)) == []


def test_saved_grok_is_reused_without_credentials_allowance_or_worker(enabled, monkeypatch):
    monkeypatch.setattr(data, "company", lambda ticker: {"company_id": 1, "exchange_id": 1})
    monkeypatch.setattr(data, "session_hours", lambda *args: True)
    monkeypatch.setattr(data, "now_et", lambda *args: datetime(2026, 8, 8, tzinfo=data.ET))
    monkeypatch.setattr(analysis, "saved_for_date", lambda *args: {1: [{"provider": "grok", "text": "Saved"}]})
    monkeypatch.setattr(analysis, "credentials", Mock(side_effect=AssertionError("must not resolve credentials")))
    monkeypatch.setattr(jobs, "enqueue", Mock(side_effect=AssertionError("must not enqueue")))
    monkeypatch.setenv("PREMARKET_WORKER_ENABLED", "false")
    assert jobs.request_analysis("AAA", DAY.isoformat(), "user")["analysis"]["text"] == "Saved"


def test_anonymous_generation_is_rejected_before_any_data_access():
    with pytest.raises(PermissionError, match="Sign in"):
        jobs.request_analysis("AAA", DAY.isoformat(), "")


def test_collection_checkpoints_gaps_and_does_not_reprocess_completed_companies(enabled, monkeypatch):
    companies = [{"company_id": i, "ticker": f"T{i}"} for i in range(30)]
    monkeypatch.setattr(data, "catalog", lambda: companies)
    monkeypatch.setattr(data, "now_et", lambda: datetime(2026, 8, 8, tzinfo=data.ET))
    monkeypatch.setattr(data, "session_hours", lambda *args: True)
    monkeypatch.setattr(data, "previous_session", lambda day: date(2026, 8, 6))
    monkeypatch.setattr(data, "observations", lambda day: {0: {"finalized": True}})
    monkeypatch.setattr(data, "persist_observations", Mock())
    monkeypatch.setattr(provider, "previous_closes", lambda *args: [])
    final = Mock(return_value=None)
    monkeypatch.setattr(provider, "final_observation", final)
    monkeypatch.setattr(jobs.time, "sleep", lambda _: None)
    checkpoint = Mock()
    monkeypatch.setattr(jobs, "_continue", checkpoint)
    jobs._collect({"kind": "finalize", "trading_date": DAY, "payload": {}})
    assert final.call_count == 25
    payload = checkpoint.call_args.args[1]
    assert payload["cursor"] == 25 and 0 not in payload["companies"]
    assert all(call.args[1] == DAY for call in final.call_args_list)


def test_provider_failure_has_reviewed_message_and_retry(enabled, monkeypatch):
    job = {"job_id": "job", "kind": "previous_closes"}
    monkeypatch.setattr(jobs, "claim", lambda _: job)
    monkeypatch.setattr(jobs, "_collect", Mock(side_effect=provider.ProviderUnavailable("MASSIVE_API_KEY is not configured.")))
    failure = Mock()
    monkeypatch.setattr(jobs, "fail", failure)
    assert jobs.run_one("worker")
    assert failure.call_args.args[1] == "MASSIVE_API_KEY is not configured."
    assert failure.call_args.kwargs["terminal"] is False


def test_arbitrary_error_text_is_never_saved(enabled, monkeypatch):
    monkeypatch.setattr(jobs, "claim", lambda _: {"job_id": "job", "kind": "analysis"})
    monkeypatch.setattr(jobs, "_analysis", Mock(side_effect=ValueError("sensitive transport contents")))
    failure = Mock()
    monkeypatch.setattr(jobs, "fail", failure)
    jobs.run_one("worker")
    assert "sensitive" not in failure.call_args.args[1]
