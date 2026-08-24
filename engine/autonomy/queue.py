"""DB-backed run queue — no Redis.

A worker claims the oldest queued run atomically with ``FOR UPDATE SKIP LOCKED`` (so N
workers never grab the same run), heartbeats while working, and acks/fails on finish.
``requeue_unfinished`` returns runs whose worker died (stale heartbeat) to the queue, so
a lost queue never loses a run.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _pool():
    return DatabasePool()


def enqueue(kind: str = "full", config: Optional[dict] = None,
            user_id: Optional[str] = None, account_id: Optional[str] = None,
            dedupe_key: Optional[str] = None) -> str:
    with _pool().get_session() as s:
        rid = s.execute(text("""
            INSERT INTO alpatrade.autonomy_runs
                (kind, status, config, user_id, account_id, dedupe_key)
            VALUES (:kind, 'queued', :config, :uid, :aid, :dedupe)
            ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL
            DO UPDATE SET updated_at = alpatrade.autonomy_runs.updated_at
            RETURNING run_id
        """), {"kind": kind, "config": json.dumps(config or {}),
               "uid": user_id, "aid": account_id,
               "dedupe": dedupe_key[:255] if dedupe_key else None}).scalar()
    return str(rid)


def claim(worker_id: str, *, advisor_only: bool = False) -> Optional[dict]:
    """Atomically claim the oldest queued run. Returns the run dict or None."""
    with _pool().get_session() as s:
        row = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET
                status = 'running', claimed_by = :w, attempt = attempt + 1,
                heartbeat_at = NOW(), updated_at = NOW()
            WHERE run_id = (
                SELECT run_id FROM alpatrade.autonomy_runs
                WHERE status = 'queued'
                  AND (:advisor_only = FALSE OR kind = 'deepagent_advisor')
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING run_id, kind, config, attempt, user_id, account_id
        """), {"w": worker_id, "advisor_only": advisor_only}).fetchone()
    if not row:
        return None
    return {"run_id": str(row[0]), "kind": row[1], "config": row[2], "attempt": row[3],
            "user_id": str(row[4]) if row[4] else None,
            "account_id": str(row[5]) if row[5] else None}


def heartbeat(run_id: str, worker_id: str) -> None:
    with _pool().get_session() as s:
        s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET heartbeat_at = NOW(), updated_at = NOW()
            WHERE run_id = :rid AND claimed_by = :w
        """), {"rid": run_id, "w": worker_id})


def ack(run_id: str) -> bool:
    with _pool().get_session() as s:
        changed = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET status = 'done', updated_at = NOW()
            WHERE run_id = :rid AND status IN ('running', 'done')
        """), {"rid": run_id}).rowcount
    return bool(changed)


def fail(run_id: str, error: str, max_attempts: int = 3) -> str:
    """Requeue for retry, or mark 'failed' once attempts are exhausted. Returns new status."""
    with _pool().get_session() as s:
        new_status = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET
                status = CASE WHEN attempt >= :maxa THEN 'failed' ELSE 'queued' END,
                claimed_by = NULL, error = :err, updated_at = NOW()
            WHERE run_id = :rid AND status IN ('running', 'failed')
            RETURNING status
        """), {"maxa": max_attempts, "err": error[:2000], "rid": run_id}).scalar()
        if new_status is None:
            new_status = s.execute(text("""
                SELECT status FROM alpatrade.autonomy_runs WHERE run_id = :rid
            """), {"rid": run_id}).scalar()
    return new_status or "failed"


def cancel(run_id: str, user_id: str, account_id: Optional[str] = None) -> bool:
    """Cancel an owned queued/running job; active paper loops observe this state."""
    with _pool().get_session() as s:
        changed = s.execute(text("""
            UPDATE alpatrade.autonomy_runs
            SET status = 'cancelled', updated_at = NOW()
            WHERE run_id = :rid AND user_id = :uid
              AND (CAST(:account_id AS UUID) IS NULL OR account_id = CAST(:account_id AS UUID))
              AND status IN ('queued', 'running')
        """), {"rid": run_id, "uid": user_id, "account_id": account_id}).rowcount
    return bool(changed)


def is_cancelled(run_id: str, user_id: Optional[str] = None) -> bool:
    with _pool().get_session() as s:
        row = s.execute(text("""
            SELECT status FROM alpatrade.autonomy_runs
            WHERE run_id = :rid
              AND (:uid IS NULL OR user_id = CAST(:uid AS UUID))
        """), {"rid": run_id, "uid": user_id}).scalar()
    return row == "cancelled"


def pending_count() -> int:
    """Runs currently queued or running (to decide whether the scout should self-feed)."""
    with _pool().get_session() as s:
        n = s.execute(text("""
            SELECT COUNT(*) FROM alpatrade.autonomy_runs WHERE status IN ('queued', 'running')
        """)).scalar()
    return int(n or 0)


def requeue_unfinished(stale_seconds: int = 300) -> int:
    """Return runs stuck in 'running' with a stale heartbeat back to 'queued'."""
    with _pool().get_session() as s:
        n = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET status = 'queued', claimed_by = NULL,
                   updated_at = NOW()
            WHERE status = 'running'
              AND kind NOT IN ('full', 'deepagent_paper', 'deepagent_full')
              AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - (:sec * INTERVAL '1 second'))
        """), {"sec": stale_seconds}).rowcount
    return n or 0


def fail_uncertain_trading_jobs(stale_seconds: int = 300) -> int:
    """Never retry a paper-capable job after an uncertain worker failure."""
    with _pool().get_session() as s:
        count = s.execute(text("""
            UPDATE alpatrade.autonomy_runs
            SET status = 'failed', claimed_by = NULL,
                error = 'Worker heartbeat expired; paper-capable job was not retried.',
                updated_at = NOW()
            WHERE status = 'running'
              AND kind IN ('full', 'deepagent_paper', 'deepagent_full')
              AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - (:sec * INTERVAL '1 second'))
        """), {"sec": stale_seconds}).rowcount
    return int(count or 0)


def retry(run_id: str, user_id: str) -> bool:
    """Requeue one failed run owned by ``user_id`` and retain checkpoints."""
    with _pool().get_session() as s:
        n = s.execute(text("""
            UPDATE alpatrade.autonomy_runs
            SET status = 'queued', claimed_by = NULL, heartbeat_at = NULL,
                error = NULL, updated_at = NOW()
            WHERE run_id = :rid AND user_id = :uid
              AND status = 'failed'
        """), {"rid": run_id, "uid": user_id}).rowcount
    return bool(n)
