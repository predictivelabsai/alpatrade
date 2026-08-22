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
                   candidate_id, config, progress, result, error, control_requested,
                   paused_at, created_at,
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
                   candidate_id, config, progress, result, error, control_requested,
                   paused_at, created_at,
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


def request_control(job_id: str, user_id: str, action: str) -> Optional[dict]:
    """Pause, resume, or stop one owned paper job without touching other users."""
    if action not in {"pause", "resume", "stop"}:
        raise ValueError("action must be pause, resume, or stop")
    with _pool().get_session() as session:
        if action == "pause":
            row = session.execute(text("""
                UPDATE alpatrade.hermes_jobs
                SET control_requested = 'pause', status = 'paused', paused_at = NOW(),
                    progress = '{"message":"Paused by user"}'::jsonb, updated_at = NOW()
                WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
                  AND kind = 'paper' AND status IN ('queued', 'running')
                RETURNING *
            """), {"job_id": job_id, "uid": user_id}).mappings().first()
        elif action == "resume":
            row = session.execute(text("""
                UPDATE alpatrade.hermes_jobs
                SET control_requested = 'none',
                    status = CASE WHEN claimed_by IS NULL THEN 'queued' ELSE 'running' END,
                    paused_at = NULL, progress = '{"message":"Resumed by user"}'::jsonb,
                    updated_at = NOW()
                WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
                  AND kind = 'paper' AND status = 'paused'
                RETURNING *
            """), {"job_id": job_id, "uid": user_id}).mappings().first()
        else:
            row = session.execute(text("""
                UPDATE alpatrade.hermes_jobs
                SET control_requested = 'stop',
                    status = CASE WHEN status IN ('queued', 'paused') AND claimed_by IS NULL
                                  THEN 'stopped' ELSE status END,
                    completed_at = CASE WHEN status IN ('queued', 'paused') AND claimed_by IS NULL
                                        THEN NOW() ELSE completed_at END,
                    progress = '{"message":"Stop requested by user"}'::jsonb,
                    updated_at = NOW()
                WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
                  AND kind = 'paper' AND status IN ('queued', 'running', 'paused')
                RETURNING *
            """), {"job_id": job_id, "uid": user_id}).mappings().first()
    return _job_dict(row) if row else None


def set_email_reports(job_id: str, user_id: str, enabled: bool) -> Optional[dict]:
    """Enable daily reports for one owned paper job using its owner's login email."""
    from engine.auth import get_user_by_id

    user = get_user_by_id(user_id) or {}
    recipient = str(user.get("email") or "") if enabled else ""
    if enabled and not recipient:
        raise ValueError("Your login account has no report email")
    patch = json.dumps({"email_notifications": enabled})
    with _pool().get_session() as session:
        row = session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET config = config || CAST(:patch AS JSONB), updated_at = NOW()
            WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
              AND kind = 'paper' AND status IN ('queued', 'running', 'paused')
            RETURNING *
        """), {"job_id": job_id, "uid": user_id, "patch": patch}).mappings().first()
    return _job_dict(row) if row else None


def set_notification_channel(job_id: str, user_id: str, channel: str) -> Optional[dict]:
    """Choose in-app, email, both, or no Hermes advice alerts for an owned job."""
    from engine.agents.hermes_advice import normalize_channel
    from engine.auth import get_user_by_id

    channel = normalize_channel(channel)
    if channel in {"email", "both"} and not (get_user_by_id(user_id) or {}).get("email"):
        raise ValueError("Your login account has no notification email")
    patch = json.dumps({
        "advice_enabled": channel != "none",
        "notification_channel": channel,
    })
    with _pool().get_session() as session:
        row = session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET config = config || CAST(:patch AS JSONB), updated_at = NOW()
            WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
              AND kind = 'paper' AND status IN ('queued', 'running', 'paused')
            RETURNING *
        """), {"job_id": job_id, "uid": user_id, "patch": patch}).mappings().first()
    return _job_dict(row) if row else None


def enqueue_candidate_paper(
    candidate_id: str,
    user_id: str,
    thread_id: str,
    *,
    duration: str = "365d",
    poll: int = 60,
    email_reports: bool = False,
    account_id: Optional[str] = None,
    extended_hours: Optional[bool] = None,
    pdt_protection: bool = True,
    notification_channel: str = "in_app",
) -> dict:
    """Validate ownership/account credentials and queue an owned paper candidate."""
    from agents.orchestrator import parse_duration
    from engine.auth import get_alpaca_keys, get_user_accounts, get_user_by_id

    with _pool().get_session() as session:
        candidate = session.execute(text("""
            SELECT strategy, symbols, params, account_id, source_run_id
            FROM alpatrade.strategy_candidates
            WHERE candidate_id = CAST(:candidate_id AS UUID)
              AND user_id = CAST(:uid AS UUID)
        """), {"candidate_id": candidate_id, "uid": user_id}).mappings().first()
    if not candidate:
        raise ValueError("Candidate was not found under your account")
    owned_accounts = get_user_accounts(user_id)
    owned_ids = {str(item["account_id"]) for item in owned_accounts}
    if account_id and account_id not in owned_ids:
        raise ValueError("Paper account was not found under your account")
    account_id = account_id or (
        str(candidate["account_id"]) if candidate.get("account_id") else None
    )
    if not account_id:
        account_id = str(owned_accounts[0]["account_id"]) if owned_accounts else None
    if not account_id or not get_alpaca_keys(user_id, account_id):
        raise ValueError("Link an Alpaca paper account before starting paper trading")
    from engine.agents.hermes_advice import normalize_channel
    notification_channel = normalize_channel(notification_channel)
    user = get_user_by_id(user_id) or {}
    report_email = str(user.get("email") or "") if (
        email_reports or notification_channel in {"email", "both"}
    ) else ""
    if (email_reports or notification_channel in {"email", "both"}) and not report_email:
        raise ValueError("Your login account has no report email")
    config = {
        "duration_seconds": parse_duration(duration),
        "continuous": duration == "365d",
        "symbols": candidate["symbols"] or [],
        "strategy": candidate["strategy"],
        "params": candidate["params"] or {},
        "source_run_id": candidate["source_run_id"],
        "poll_interval_seconds": poll,
        "email_notifications": email_reports,
        "advice_enabled": notification_channel != "none",
        "notification_channel": notification_channel,
        "advice_interval_seconds": 900,
        "report_hour_utc": 21,
        "agent_name": "Hermes",
        "agent_framework": "hermes",
        "pdt_protection": pdt_protection,
    }
    if extended_hours is not None:
        config["extended_hours"] = extended_hours
    job = enqueue(
        "paper", user_id, thread_id, config,
        account_id=account_id, candidate_id=candidate_id,
    )
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.strategy_candidates
            SET status = 'paper', updated_at = NOW()
            WHERE candidate_id = CAST(:candidate_id AS UUID)
              AND user_id = CAST(:uid AS UUID)
        """), {"candidate_id": candidate_id, "uid": user_id})
    return {**job, "candidate_id": candidate_id, "account_id": account_id,
            "email_reports": email_reports}


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
            WHERE job_id = CAST(:job_id AS UUID) AND status IN ('running', 'paused')
        """), {"job_id": job_id,
                "progress": json.dumps({"message": message})})


class DatabaseJobControl:
    """Cooperative paper control that survives web/worker process boundaries."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def _state(self) -> tuple[str, str]:
        with _pool().get_session() as session:
            row = session.execute(text("""
                SELECT status, control_requested FROM alpatrade.hermes_jobs
                WHERE job_id = CAST(:job_id AS UUID)
            """), {"job_id": self.job_id}).first()
        return (str(row[0]), str(row[1])) if row else ("stopped", "stop")

    def is_set(self) -> bool:
        status, control = self._state()
        return control == "stop" or status in {"stopped", "cancelled", "failed"}

    def wait_if_paused(self) -> bool:
        """Block cooperatively while paused; return False when stop is requested."""
        while True:
            status, control = self._state()
            if control == "stop" or status in {"stopped", "cancelled", "failed"}:
                return False
            if control != "pause" and status != "paused":
                return True
            heartbeat(self.job_id, "Paper trading paused")
            time.sleep(2)

    def report_target(self) -> tuple[bool, str]:
        with _pool().get_session() as session:
            row = session.execute(text("""
                SELECT j.config, u.email
                FROM alpatrade.hermes_jobs j
                JOIN alpatrade.users u ON u.user_id = j.user_id
                WHERE j.job_id = CAST(:job_id AS UUID)
            """), {"job_id": self.job_id}).first()
        config = row[0] if row else {}
        return bool(config.get("email_notifications")), str(row[1] or "") if row else ""

    def advice_settings(self) -> dict:
        """Resolve mutable advice preferences and owner context at delivery time."""
        with _pool().get_session() as session:
            row = session.execute(text("""
                SELECT j.user_id, j.account_id, j.thread_id, j.candidate_id,
                       j.run_id, j.config, u.email
                FROM alpatrade.hermes_jobs j
                JOIN alpatrade.users u ON u.user_id = j.user_id
                WHERE j.job_id = CAST(:job_id AS UUID)
            """), {"job_id": self.job_id}).mappings().first()
        if not row:
            return {"enabled": False}
        config = dict(row["config"] or {})
        return {
            "enabled": bool(config.get("advice_enabled", False)),
            "channel": config.get("notification_channel", "in_app"),
            "interval_seconds": max(60, int(config.get("advice_interval_seconds", 900))),
            "user_id": str(row["user_id"]),
            "account_id": str(row["account_id"]) if row["account_id"] else None,
            "thread_id": str(row["thread_id"]) if row["thread_id"] else None,
            "candidate_id": str(row["candidate_id"]) if row["candidate_id"] else None,
            "job_id": self.job_id,
            "run_id": str(row["run_id"]),
            "config": config,
            "email": str(row["email"] or ""),
        }

    def publish_advice(self, items: list[dict]) -> list[dict]:
        """Persist new advice and deliver actionable changes via the selected channels."""
        from engine.agents.hermes_advice import (
            build_advice_alert_email, save_advice, mark_delivered,
        )
        settings = self.advice_settings()
        if not settings.get("enabled") or not items:
            return []
        saved = []
        with _pool().get_session() as session:
            for item in items:
                duplicate = session.execute(text("""
                    SELECT 1 FROM alpatrade.hermes_advice
                    WHERE job_id = CAST(:job_id AS UUID) AND symbol IS NOT DISTINCT FROM :symbol
                      AND action = :action AND created_at > NOW() - INTERVAL '6 hours'
                    LIMIT 1
                """), {"job_id": self.job_id, "symbol": item.get("symbol"),
                        "action": item["action"]}).first()
                if not duplicate:
                    saved.append(item)
        ids = []
        for item in saved:
            ids.append(save_advice(
                user_id=settings["user_id"], account_id=settings["account_id"],
                job_id=self.job_id, candidate_id=settings["candidate_id"],
                thread_id=settings["thread_id"], symbol=item.get("symbol"),
                advice_type=item["advice_type"], action=item["action"],
                severity=item["severity"], summary=item["summary"],
                rationale=item["rationale"], snapshot=item.get("snapshot") or {},
            ))
        actionable = [(item, aid) for item, aid in zip(saved, ids)
                      if item.get("severity") in {"watch", "action"}
                      and item.get("action") != "WATCH_ENTRY"]
        channel = settings["channel"]
        if actionable and channel in {"in_app", "both"} and settings["thread_id"]:
            from engine.ai.chat_store import save_message
            body = "## Hermes portfolio advice\n\n" + "\n".join(
                f"- **{item['summary']}** — {item['rationale']}" for item, _ in actionable
            ) + "\n\nAdvice only; no additional order was placed."
            save_message(settings["thread_id"], "assistant", body, metadata={
                "agent": "Hermes", "framework": "hermes", "job_id": self.job_id,
                "event": "portfolio_advice",
            })
            mark_delivered([aid for _, aid in actionable], in_app=True)
        if actionable and channel in {"email", "both"} and settings["email"]:
            from utils.email_util import send_email_to
            subject, body = build_advice_alert_email(
                [item for item, _ in actionable], settings
            )
            if send_email_to(settings["email"], subject, body):
                mark_delivered([aid for _, aid in actionable], email=True)
        return saved

    def recent_advice(self, limit: int = 20) -> list[dict]:
        settings = self.advice_settings()
        if not settings.get("user_id"):
            return []
        from engine.agents.hermes_advice import list_owned
        return list_owned(settings["user_id"], job_id=self.job_id, limit=limit)


def finish(
    job_id: str,
    result: dict,
    candidate_id: Optional[str] = None,
    *,
    status: str = "completed",
) -> None:
    progress = json.dumps({"message": "Stopped" if status == "stopped" else "Completed"})
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = :status, result = CAST(:result AS JSONB),
                candidate_id = COALESCE(CAST(:candidate_id AS UUID), candidate_id),
                progress = CAST(:progress AS JSONB),
                completed_at = NOW(), heartbeat_at = NOW(), updated_at = NOW()
            WHERE job_id = CAST(:job_id AS UUID)
        """), {"job_id": job_id, "status": status, "progress": progress,
                "result": json.dumps(result, default=str),
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
    """Retry backtests and explicitly continuous paper jobs after worker restarts."""
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
            SET status = 'queued', claimed_by = NULL,
                progress = '{"message":"Continuous paper job requeued after worker restart"}'::jsonb,
                updated_at = NOW()
            WHERE status = 'running' AND kind = 'paper'
              AND COALESCE((config->>'continuous')::boolean, FALSE) = TRUE
              AND control_requested = 'none'
              AND heartbeat_at < NOW() - (CAST(:seconds AS INTEGER) * INTERVAL '1 second')
        """), {"seconds": stale_seconds})
        session.execute(text("""
            UPDATE alpatrade.hermes_jobs
            SET status = 'failed',
                error = 'Paper worker interrupted; not replayed to avoid duplicate orders',
                progress = '{"message":"Stopped safely after worker interruption"}'::jsonb,
                completed_at = NOW(), updated_at = NOW()
            WHERE status = 'running' AND kind = 'paper'
              AND COALESCE((config->>'continuous')::boolean, FALSE) = FALSE
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
    result = orch.run_paper_trade(config, stop_event=DatabaseJobControl(str(job["job_id"])))
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
        final_status = "stopped" if job["kind"] == "paper" and DatabaseJobControl(job_id).is_set() else "completed"
        if final_status == "stopped":
            markdown = markdown.replace(
                "## Hermes paper session completed", "## Hermes paper session stopped", 1
            )
        finish(job_id, result, candidate_id, status=final_status)
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
