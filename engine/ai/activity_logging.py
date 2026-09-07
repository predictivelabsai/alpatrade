"""Tenant-safe prompt/response and agent activity history."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text

from engine.db.pool import get_pool

_SECRET_PATTERNS = (
    re.compile(r"\bxai-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(api[_ -]?key|secret|token|password)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+\S+"),
)
_MAX_TEXT = 50_000


def redact_text(value: Any) -> str:
    """Bound log size and redact common credential-shaped values."""
    result = str(value or "")[:_MAX_TEXT]
    result = _SECRET_PATTERNS[0].sub("[REDACTED_XAI_KEY]", result)
    result = _SECRET_PATTERNS[1].sub(r"\1=[REDACTED]", result)
    return _SECRET_PATTERNS[2].sub("Bearer [REDACTED]", result)


def start_user_log(user_id: str, thread_id: str, request_text: str) -> str | None:
    if not user_id or not request_text:
        return None
    with get_pool().get_session() as session:
        value = session.execute(text("""
            INSERT INTO alpatrade.user_logging
                (user_id, thread_id, request_text)
            VALUES
                (CAST(:uid AS UUID), CAST(:thread_id AS UUID), :request_text)
            RETURNING log_id
        """), {
            "uid": user_id, "thread_id": thread_id,
            "request_text": redact_text(request_text),
        }).scalar_one()
    return str(value)


def complete_user_log(
    user_id: str, thread_id: str, response_text: str,
    metadata: dict | None = None,
) -> None:
    """Complete the latest pending message in the same owned thread."""
    if not user_id:
        return
    meta = dict(metadata or {})
    status = (
        "blocked" if meta.get("code") == "query_limit_exceeded"
        else "failed" if meta.get("error") else "completed"
    )
    framework = str(meta.get("framework") or meta.get("agent") or "unknown")[:64]
    error = redact_text(response_text) if status in {"failed", "blocked"} else None
    safe_meta = {
        key: value for key, value in meta.items()
        if key in {"dispatch", "code", "framework", "agent"}
    }
    with get_pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.user_logging SET
                response_text = :response_text,
                agent_framework = :framework,
                status = :status,
                error = :error,
                metadata = CAST(:metadata AS JSONB),
                completed_at = NOW()
            WHERE log_id = (
                SELECT log_id FROM alpatrade.user_logging
                WHERE user_id = CAST(:uid AS UUID)
                  AND thread_id = CAST(:thread_id AS UUID)
                  AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            )
        """), {
            "uid": user_id, "thread_id": thread_id,
            "response_text": redact_text(response_text), "framework": framework,
            "status": status, "error": error,
            "metadata": json.dumps(safe_meta, default=str),
        })


def list_user_logs(
    requester_id: str, *, is_admin: bool, limit: int = 100,
    email: str = "",
) -> list[dict]:
    """Admins may query all users; everyone else is forcibly owner-scoped."""
    owner_filter = "" if is_admin else "AND l.user_id = CAST(:requester_id AS UUID)"
    email_filter = ""
    params: dict[str, Any] = {
        "requester_id": requester_id, "limit": max(1, min(int(limit), 500)),
    }
    if is_admin and email.strip():
        email_filter = "AND u.email ILIKE :email"
        params["email"] = f"%{email.strip()}%"
    with get_pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT l.log_id, l.user_id, u.email, l.thread_id, l.request_text,
                   l.response_text, l.agent_framework, l.status, l.error,
                   l.created_at, l.completed_at
            FROM alpatrade.user_logging l
            JOIN alpatrade.users u ON u.user_id = l.user_id
            WHERE TRUE {owner_filter} {email_filter}
            ORDER BY l.created_at DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(row) for row in rows]


def list_agent_logs(
    requester_id: str, *, is_admin: bool, limit: int = 100,
    email: str = "",
) -> list[dict]:
    owner_filter = "" if is_admin else "AND l.user_id = CAST(:requester_id AS UUID)"
    email_filter = ""
    params: dict[str, Any] = {
        "requester_id": requester_id, "limit": max(1, min(int(limit), 500)),
    }
    if is_admin and email.strip():
        email_filter = "AND u.email ILIKE :email"
        params["email"] = f"%{email.strip()}%"
    with get_pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT l.log_id, l.user_id, u.email, l.agent_framework,
                   l.operation_type, l.job_id, l.run_id, l.status, l.details,
                   l.error, l.started_at, l.completed_at, l.updated_at
            FROM alpatrade.agent_logging l
            LEFT JOIN alpatrade.users u ON u.user_id = l.user_id
            WHERE TRUE {owner_filter} {email_filter}
            ORDER BY l.updated_at DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(row) for row in rows]
