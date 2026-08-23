"""Tenant-safe durable storage for the canonical DeepAgents API."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from engine.db.pool import DatabasePool


class DeepAgentStoreError(RuntimeError):
    """Base class for expected durable-chat conflicts."""


class ThreadAccessError(DeepAgentStoreError):
    pass


class AccountAccessError(DeepAgentStoreError):
    pass


class MessageConflictError(DeepAgentStoreError):
    pass


class ResponseInProgressError(DeepAgentStoreError):
    pass


@dataclass(frozen=True)
class ResponseRecord:
    response_id: str
    thread_id: str
    request_message_id: str
    status: str
    provider: str
    model: str
    payload: Optional[dict[str, Any]] = None
    request_fingerprint: str = ""


@dataclass(frozen=True)
class ActionRecord:
    action_id: str
    status: str
    job_id: Optional[str]
    order_client_id: Optional[str]
    created: bool


class PostgresDeepAgentStore:
    """Small SQL store with ownership checks on every tenant-bearing query."""

    def __init__(self, pool: Optional[DatabasePool] = None) -> None:
        self.pool = pool or DatabasePool()

    def validate_account(self, user_id: str, account_id: Optional[str]) -> None:
        if not account_id:
            return
        with self.pool.get_session() as session:
            owned = session.execute(text("""
                SELECT 1
                FROM alpatrade.user_accounts
                WHERE user_id = :uid AND account_id = :aid AND is_active = TRUE
            """), {"uid": user_id, "aid": account_id}).scalar()
        if not owned:
            raise AccountAccessError("account_id is not owned by the authenticated user")

    def ensure_thread(self, user_id: str, thread_id: str, title: str) -> None:
        """Create a thread or prove that the existing thread belongs to user_id."""
        with self.pool.get_session() as session:
            session.execute(text("""
                INSERT INTO alpatrade.chat_conversations
                    (thread_id, user_id, title, updated_at)
                VALUES (:tid, :uid, :title, NOW())
                ON CONFLICT (thread_id) DO NOTHING
            """), {
                "tid": thread_id,
                "uid": user_id,
                "title": (title.strip() or "New chat")[:200],
            })
            row = session.execute(text("""
                SELECT user_id FROM alpatrade.chat_conversations
                WHERE thread_id = :tid
            """), {"tid": thread_id}).fetchone()
            if row is None or row[0] is None or str(row[0]) != user_id:
                raise ThreadAccessError("thread_id is owned by another user")

    def append_messages(
        self,
        user_id: str,
        thread_id: str,
        messages: Iterable[dict[str, str]],
    ) -> None:
        """Append one new batch atomically; reject any previously appended id."""
        batch = list(messages)
        identifiers = [message["id"] for message in batch]
        with self.pool.get_session() as session:
            owner = session.execute(text("""
                SELECT user_id FROM alpatrade.chat_conversations
                WHERE thread_id = :tid
            """), {"tid": thread_id}).scalar()
            if owner is None or str(owner) != user_id:
                raise ThreadAccessError("thread_id is not owned by the authenticated user")
            existing: dict[str, tuple[str, str]] = {}
            if identifiers:
                rows = session.execute(text("""
                    SELECT message_id, role, content
                    FROM alpatrade.chat_messages
                    WHERE thread_id = :tid AND message_id = ANY(CAST(:ids AS UUID[]))
                """), {"tid": thread_id, "ids": identifiers}).fetchall()
                existing = {str(row[0]): (row[1], row[2]) for row in rows}
            for message in batch:
                prior = existing.get(message["id"])
                current = (message["role"], message["content"])
                if prior is not None:
                    if prior != current:
                        raise MessageConflictError(
                            "a message id already exists with different role or content"
                        )
                    raise MessageConflictError(
                        "a message id has already been appended to this thread"
                    )
                session.execute(text("""
                    INSERT INTO alpatrade.chat_messages
                        (thread_id, message_id, role, content, metadata)
                    VALUES (:tid, :mid, :role, :content, CAST(:metadata AS JSONB))
                    ON CONFLICT (thread_id, message_id) DO NOTHING
                """), {
                    "tid": thread_id,
                    "mid": message["id"],
                    "role": message["role"],
                    "content": message["content"],
                    "metadata": json.dumps({"source": "deepagents-api"}),
                })
            session.execute(text("""
                UPDATE alpatrade.chat_conversations SET updated_at = NOW()
                WHERE thread_id = :tid AND user_id = :uid
            """), {"tid": thread_id, "uid": user_id})

    def load_messages(self, user_id: str, thread_id: str) -> list[dict[str, Any]]:
        with self.pool.get_session() as session:
            rows = session.execute(text("""
                SELECT m.message_id, m.role, m.content, m.created_at
                FROM alpatrade.chat_messages m
                JOIN alpatrade.chat_conversations c ON c.thread_id = m.thread_id
                WHERE m.thread_id = :tid AND c.user_id = :uid
                ORDER BY m.created_at ASC, m.id ASC
            """), {"tid": thread_id, "uid": user_id}).fetchall()
        return [
            {
                "id": str(row[0]),
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]

    def find_response(
        self,
        user_id: str,
        thread_id: str,
        request_message_id: str,
    ) -> Optional[ResponseRecord]:
        with self.pool.get_session() as session:
            row = session.execute(text("""
                SELECT response_id, thread_id, request_message_id,
                       request_fingerprint, status, model_provider, model_name,
                       response_payload
                FROM alpatrade.deepagent_responses
                WHERE user_id = :uid AND thread_id = :tid
                  AND request_message_id = :mid
            """), {
                "uid": user_id,
                "tid": thread_id,
                "mid": request_message_id,
            }).fetchone()
        return self._record(row) if row else None

    def begin_response(
        self,
        *,
        user_id: str,
        thread_id: str,
        request_message_id: str,
        account_id: Optional[str],
        request_id: str,
        auth_type: str,
        provider: str,
        model: str,
        process_instance_id: str,
        request_fingerprint: str,
    ) -> ResponseRecord:
        cached = self.find_response(user_id, thread_id, request_message_id)
        if cached:
            if cached.status == "running":
                raise ResponseInProgressError("response_in_progress")
            return cached

        response_id = str(uuid.uuid4())
        try:
            with self.pool.get_session() as session:
                row = session.execute(text("""
                    INSERT INTO alpatrade.deepagent_responses (
                        response_id, user_id, thread_id, request_message_id,
                        request_fingerprint, account_id, request_id, auth_type,
                        process_instance_id,
                        status, model_provider, model_name
                    ) VALUES (
                        :rid, :uid, :tid, :mid, :fingerprint, :aid, :request_id,
                        :auth_type, :process_id, 'running', :provider, :model
                    )
                    RETURNING response_id, thread_id, request_message_id,
                              request_fingerprint, status, model_provider,
                              model_name, response_payload
                """), {
                    "rid": response_id,
                    "uid": user_id,
                    "tid": thread_id,
                    "mid": request_message_id,
                    "fingerprint": request_fingerprint,
                    "aid": account_id,
                    "request_id": request_id,
                    "auth_type": auth_type,
                    "process_id": process_instance_id,
                    "provider": provider,
                    "model": model,
                }).fetchone()
            return self._record(row)
        except IntegrityError as exc:
            cached = self.find_response(user_id, thread_id, request_message_id)
            if cached and cached.status != "running":
                return cached
            raise ResponseInProgressError("response_in_progress") from exc

    def heartbeat(self, user_id: str, response_id: str) -> None:
        with self.pool.get_session() as session:
            session.execute(text("""
                UPDATE alpatrade.deepagent_responses
                SET heartbeat_at = NOW()
                WHERE response_id = :rid AND user_id = :uid AND status = 'running'
            """), {"rid": response_id, "uid": user_id})

    def complete_response(
        self,
        user_id: str,
        response_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self.pool.get_session() as session:
            updated = session.execute(text("""
                UPDATE alpatrade.deepagent_responses
                SET status = 'completed', response_payload = CAST(:payload AS JSONB),
                    completed_at = NOW(), heartbeat_at = NOW()
                WHERE response_id = :rid AND user_id = :uid AND status = 'running'
            """), {
                "rid": response_id,
                "uid": user_id,
                "payload": json.dumps(payload, default=str),
            }).rowcount
        if not updated:
            raise DeepAgentStoreError("response was no longer running")

    def fail_response(
        self,
        user_id: str,
        response_id: str,
        payload: dict[str, Any],
        *,
        code: str,
        message: str,
    ) -> None:
        with self.pool.get_session() as session:
            session.execute(text("""
                UPDATE alpatrade.deepagent_responses
                SET status = 'failed', response_payload = CAST(:payload AS JSONB),
                    error_code = :code, error_message = :message,
                    completed_at = NOW(), heartbeat_at = NOW()
                WHERE response_id = :rid AND user_id = :uid AND status = 'running'
            """), {
                "rid": response_id,
                "uid": user_id,
                "payload": json.dumps(payload, default=str),
                "code": code[:64],
                "message": message[:512],
            })

    def save_assistant_message(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
        content: str,
        response_id: str,
    ) -> None:
        with self.pool.get_session() as session:
            result = session.execute(text("""
                INSERT INTO alpatrade.chat_messages
                    (thread_id, message_id, role, content, metadata)
                SELECT :tid, :mid, 'assistant', :content, CAST(:metadata AS JSONB)
                FROM alpatrade.chat_conversations
                WHERE thread_id = :tid AND user_id = :uid
                ON CONFLICT (thread_id, message_id) DO NOTHING
            """), {
                "tid": thread_id,
                "mid": message_id,
                "uid": user_id,
                "content": content,
                "metadata": json.dumps({
                    "source": "deepagents-api",
                    "response_id": response_id,
                }),
            })
            if not result.rowcount:
                exists = session.execute(text("""
                    SELECT 1 FROM alpatrade.chat_messages
                    WHERE thread_id = :tid AND message_id = :mid
                """), {"tid": thread_id, "mid": message_id}).scalar()
                if not exists:
                    raise ThreadAccessError("thread_id is not owned by the authenticated user")
            session.execute(text("""
                UPDATE alpatrade.chat_conversations SET updated_at = NOW()
                WHERE thread_id = :tid AND user_id = :uid
            """), {"tid": thread_id, "uid": user_id})

    def append_event(
        self,
        response_id: str,
        sequence_no: int,
        event_type: str,
        *,
        call_id: Optional[str] = None,
        name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        """Persist only the trace envelope; arguments/results/errors are excluded."""
        with self.pool.get_session() as session:
            session.execute(text("""
                INSERT INTO alpatrade.deepagent_events
                    (response_id, sequence_no, event_type, call_id, name, status)
                VALUES (:rid, :seq, :event, :call, :name, :status)
                ON CONFLICT (response_id, sequence_no) DO NOTHING
            """), {
                "rid": response_id,
                "seq": sequence_no,
                "event": event_type[:32],
                "call": call_id[:128] if call_id else None,
                "name": name[:128] if name else None,
                "status": status[:32] if status else None,
            })

    def reserve_action(
        self,
        *,
        user_id: str,
        response_id: str,
        request_message_id: str,
        tool_call_id: str,
        tool_name: str,
        order_client_id: Optional[str] = None,
    ) -> ActionRecord:
        action_id = str(uuid.uuid4())
        try:
            with self.pool.get_session() as session:
                row = session.execute(text("""
                    INSERT INTO alpatrade.deepagent_actions (
                        action_id, user_id, response_id, request_message_id,
                        tool_call_id, tool_name, order_client_id
                    ) VALUES (:aid, :uid, :rid, :mid, :call, :tool, :order_id)
                    RETURNING action_id, status, job_id, order_client_id
                """), {
                    "aid": action_id,
                    "uid": user_id,
                    "rid": response_id,
                    "mid": request_message_id,
                    "call": tool_call_id[:128],
                    "tool": tool_name[:128],
                    "order_id": order_client_id,
                }).fetchone()
            return ActionRecord(str(row[0]), row[1], None, row[3], True)
        except IntegrityError:
            with self.pool.get_session() as session:
                row = session.execute(text("""
                    SELECT action_id, status, job_id, order_client_id
                    FROM alpatrade.deepagent_actions
                    WHERE response_id = :rid AND request_message_id = :mid
                      AND tool_call_id = :call AND tool_name = :tool
                      AND user_id = :uid
                """), {
                    "rid": response_id, "mid": request_message_id,
                    "call": tool_call_id[:128], "tool": tool_name[:128],
                    "uid": user_id,
                }).fetchone()
            if row is None:
                raise
            return ActionRecord(
                str(row[0]), row[1], str(row[2]) if row[2] else None,
                row[3], False,
            )

    def finish_action(
        self,
        user_id: str,
        action_id: str,
        status: str,
        *,
        job_id: Optional[str] = None,
    ) -> None:
        with self.pool.get_session() as session:
            session.execute(text("""
                UPDATE alpatrade.deepagent_actions
                SET status = :status, job_id = COALESCE(CAST(:job_id AS UUID), job_id)
                WHERE action_id = :aid AND user_id = :uid
            """), {
                "status": status[:32], "job_id": job_id,
                "aid": action_id, "uid": user_id,
            })

    def fail_stale_responses(self, stale_seconds: int = 120) -> int:
        """Close abandoned responses without rerunning any possibly completed action."""
        with self.pool.get_session() as session:
            count = session.execute(text("""
                UPDATE alpatrade.deepagent_responses
                SET status = 'failed', error_code = 'process_interrupted',
                    error_message = 'The server process ended before completion.',
                    completed_at = NOW(),
                    response_payload = COALESCE(
                        response_payload,
                        jsonb_build_object(
                            'id', response_id::TEXT,
                            'thread_id', thread_id::TEXT,
                            'status', 'failed',
                            'framework', 'deepagents',
                            'model', jsonb_build_object(
                                'provider', model_provider,
                                'name', model_name
                            ),
                            'messages', '[]'::JSONB,
                            'tools', '[]'::JSONB,
                            'subagents', '[]'::JSONB,
                            'cached', FALSE
                        )
                    )
                WHERE status = 'running'
                  AND heartbeat_at < NOW() - (:seconds * INTERVAL '1 second')
            """), {"seconds": stale_seconds}).rowcount
        return int(count or 0)

    @staticmethod
    def _record(row: Any) -> ResponseRecord:
        payload = row[7]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ResponseRecord(
            response_id=str(row[0]),
            thread_id=str(row[1]),
            request_message_id=str(row[2]),
            status=row[4],
            provider=row[5],
            model=row[6],
            payload=payload,
            request_fingerprint=row[3],
        )
