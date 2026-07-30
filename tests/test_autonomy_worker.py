from unittest.mock import MagicMock, patch


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

    factory.assert_called_once_with("user-1", "account-1")
    pipeline.run.assert_called_once_with(
        "run-1", ctx={"config": {"strategy": "buy_the_dip"}, "run_id": "run-1"})
    ack.assert_called_once_with("run-1")


def test_worker_returns_false_for_empty_queue():
    with patch("engine.autonomy.worker.queue.claim", return_value=None):
        from engine.autonomy.worker import run_one
        assert run_one("test-worker") is False
