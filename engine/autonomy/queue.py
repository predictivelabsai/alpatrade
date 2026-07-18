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
            user_id: Optional[str] = None, account_id: Optional[str] = None) -> str:
    with _pool().get_session() as s:
        rid = s.execute(text("""
            INSERT INTO alpatrade.autonomy_runs (kind, status, config, user_id, account_id)
            VALUES (:kind, 'queued', :config, :uid, :aid) RETURNING run_id
        """), {"kind": kind, "config": json.dumps(config or {}),
               "uid": user_id, "aid": account_id}).scalar()
    return str(rid)


def claim(worker_id: str) -> Optional[dict]:
    """Atomically claim the oldest queued run. Returns the run dict or None."""
    with _pool().get_session() as s:
        row = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET
                status = 'running', claimed_by = :w, attempt = attempt + 1,
                heartbeat_at = NOW(), updated_at = NOW()
            WHERE run_id = (
                SELECT run_id FROM alpatrade.autonomy_runs
                WHERE status = 'queued'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING run_id, kind, config, attempt
        """), {"w": worker_id}).fetchone()
    if not row:
        return None
    return {"run_id": str(row[0]), "kind": row[1], "config": row[2], "attempt": row[3]}


def heartbeat(run_id: str, worker_id: str) -> None:
    with _pool().get_session() as s:
        s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET heartbeat_at = NOW(), updated_at = NOW()
            WHERE run_id = :rid AND claimed_by = :w
        """), {"rid": run_id, "w": worker_id})


def ack(run_id: str) -> None:
    with _pool().get_session() as s:
        s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET status = 'done', updated_at = NOW()
            WHERE run_id = :rid
        """), {"rid": run_id})


def fail(run_id: str, error: str, max_attempts: int = 3) -> str:
    """Requeue for retry, or mark 'failed' once attempts are exhausted. Returns new status."""
    with _pool().get_session() as s:
        new_status = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET
                status = CASE WHEN attempt >= :maxa THEN 'failed' ELSE 'queued' END,
                claimed_by = NULL, error = :err, updated_at = NOW()
            WHERE run_id = :rid
            RETURNING status
        """), {"maxa": max_attempts, "err": error[:2000], "rid": run_id}).scalar()
    return new_status or "failed"


def requeue_unfinished(stale_seconds: int = 300) -> int:
    """Return runs stuck in 'running' with a stale heartbeat back to 'queued'."""
    with _pool().get_session() as s:
        n = s.execute(text("""
            UPDATE alpatrade.autonomy_runs SET status = 'queued', claimed_by = NULL,
                   updated_at = NOW()
            WHERE status = 'running'
              AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - (:sec * INTERVAL '1 second'))
        """), {"sec": stale_seconds}).rowcount
    return n or 0
