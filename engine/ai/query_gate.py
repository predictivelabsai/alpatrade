"""Atomic platform-funded query gate for user-scoped model calls."""
from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import text

FREE_PLATFORM_QUERY_LIMIT = int(os.getenv("FREE_PLATFORM_QUERY_LIMIT", "5"))


class QueryLimitExceeded(PermissionError):
    """Raised when a user has exhausted the shared platform allowance."""


@dataclass(frozen=True)
class QueryAuthorization:
    funding_source: str
    platform_slot: bool = False


def authorize_query(user_id: str, *, has_byok: bool) -> QueryAuthorization:
    """Use BYOK or atomically reserve one of the user's platform-funded calls."""
    if has_byok:
        return QueryAuthorization("byok")
    if not user_id:
        raise QueryLimitExceeded("Sign in and add your xAI API key in Settings.")
    from engine.db.pool import get_pool
    with get_pool().get_session() as session:
        session.execute(text("""
            INSERT INTO alpatrade.user_ai_query_allowances (user_id)
            VALUES (:user_id) ON CONFLICT (user_id) DO NOTHING
        """), {"user_id": user_id})
        row = session.execute(text("""
            UPDATE alpatrade.user_ai_query_allowances
            SET platform_queries_used = platform_queries_used + 1,
                updated_at = NOW()
            WHERE user_id = :user_id
              AND platform_queries_used < :query_limit
            RETURNING platform_queries_used
        """), {"user_id": user_id, "query_limit": FREE_PLATFORM_QUERY_LIMIT}).fetchone()
    if not row:
        raise QueryLimitExceeded(
            f"Your {FREE_PLATFORM_QUERY_LIMIT} platform-funded AI queries are used. "
            "Add your own xAI API key in Settings to continue."
        )
    return QueryAuthorization("platform", platform_slot=True)


def refund_query(user_id: str, authorization: QueryAuthorization | None) -> None:
    """Return a reserved platform slot when the model request fails."""
    if not authorization or not authorization.platform_slot:
        return
    from engine.db.pool import get_pool
    with get_pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.user_ai_query_allowances
            SET platform_queries_used = GREATEST(platform_queries_used - 1, 0),
                updated_at = NOW()
            WHERE user_id = :user_id
        """), {"user_id": user_id})

