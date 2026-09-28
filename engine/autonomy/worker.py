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
from utils.agent_storage import sweep_stale_paper_runs

log = logging.getLogger("autonomy.worker")

SCAN_SECONDS = int(os.getenv("AUTONOMY_SCAN_SECONDS", "300"))
STALE_SECONDS = int(os.getenv("AUTONOMY_STALE_SECONDS", "900"))
MAX_ATTEMPTS = int(os.getenv("AUTONOMY_MAX_ATTEMPTS", "3"))
HEARTBEAT_SECONDS = int(os.getenv("AUTONOMY_HEARTBEAT_SECONDS", "30"))
# Paper runs left 'running' by an interrupted/redeployed process are swept to
# 'stopped' once their heartbeat is older than this (default 30 min).
RUNS_STALE_SECONDS = int(os.getenv("RUNS_STALE_SECONDS", "1800"))
# Loop guards (2026-09-28 cost incident: failing runs were re-enqueued back to back,
# ~1,000-1,500 runs/day, each making LLM calls).
MAX_CONSECUTIVE_FAILURES = max(1, int(os.getenv("AUTONOMY_MAX_CONSECUTIVE_FAILURES", "5")))
FAILURE_PAUSE_SECONDS = max(60, int(os.getenv("AUTONOMY_FAILURE_PAUSE_SECONDS", "21600")))
MAX_BACKOFF_SECONDS = max(1, int(os.getenv("AUTONOMY_MAX_BACKOFF_SECONDS", "3600")))
MAX_RUNS_PER_DAY = max(0, int(os.getenv("AUTONOMY_MAX_RUNS_PER_DAY", "24")))

_outcome = threading.local()


def last_outcome() -> str | None:
    """Outcome of this thread's most recent ``run_one``: ok / failed / cancelled."""
    return getattr(_outcome, "value", None)


class LoopGuard:
    """Back-off and circuit breaker for the self-feeding autonomy loop.

    Every failed run makes the loop sleep at least ``SCAN_SECONDS``, doubling per
    consecutive failure (capped). After ``MAX_CONSECUTIVE_FAILURES`` in a row the
    loop pauses (no scouting, no claiming) for ``FAILURE_PAUSE_SECONDS`` and says so
    loudly in the log and in ``autonomy_events``.
    """

    def __init__(self, *, max_failures: int = MAX_CONSECUTIVE_FAILURES,
                 pause_seconds: int = FAILURE_PAUSE_SECONDS,
                 base_seconds: int | None = None,
                 max_backoff: int = MAX_BACKOFF_SECONDS, clock=time.monotonic):
        self.max_failures = max_failures
        self.pause_seconds = pause_seconds
        self.base_seconds = max(1, SCAN_SECONDS if base_seconds is None else base_seconds)
        self.max_backoff = max(max_backoff, self.base_seconds)
        self.clock = clock
        self.failures = 0
        self.paused_until = 0.0

    def paused(self) -> bool:
        return self.clock() < self.paused_until

    def record(self, outcome: str | None) -> None:
        if outcome == "failed":
            self.failures += 1
            if self.failures >= self.max_failures:
                self.paused_until = self.clock() + self.pause_seconds
                msg = (f"autonomy loop PAUSED for {self.pause_seconds}s after "
                       f"{self.failures} consecutive failed runs")
                log.error(msg)
                try:
                    store.append_event(None, msg, level="error")
                except Exception:  # noqa: BLE001 — never let the guard crash the loop
                    pass
                self.failures = 0
        elif outcome == "ok":
            self.failures = 0

    def sleep_seconds(self, failed: bool) -> int:
        if not failed:
            return self.base_seconds
        exp = max(self.failures - 1, 0)
        return int(min(self.base_seconds * (2 ** exp), self.max_backoff))


def self_feed_allowed(max_per_day: int = MAX_RUNS_PER_DAY) -> bool:
    """Daily cap on autonomy 'full' runs; fails closed if the count is unavailable."""
    if max_per_day <= 0:
        return False
    try:
        return queue.full_runs_created_today() < max_per_day
    except Exception as e:  # noqa: BLE001
        log.warning("daily run cap check failed (%s); not self-feeding", e)
        return False


def scout_owner() -> tuple[str | None, str | None]:
    """Resolve the owner for scout self-fed autonomous runs.

    Without an owner the self-feed enqueues UNATTRIBUTED runs (user_id NULL) that
    pile up because the session-scoped dedup guard only acts on attributed runs.
    Reads AUTONOMY_OWNER_USER_ID/AUTONOMY_OWNER_ACCOUNT_ID, falling back to
    PAPER_USER_ID/PAPER_ACCOUNT_ID so one env pair can own both this worker's
    self-feed and the fixed paper-strategy service. Both must be set together —
    a half-configured pair resolves to unattributed rather than a broken lookup.
    """
    uid = (os.getenv("AUTONOMY_OWNER_USER_ID", "").strip()
           or os.getenv("PAPER_USER_ID", "").strip() or None)
    aid = (os.getenv("AUTONOMY_OWNER_ACCOUNT_ID", "").strip()
           or os.getenv("PAPER_ACCOUNT_ID", "").strip() or None)
    if not (uid and aid):
        return None, None
    return uid, aid
ADVISOR_POLL_SECONDS = max(
    1, int(os.getenv("ADVISOR_WORKER_POLL_SECONDS", "10"))
)


def _enabled() -> bool:
    return os.getenv("AUTONOMY_ENABLED", "false").lower() in ("1", "true", "yes", "on")


def run_one(worker_id: str, *, advisor_only: bool = False) -> bool:
    """Claim and run a single queued run. Returns True if one was processed."""
    _outcome.value = None
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
        _outcome.value = "ok"
    except JobCancelled:
        store.append_event(run_id, "run cancelled")
        _outcome.value = "cancelled"
    except Exception as e:  # noqa: BLE001
        _outcome.value = "failed"
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
    # Research collection is independent of both trading and advisor queues.
    from engine.premarket_jobs import start as start_premarket
    start_premarket()
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
    log.info("autonomy worker %s starting (scan=%ss, max %s runs/day, pause after %s failures)",
             worker_id, SCAN_SECONDS, MAX_RUNS_PER_DAY, MAX_CONSECUTIVE_FAILURES)
    guard = LoopGuard()
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
            sweep_stale_paper_runs(RUNS_STALE_SECONDS)
            if reclaimed:
                log.info("requeued %d stale run(s)", reclaimed)
            if uncertain:
                log.warning("failed %d uncertain paper-capable run(s)", uncertain)
            if guard.paused():
                time.sleep(SCAN_SECONDS)
                continue
            # Self-feed: when the queue is idle and under the daily cap, the Scout
            # enqueues one new run.
            if queue.pending_count() == 0 and self_feed_allowed():
                from engine.autonomy import scout
                # Attribute the self-fed run to the configured owner so it is a
                # tenant-scoped session (not an orphan) and the dedup guard applies.
                owner_uid, owner_aid = scout_owner()
                rid = scout.enqueue_run(
                    strategy=os.getenv("AUTONOMY_STRATEGY", "btd"),
                    user_id=owner_uid,
                    account_id=owner_aid,
                )
                if rid:
                    log.info("scout enqueued run %s (owner=%s)", rid,
                             (owner_uid[:8] if owner_uid else "unattributed"))
            failed = False
            while run_one(worker_id):
                outcome = last_outcome()
                guard.record(outcome)
                if outcome == "failed" or guard.paused():
                    failed = outcome == "failed"
                    break
            # Always wait between ticks: a finished (or failed) run must never
            # immediately trigger another scout + run (the Sep 2026 hot loop).
            time.sleep(guard.sleep_seconds(failed))
        except Exception as e:  # noqa: BLE001 — never let one tick kill the worker
            log.exception("worker tick failed: %s", e)
            time.sleep(min(SCAN_SECONDS, 30))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop(os.getenv("AUTONOMY_WORKER_ID", "worker-1"))
