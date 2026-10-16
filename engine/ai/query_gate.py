"""Atomic platform-funded query gate for user-scoped model calls."""
from __future__ import annotations

import math
import os
from contextlib import nullcontext
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

FREE_PLATFORM_QUERY_LIMIT = int(os.getenv("FREE_PLATFORM_QUERY_LIMIT", "5"))


class QueryLimitExceeded(PermissionError):
    """Raised when a user has exhausted the shared platform allowance."""


@dataclass(frozen=True)
class QueryAuthorization:
    funding_source: str
    platform_slot: bool = False
    platform_queries_used: int = 0
    platform_query_limit: int | None = FREE_PLATFORM_QUERY_LIMIT
    owner: bool = False


def is_admin_user(user_id: str) -> bool:
    """Check owner access, failing closed when the database is unavailable."""
    if not user_id:
        return False
    try:
        from engine.db.pool import get_pool
        with get_pool().get_session() as session:
            row = session.execute(text("""
                SELECT is_admin
                FROM alpatrade.users
                WHERE user_id = CAST(:uid AS UUID)
            """), {"uid": user_id}).fetchone()
        return row is not None and row[0] is True
    except Exception:
        return False


def get_usage_status(user_id: str, *, has_byok: bool) -> dict[str, object]:
    """Return the user's starter-query status without consuming a query."""
    owner = not has_byok and is_admin_user(user_id)
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
    try:
        from engine.ai.llm_usage import PLATFORM_DAILY_BUDGET_USD, daily_platform_cost
        daily_cost = daily_platform_cost()
        user_daily_cost = daily_platform_cost(user_id) if user_id else Decimal("0")
        daily_budget = PLATFORM_DAILY_BUDGET_USD
    except Exception:  # migration may not be deployed yet
        daily_cost = user_daily_cost = Decimal("0")
        daily_budget = Decimal("5")
    return {
        "funding_source": "byok" if has_byok else "owner" if owner else "platform",
        "platform_queries_used": used,
        "platform_query_limit": None if owner else limit,
        "platform_queries_remaining": None if owner else max(limit - used, 0),
        "percent_used": None if owner else round((used / limit) * 100) if limit else 100,
        "platform_daily_cost": daily_cost,
        "user_daily_cost": user_daily_cost,
        "platform_daily_budget": daily_budget,
    }


def usage_warning(authorization: QueryAuthorization | None) -> str | None:
    """Build a warning after a platform-funded response reaches 90% usage."""
    if (not authorization or authorization.owner
            or authorization.funding_source != "platform"):
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
    owner = status["funding_source"] == "owner"
    if owner and status["platform_query_limit"] is None:
        queries = f"- **Platform queries used:** {used} / unlimited\n\n"
    else:
        limit = int(status["platform_query_limit"])
        remaining = int(status["platform_queries_remaining"])
        percent = int(status["percent_used"])
        queries = (
            f"- **Platform queries used:** {used} / {limit} ({percent}%)\n"
            f"- **Platform queries remaining:** {remaining}\n\n"
        )
    byok = status["funding_source"] == "byok"
    funding = (
        "Platform owner account" if owner else
        "Your xAI API key for DeepAgents/LangGraph"
        if byok else "Platform starter allowance"
    )
    note = (
        "Free-form Hermes, DeepAgents, and LangGraph questions have unlimited platform funding."
        if owner else
        "Your starter allowance is paused for DeepAgents/LangGraph; free-form "
        "Hermes still uses it because the sidecar cannot receive your saved key."
        if byok else
        "Free-form Hermes, DeepAgents, and LangGraph questions consume this allowance."
    )
    return (
        "## AI usage\n\n"
        f"- **Current funding:** {funding}\n"
        f"{queries}"
        f"- **Your estimated AI cost today:** ${status.get('user_daily_cost', 0):.4f}\n"
        f"- **Platform estimated spend today:** ${status.get('platform_daily_cost', 0):.4f} / "
        f"${status.get('platform_daily_budget', 5):.2f}\n\n"
        f"{note} Deterministic commands, including supported Hermes trading "
        "commands, do not consume a query. This counts visible Hermes requests, "
        "not every internal sidecar model turn or its exact token cost."
    )


def authorize_query(user_id: str, *, has_byok: bool, session=None) -> QueryAuthorization:
    """Use BYOK or atomically reserve one of the user's platform-funded calls."""
    if has_byok:
        return QueryAuthorization("byok")
    if is_admin_user(user_id):
        return QueryAuthorization("owner", platform_query_limit=None, owner=True)
    if not user_id:
        raise QueryLimitExceeded("Sign in and add your xAI API key in Settings.")
    from engine.ai.llm_usage import enforce_daily_budget
    enforce_daily_budget(funding_source="platform")
    from engine.db.pool import get_pool
    with (nullcontext(session) if session is not None else get_pool().get_session()) as session:
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


def refund_query(user_id: str, authorization: QueryAuthorization | None, *, session=None) -> None:
    """Return a reserved platform slot when the model request fails."""
    if not authorization or not authorization.platform_slot:
        return
    from engine.db.pool import get_pool
    with (nullcontext(session) if session is not None else get_pool().get_session()) as session:
        session.execute(text("""
            UPDATE alpatrade.user_ai_query_allowances
            SET platform_queries_used = GREATEST(platform_queries_used - 1, 0),
                updated_at = NOW()
            WHERE user_id = :user_id
        """), {"user_id": user_id})
