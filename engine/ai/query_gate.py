"""Atomic platform-funded query gate for user-scoped model calls."""
from __future__ import annotations

import math
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
    platform_queries_used: int = 0
    platform_query_limit: int = FREE_PLATFORM_QUERY_LIMIT


def get_usage_status(user_id: str, *, has_byok: bool) -> dict[str, object]:
    """Return the user's starter-query status without consuming a query."""
    used = 0
    if user_id:
        from engine.db.pool import get_pool
        with get_pool().get_session() as session:
            row = session.execute(text("""
                SELECT platform_queries_used
                FROM alpatrade.user_ai_query_allowances
                WHERE user_id = :user_id
            """), {"user_id": user_id}).fetchone()
            if row:
                used = int(row[0] or 0)
    limit = max(FREE_PLATFORM_QUERY_LIMIT, 0)
    return {
        "funding_source": "byok" if has_byok else "platform",
        "platform_queries_used": used,
        "platform_query_limit": limit,
        "platform_queries_remaining": max(limit - used, 0),
        "percent_used": round((used / limit) * 100) if limit else 100,
    }


def usage_warning(authorization: QueryAuthorization | None) -> str | None:
    """Build a warning after a platform-funded response reaches 90% usage."""
    if not authorization or authorization.funding_source != "platform":
        return None
    limit = authorization.platform_query_limit
    used = authorization.platform_queries_used
    threshold = math.ceil(limit * 0.9)
    if limit <= 0 or used < threshold:
        return None
    remaining = max(limit - used, 0)
    if remaining == 0:
        return (
            f"You have used all {limit} platform-funded AI queries. "
            "Add your xAI API key in Settings before your next AI question."
        )
    return (
        f"You have used {used} of {limit} platform-funded AI queries "
        f"({remaining} remaining). Add your xAI API key in Settings soon."
    )


def render_usage_status(status: dict[str, object]) -> str:
    """Render concise, transparent usage help for the deterministic command."""
    used = int(status["platform_queries_used"])
    limit = int(status["platform_query_limit"])
    remaining = int(status["platform_queries_remaining"])
    percent = int(status["percent_used"])
    byok = status["funding_source"] == "byok"
    funding = (
        "Your xAI API key for DeepAgents/LangGraph"
        if byok else "Platform starter allowance"
    )
    note = (
        "Your starter allowance is paused for DeepAgents/LangGraph; free-form "
        "Hermes still uses it because the sidecar cannot receive your saved key."
        if byok else
        "Free-form Hermes, DeepAgents, and LangGraph questions consume this allowance."
    )
    return (
        "## AI usage\n\n"
        f"- **Current funding:** {funding}\n"
        f"- **Platform queries used:** {used} / {limit} ({percent}%)\n"
        f"- **Platform queries remaining:** {remaining}\n\n"
        f"{note} Deterministic commands, including supported Hermes trading "
        "commands, do not consume a query. This counts visible Hermes requests, "
        "not every internal sidecar model turn or its exact token cost."
    )


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
    return QueryAuthorization(
        "platform", platform_slot=True,
        platform_queries_used=int(row[0]),
        platform_query_limit=FREE_PLATFORM_QUERY_LIMIT,
    )


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
