"""Continuous autonomy worker — self-feeding loop, Postgres-only.

Full autonomy is gated by ``AUTONOMY_ENABLED`` (on by default in prod via
docker-compose); the worker-owned daily advisor queue continues when it is off.
Each tick:
  1. ``requeue_unfinished`` — reclaim runs whose worker died.
  2. (Phase C) scout scan → ``queue.enqueue`` new candidate runs.
  3. Drain: ``queue.claim`` → run the pipeline (heart-beating) → ack / fail.

Run: ``python -m engine.autonomy.worker``. Paper-only; never places live orders.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from engine.autonomy import queue, store
from engine.autonomy.graph import JobCancelled, deepagent_job_pipeline, default_pipeline

log = logging.getLogger("autonomy.worker")

SCAN_SECONDS = int(os.getenv("AUTONOMY_SCAN_SECONDS", "300"))
STALE_SECONDS = int(os.getenv("AUTONOMY_STALE_SECONDS", "900"))
MAX_ATTEMPTS = int(os.getenv("AUTONOMY_MAX_ATTEMPTS", "3"))
HEARTBEAT_SECONDS = int(os.getenv("AUTONOMY_HEARTBEAT_SECONDS", "30"))
ADVISOR_POLL_SECONDS = max(
    1, int(os.getenv("ADVISOR_WORKER_POLL_SECONDS", "10"))
)


def _enabled() -> bool:
    return os.getenv("AUTONOMY_ENABLED", "false").lower() in ("1", "true", "yes", "on")


def run_one(worker_id: str, *, advisor_only: bool = False) -> bool:
    """Claim and run a single queued run. Returns True if one was processed."""
    claimed = queue.claim(worker_id, advisor_only=advisor_only)
    if not claimed:
        return False
    run_id = claimed["run_id"]
    store.append_event(run_id, f"claimed by {worker_id} (attempt {claimed['attempt']})")
    stopped = threading.Event()
    cancel_requested = threading.Event()

    def _heartbeat() -> None:
        while not stopped.wait(HEARTBEAT_SECONDS):
            try:
                queue.heartbeat(run_id, worker_id)
                if queue.is_cancelled(run_id, claimed.get("user_id")):
                    cancel_requested.set()
            except Exception as exc:  # noqa: BLE001
                log.warning("heartbeat failed for %s: %s", run_id, exc)

    pulse = threading.Thread(target=_heartbeat, name=f"heartbeat-{run_id[:8]}", daemon=True)
    pulse.start()
    try:
        kind = claimed.get("kind") or "full"
        if kind.startswith("deepagent_"):
            if not claimed.get("user_id"):
                raise ValueError("DeepAgent jobs require a tenant user")
            pipeline = deepagent_job_pipeline(
                kind,
                claimed["user_id"],
                claimed.get("account_id"),
                stop_event=cancel_requested,
            )
        else:
            pipeline = default_pipeline(
                claimed.get("user_id"),
                claimed.get("account_id"),
                stop_event=cancel_requested,
            )
        pipeline.run(
            run_id,
            ctx={"config": claimed.get("config") or {}, "run_id": run_id},
            stop_event=cancel_requested,
        )
        if cancel_requested.is_set():
            raise JobCancelled("job cancelled")
        queue.ack(run_id)
        store.append_event(run_id, "run complete")
    except JobCancelled:
        store.append_event(run_id, "run cancelled")
    except Exception as e:  # noqa: BLE001
        no_retry = claimed.get("kind") in {"full", "deepagent_paper", "deepagent_full"}
        status = queue.fail(run_id, str(e), max_attempts=1 if no_retry else MAX_ATTEMPTS)
        store.append_event(run_id, f"run errored → {status}", level="error")
    finally:
        stopped.set()
        pulse.join(timeout=1)
    return True


def _advisor_loop(worker_id: str) -> None:
    """Drain advisor jobs independently of long-running paper sessions.

    The general autonomy lane can legitimately spend an hour or more inside a
    bounded paper-trading phase. Keeping the reporting lane separate ensures a
    post-close job is still claimed promptly without moving scheduler ownership
    out of the autonomy worker process.
    """
    log.info(
        "daily advisor queue lane %s starting (poll=%ss)",
        worker_id,
        ADVISOR_POLL_SECONDS,
    )
    while True:
        try:
            drained = 0
            while run_one(worker_id, advisor_only=True):
                drained += 1
            if not drained:
                time.sleep(ADVISOR_POLL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            log.exception("daily advisor queue lane failed: %s", exc)
            time.sleep(ADVISOR_POLL_SECONDS)


def loop(worker_id: str = "worker-1") -> None:
    # The NYSE-aware advisor scheduler is owned only by this worker process.
    try:
        from engine.autonomy.schedule import start as start_scheduler
        start_scheduler()
    except Exception as e:  # noqa: BLE001
        log.warning("daily advisor scheduler failed to start: %s", e)
    threading.Thread(
        target=_advisor_loop,
        args=(f"{worker_id}-advisor",),
        name="daily-advisor-worker",
        daemon=True,
    ).start()
    if not _enabled():
        log.warning(
            "AUTONOMY_ENABLED is off — only scheduled daily-advisor jobs will run."
        )
    log.info("autonomy worker %s starting (scan=%ss)", worker_id, SCAN_SECONDS)
    while True:
        if not _enabled():
            try:
                # Advisor generation remains durable even when the broader autonomy
                # loop is disabled: reclaim a report job left running by a dead worker.
                reclaimed = queue.requeue_unfinished(STALE_SECONDS)
                uncertain = queue.fail_uncertain_trading_jobs(STALE_SECONDS)
                if reclaimed:
                    log.info("requeued %d stale run(s)", reclaimed)
                if uncertain:
                    log.warning("failed %d uncertain paper-capable run(s)", uncertain)
                time.sleep(SCAN_SECONDS)
            except Exception as e:  # noqa: BLE001
                log.exception("advisor-only worker tick failed: %s", e)
                time.sleep(min(SCAN_SECONDS, 30))
            continue
        try:
            reclaimed = queue.requeue_unfinished(STALE_SECONDS)
            uncertain = queue.fail_uncertain_trading_jobs(STALE_SECONDS)
            if reclaimed:
                log.info("requeued %d stale run(s)", reclaimed)
            if uncertain:
                log.warning("failed %d uncertain paper-capable run(s)", uncertain)
            # Self-feed: when the queue is idle, the Scout enqueues one new run.
            if queue.pending_count() == 0:
                from engine.autonomy import scout
                rid = scout.enqueue_run(strategy=os.getenv("AUTONOMY_STRATEGY", "btd"))
                if rid:
                    log.info("scout enqueued run %s", rid)
            drained = 0
            while run_one(worker_id):
                drained += 1
            if not drained:
                time.sleep(SCAN_SECONDS)
        except Exception as e:  # noqa: BLE001 — never let one tick kill the worker
            log.exception("worker tick failed: %s", e)
            time.sleep(min(SCAN_SECONDS, 30))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop(os.getenv("AUTONOMY_WORKER_ID", "worker-1"))
