"""Durable asynchronous jobs for the scoped Hermes trading broker."""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from engine.db.pool import DatabasePool

log = logging.getLogger("hermes.jobs")


def _pool() -> DatabasePool:
    return DatabasePool()


def enqueue(
    kind: str,
    user_id: str,
    thread_id: str,
    config: dict,
    *,
    account_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> dict:
    """Create one owned job and reserve its execution run ID."""
    run_id = str(uuid.uuid4())
    with _pool().get_session() as session:
        row = session.execute(text("""
            INSERT INTO alpatrade.hermes_jobs
                (run_id, kind, user_id, account_id, thread_id, candidate_id,
                 config, progress)
            VALUES
                (:run_id, :kind, CAST(:uid AS UUID), CAST(:aid AS UUID),
                 CAST(:tid AS UUID), CAST(:candidate_id AS UUID),
                 CAST(:config AS JSONB), '{"message":"Queued"}'::jsonb)
            RETURNING job_id, created_at
        """), {
            "run_id": run_id, "kind": kind, "uid": user_id,
            "aid": account_id, "tid": thread_id, "candidate_id": candidate_id,
            "config": json.dumps(config, default=str),
        }).mappings().one()
    return {"job_id": str(row["job_id"]), "run_id": run_id,
            "status": "queued", "kind": kind, "created_at": row["created_at"]}


def list_owned(user_id: str, *, limit: int = 50) -> list[dict]:
    with _pool().get_session() as session:
        rows = session.execute(text("""
            SELECT job_id, run_id, kind, status, account_id, thread_id,
                   candidate_id, progress, result, error, created_at,
                   started_at, completed_at
            FROM alpatrade.hermes_jobs
            WHERE user_id = CAST(:uid AS UUID)
            ORDER BY created_at DESC LIMIT :limit
        """), {"uid": user_id, "limit": limit}).mappings().all()
    return [_job_dict(row) for row in rows]


def get_owned(job_id: str, user_id: str) -> Optional[dict]:
    with _pool().get_session() as session:
        row = session.execute(text("""
            SELECT job_id, run_id, kind, status, account_id, thread_id,
                   candidate_id, progress, result, error, created_at,
                   started_at, completed_at
            FROM alpatrade.hermes_jobs
            WHERE job_id = CAST(:job_id AS UUID)
              AND user_id = CAST(:uid AS UUID)
        """), {"job_id": job_id, "uid": user_id}).mappings().first()
    return _job_dict(row) if row else None


def _job_dict(row) -> dict:
    return {key: (str(value) if key in {"job_id", "account_id", "thread_id",
                                        "candidate_id"} and value is not None else value)
            for key, value in dict(row).items()}


def claim(worker_id: str) -> Optional[dict]:
    """Atomically claim the oldest queued job across worker replicas."""
    with _pool().get_session() as session:
        row = session.execute(text("""
            WITH next_job AS (
                SELECT job_id FROM alpatrade.hermes_jobs
                WHERE status = 'queued' ORDER BY created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE alpatrade.hermes_jobs j
            SET status = 'running', claimed_by = :worker,
                started_at = COALESCE(started_at, NOW()), heartbeat_at = NOW(),
                progress = '{"message":"Worker started"}'::jsonb,
                updated_at = NOW()
            FROM next_job n WHERE j.job_id = n.job_id
            RETURNING j.*
        """), {"worker": worker_id}).mappings().first()
    return dict(row) if row else None


def heartbeat(job_id: str, message: str) -> None:
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET heartbeat_at = NOW(), updated_at = NOW(),
                progress = CAST(:progress AS JSONB)
            WHERE job_id = CAST(:job_id AS UUID) AND status = 'running'
        """), {"job_id": job_id,
                "progress": json.dumps({"message": message})})


def finish(job_id: str, result: dict, candidate_id: Optional[str] = None) -> None:
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = 'completed', result = CAST(:result AS JSONB),
                candidate_id = COALESCE(CAST(:candidate_id AS UUID), candidate_id),
                progress = '{"message":"Completed"}'::jsonb,
                completed_at = NOW(), heartbeat_at = NOW(), updated_at = NOW()
            WHERE job_id = CAST(:job_id AS UUID)
        """), {"job_id": job_id, "result": json.dumps(result, default=str),
                "candidate_id": candidate_id})


def fail(job_id: str, error: str) -> None:
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = 'failed', error = :error,
                progress = '{"message":"Failed"}'::jsonb,
                completed_at = NOW(), heartbeat_at = NOW(), updated_at = NOW()
            WHERE job_id = CAST(:job_id AS UUID)
        """), {"job_id": job_id, "error": error[:4000]})


def recover_stale(stale_seconds: int = 900) -> None:
    """Retry interrupted backtests; fail paper safely instead of replaying orders."""
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = 'queued', claimed_by = NULL,
                progress = '{"message":"Requeued after worker restart"}'::jsonb,
                updated_at = NOW()
            WHERE status = 'running' AND kind = 'backtest'
              AND heartbeat_at < NOW() - (CAST(:seconds AS INTEGER) * INTERVAL '1 second')
        """), {"seconds": stale_seconds})
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = 'failed',
                error = 'Paper worker interrupted; not replayed to avoid duplicate orders',
                progress = '{"message":"Stopped safely after worker interruption"}'::jsonb,
                completed_at = NOW(), updated_at = NOW()
            WHERE status = 'running' AND kind = 'paper'
              AND heartbeat_at < NOW() - (CAST(:seconds AS INTEGER) * INTERVAL '1 second')
        """), {"seconds": stale_seconds})


def _save_candidate(job: dict, result: dict) -> Optional[str]:
    best = result.get("best_config") or {}
    params = best.get("params") or {}
    if not params:
        return None
    metrics = {key: value for key, value in best.items() if key != "params"}
    config = job.get("config") or {}
    with _pool().get_session() as session:
        candidate_id = session.execute(text("""
            INSERT INTO alpatrade.strategy_candidates
                (user_id, account_id, source_run_id, agent_name,
                 agent_framework, strategy, symbols, params, metrics, objective)
            VALUES
                (CAST(:uid AS UUID), CAST(:aid AS UUID), :run_id, 'Hermes',
                 'hermes', :strategy, CAST(:symbols AS JSONB),
                 CAST(:params AS JSONB), CAST(:metrics AS JSONB),
                 CAST(:objective AS JSONB))
            RETURNING candidate_id
        """), {
            "uid": str(job["user_id"]), "aid": job.get("account_id"),
            "run_id": job["run_id"], "strategy": config.get("strategy", "buy_the_dip"),
            "symbols": json.dumps(config.get("symbols") or []),
            "params": json.dumps(params, default=str),
            "metrics": json.dumps(metrics, default=str),
            "objective": json.dumps(config.get("objective") or {}, default=str),
        }).scalar_one()
    return str(candidate_id)


def _notify(job: dict, markdown: str, *, failed: bool = False) -> None:
    thread_id = job.get("thread_id")
    if not thread_id:
        return
    try:
        from engine.ai.chat_store import save_message
        save_message(str(thread_id), "assistant", markdown, metadata={
            "agent": "Hermes", "framework": "hermes",
            "job_id": str(job["job_id"]), "job_status": "failed" if failed else "completed",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not notify chat for job %s: %s", job["job_id"], exc)


def _backtest(job: dict) -> tuple[dict, Optional[str], str]:
    from agents.orchestrator import Orchestrator
    config = dict(job.get("config") or {})
    config.update({"agent_name": "Hermes", "agent_framework": "hermes"})
    orch = Orchestrator(user_id=str(job["user_id"]),
                        account_id=str(job["account_id"]) if job.get("account_id") else None)
    orch.run_id = job["run_id"]
    orch.state.run_id = job["run_id"]
    result = orch.run_backtest(config)
    if result.get("error"):
        raise RuntimeError(result["error"])
    candidate_id = _save_candidate(job, result)
    best = result.get("best_config") or {}
    markdown = (
        "## Hermes backtest completed\n\n"
        f"- **Job ID:** `{job['job_id']}`\n- **Run ID:** `{job['run_id']}`\n"
        f"- **Candidate ID:** `{candidate_id or 'not created'}`\n"
        f"- **Best parameters:** `{json.dumps(best.get('params') or {}, default=str)}`\n"
        f"- **Sharpe ratio:** {best.get('sharpe_ratio', 'n/a')}\n"
        f"- **Total return:** {best.get('total_return', 'n/a')}\n"
        f"- **Maximum drawdown:** {best.get('max_drawdown', 'n/a')}\n"
        f"- **Win rate:** {best.get('win_rate', 'n/a')}\n"
        f"- **Trades:** {best.get('total_trades', 'n/a')}\n\n"
        "You can now ask Hermes to start this candidate in paper trading."
    )
    return result, candidate_id, markdown


def _paper(job: dict) -> tuple[dict, Optional[str], str]:
    from agents.orchestrator import Orchestrator
    config = dict(job.get("config") or {})
    config.update({"agent_name": "Hermes", "agent_framework": "hermes"})
    orch = Orchestrator(user_id=str(job["user_id"]),
                        account_id=str(job["account_id"]) if job.get("account_id") else None)
    orch.run_id = job["run_id"]
    orch.state.run_id = job["run_id"]
    orch.state.best_config = {"params": config.get("params") or {}}
    result = orch.run_paper_trade(config)
    if result.get("error"):
        raise RuntimeError(result["error"])
    markdown = (
        "## Hermes paper session completed\n\n"
        f"- **Job ID:** `{job['job_id']}`\n- **Run ID:** `{job['run_id']}`\n"
        f"- **Candidate ID:** `{job.get('candidate_id')}`\n"
        f"- **Trades:** {result.get('total_trades', 0)}\n"
        f"- **P&L:** {result.get('total_pnl', 0)}\n"
    )
    return result, str(job.get("candidate_id")) if job.get("candidate_id") else None, markdown


def run_one(worker_id: str) -> bool:
    job = claim(worker_id)
    if not job:
        return False
    job_id = str(job["job_id"])
    stopped = threading.Event()

    def pulse() -> None:
        started = time.monotonic()
        while not stopped.wait(15):
            heartbeat(job_id, f"{job['kind'].title()} running ({int(time.monotonic()-started)}s)")

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        if job["kind"] == "backtest":
            result, candidate_id, markdown = _backtest(job)
        else:
            result, candidate_id, markdown = _paper(job)
        finish(job_id, result, candidate_id)
        _notify(job, markdown)
    except Exception as exc:  # noqa: BLE001
        log.exception("Hermes job %s failed", job_id)
        fail(job_id, str(exc))
        _notify(job, f"## Hermes {job['kind']} failed\n\nJob `{job_id}`: {exc}", failed=True)
    finally:
        stopped.set()
        thread.join(timeout=1)
    return True


def loop() -> None:
    worker_id = os.getenv("HERMES_JOBS_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
    poll = float(os.getenv("HERMES_JOBS_POLL_SECONDS", "2"))
    log.info("Hermes jobs worker %s starting", worker_id)
    last_recovery = 0.0
    while True:
        try:
            if time.monotonic() - last_recovery > 60:
                recover_stale(int(os.getenv("HERMES_JOBS_STALE_SECONDS", "900")))
                last_recovery = time.monotonic()
            if not run_one(worker_id):
                time.sleep(poll)
        except Exception:  # noqa: BLE001
            log.exception("Hermes jobs worker loop error")
            time.sleep(min(poll, 5))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop()
