"""
Chat persistence — save/load conversations and messages to PostgreSQL.
"""

import json
import uuid
import logging
from typing import Optional

from sqlalchemy import text

from utils.db.db_pool import DatabasePool

logger = logging.getLogger(__name__)

_pool: Optional[DatabasePool] = None


def _get_pool() -> DatabasePool:
    global _pool
    if _pool is None:
        _pool = DatabasePool()
    return _pool


def save_conversation(thread_id: str, user_id: Optional[str] = None,
                      title: Optional[str] = None):
    """Upsert a conversation record. If title is None, only update updated_at."""
    pool = _get_pool()
    with pool.get_session() as session:
        if title is not None:
            session.execute(text("""
                INSERT INTO alpatrade.chat_conversations (thread_id, user_id, title)
                VALUES (:tid, :uid, :title)
                ON CONFLICT (thread_id) DO UPDATE
                SET title = :title, updated_at = NOW()
            """), {"tid": thread_id, "uid": user_id, "title": title})
        else:
            session.execute(text("""
                INSERT INTO alpatrade.chat_conversations (thread_id, user_id, title)
                VALUES (:tid, :uid, 'New chat')
                ON CONFLICT (thread_id) DO UPDATE
                SET updated_at = NOW()
            """), {"tid": thread_id, "uid": user_id})


def save_message(thread_id: str, role: str, content: str,
                 message_id: Optional[str] = None, metadata: Optional[dict] = None):
    """Insert a chat message."""
    pool = _get_pool()
    mid = message_id or str(uuid.uuid4())
    with pool.get_session() as session:
        session.execute(text("""
            INSERT INTO alpatrade.chat_messages (thread_id, message_id, role, content, metadata)
            VALUES (:tid, :mid, :role, :content, CAST(:meta AS JSONB))
        """), {
            "tid": thread_id,
            "mid": mid,
            "role": role,
            "content": content,
            "meta": json.dumps(metadata) if metadata is not None else None,
        })


def load_conversation_messages(
    thread_id: str, user_id: Optional[str] = None
) -> list[dict]:
    """Load messages, optionally enforcing ownership by ``user_id``."""
    pool = _get_pool()
    with pool.get_session() as session:
        owner_join = "" if user_id is None else (
            " JOIN alpatrade.chat_conversations c ON c.thread_id = m.thread_id"
        )
        owner_filter = "" if user_id is None else " AND c.user_id = CAST(:uid AS UUID)"
        rows = session.execute(text(f"""
            SELECT m.message_id, m.role, m.content, m.metadata, m.created_at
            FROM alpatrade.chat_messages m{owner_join}
            WHERE m.thread_id = CAST(:tid AS UUID){owner_filter}
            ORDER BY m.created_at ASC
        """), {"tid": thread_id, "uid": user_id}).fetchall()
    return [
        {
            "message_id": str(r[0]),
            "role": r[1],
            "content": r[2],
            "metadata": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def list_conversations(user_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """List recent conversations, optionally filtered by user."""
    pool = _get_pool()
    with pool.get_session() as session:
        if user_id:
            rows = session.execute(text("""
                SELECT c.thread_id, c.title, c.updated_at,
                       (SELECT content FROM alpatrade.chat_messages m
                        WHERE m.thread_id = c.thread_id AND m.role = 'user'
                        ORDER BY m.created_at ASC LIMIT 1) AS first_msg
                FROM alpatrade.chat_conversations c
                WHERE c.user_id = :uid
                ORDER BY c.updated_at DESC
                LIMIT :lim
            """), {"uid": user_id, "lim": limit}).fetchall()
        else:
            rows = session.execute(text("""
                SELECT c.thread_id, c.title, c.updated_at,
                       (SELECT content FROM alpatrade.chat_messages m
                        WHERE m.thread_id = c.thread_id AND m.role = 'user'
                        ORDER BY m.created_at ASC LIMIT 1) AS first_msg
                FROM alpatrade.chat_conversations c
                WHERE c.user_id IS NULL
                ORDER BY c.updated_at DESC
                LIMIT :lim
            """), {"lim": limit}).fetchall()
    return [
        {
            "thread_id": str(r[0]),
            "title": r[1],
            "updated_at": r[2],
            "first_msg": r[3],
        }
        for r in rows
    ]


def conversation_belongs_to_user(thread_id: str, user_id: str) -> bool:
    """Return whether a thread belongs to the specified logged-in user."""
    pool = _get_pool()
    with pool.get_session() as session:
        return bool(session.execute(text("""
            SELECT 1 FROM alpatrade.chat_conversations
            WHERE thread_id = CAST(:tid AS UUID)
              AND user_id = CAST(:uid AS UUID)
        """), {"tid": thread_id, "uid": user_id}).scalar())


def delete_conversation(thread_id: str, user_id: Optional[str] = None):
    """Delete a conversation, optionally enforcing account ownership."""
    pool = _get_pool()
    with pool.get_session() as session:
        owner_filter = "" if user_id is None else " AND user_id = CAST(:uid AS UUID)"
        session.execute(text(f"""
            DELETE FROM alpatrade.chat_conversations
            WHERE thread_id = CAST(:tid AS UUID){owner_filter}
        """), {"tid": thread_id, "uid": user_id})
