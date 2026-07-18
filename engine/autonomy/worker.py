"""Continuous autonomy worker — self-feeding loop, Postgres-only.

Gated by ``AUTONOMY_ENABLED`` (off by default, incl. prod). Each tick:
  1. ``requeue_unfinished`` — reclaim runs whose worker died.
  2. (Phase C) scout scan → ``queue.enqueue`` new candidate runs.
  3. Drain: ``queue.claim`` → run the pipeline (heart-beating) → ack / fail.

Run: ``python -m engine.autonomy.worker``. Paper-only; never places live orders.
"""
from __future__ import annotations

import logging
import os
import time

from engine.autonomy import queue, store
from engine.autonomy.graph import default_pipeline

log = logging.getLogger("autonomy.worker")

SCAN_SECONDS = int(os.getenv("AUTONOMY_SCAN_SECONDS", "300"))
STALE_SECONDS = int(os.getenv("AUTONOMY_STALE_SECONDS", "900"))
MAX_ATTEMPTS = int(os.getenv("AUTONOMY_MAX_ATTEMPTS", "3"))


def _enabled() -> bool:
    return os.getenv("AUTONOMY_ENABLED", "false").lower() in ("1", "true", "yes", "on")


def run_one(worker_id: str) -> bool:
    """Claim and run a single queued run. Returns True if one was processed."""
    claimed = queue.claim(worker_id)
    if not claimed:
        return False
    run_id = claimed["run_id"]
    store.append_event(run_id, f"claimed by {worker_id} (attempt {claimed['attempt']})")
    try:
        pipeline = default_pipeline()
        pipeline.run(run_id, ctx={"config": claimed.get("config") or {}})
        queue.ack(run_id)
        store.append_event(run_id, "run complete")
    except Exception as e:  # noqa: BLE001
        status = queue.fail(run_id, str(e), max_attempts=MAX_ATTEMPTS)
        store.append_event(run_id, f"run errored → {status}: {e}", level="error")
    return True


def loop(worker_id: str = "worker-1") -> None:
    if not _enabled():
        log.warning("AUTONOMY_ENABLED is off — worker idle. Set AUTONOMY_ENABLED=true to run.")
    log.info("autonomy worker %s starting (scan=%ss)", worker_id, SCAN_SECONDS)
    while True:
        if not _enabled():
            time.sleep(SCAN_SECONDS)
            continue
        try:
            reclaimed = queue.requeue_unfinished(STALE_SECONDS)
            if reclaimed:
                log.info("requeued %d stale run(s)", reclaimed)
            # Phase C: scout.enqueue_candidates() goes here.
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
