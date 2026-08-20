from unittest.mock import ANY, MagicMock, patch

import pytest


def test_worker_propagates_run_tenant_and_stops_heartbeat_thread():
    claimed = {
        "run_id": "run-1", "attempt": 1, "config": {"strategy": "buy_the_dip"},
        "user_id": "user-1", "account_id": "account-1",
    }
    pipeline = MagicMock()
    with patch("engine.autonomy.worker.queue.claim", return_value=claimed), \
         patch("engine.autonomy.worker.queue.ack") as ack, \
         patch("engine.autonomy.worker.store.append_event"), \
         patch("engine.autonomy.worker.default_pipeline", return_value=pipeline) as factory:
        from engine.autonomy.worker import run_one
        assert run_one("test-worker") is True

    factory.assert_called_once_with("user-1", "account-1", stop_event=ANY)
    pipeline.run.assert_called_once_with(
        "run-1", ctx={"config": {"strategy": "buy_the_dip"}, "run_id": "run-1"},
        stop_event=ANY)
    ack.assert_called_once_with("run-1")


def test_worker_returns_false_for_empty_queue():
    with patch("engine.autonomy.worker.queue.claim", return_value=None):
        from engine.autonomy.worker import run_one
        assert run_one("test-worker") is False


def test_worker_never_retries_uncertain_paper_job():
    claimed = {
        "run_id": "run-paper", "kind": "deepagent_paper", "attempt": 1,
        "config": {}, "user_id": "user-1", "account_id": "account-1",
    }
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("uncertain broker failure")
    with patch("engine.autonomy.worker.queue.claim", return_value=claimed), \
         patch("engine.autonomy.worker.queue.fail", return_value="failed") as fail, \
         patch("engine.autonomy.worker.store.append_event"), \
         patch("engine.autonomy.worker.deepagent_job_pipeline", return_value=pipeline):
        from engine.autonomy.worker import run_one
        assert run_one("test-worker") is True

    assert fail.call_args.kwargs["max_attempts"] == 1


def test_pipeline_does_not_overwrite_a_concurrent_cancellation():
    from engine.autonomy.graph import JobCancelled, Pipeline

    with patch("engine.autonomy.graph.store.completed_steps", return_value=set()), \
         patch("engine.autonomy.graph.store.completed_step_outputs", return_value={}), \
         patch("engine.autonomy.graph.store.mark_running", return_value=True), \
         patch("engine.autonomy.graph.store.save_step"), \
         patch("engine.autonomy.graph.store.append_event"), \
         patch("engine.autonomy.graph.store.set_status", return_value=False) as status:
        with pytest.raises(JobCancelled, match="cancelled"):
            Pipeline([("paper_trade", lambda _ctx: {"result": "accepted"})]).run(
                "run-cancelled"
            )

    status.assert_called_once_with("run-cancelled", "done")
