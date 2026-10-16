"""Platform user analytics for the admin page (read-only SQL, each metric isolated).

Day/week buckets are US/Eastern calendar days. A metric whose source table is
missing renders as ``None`` instead of failing the page.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("engine.admin_analytics")

# name -> (sql, shape) ; shape: "scalar" | "rows"
QUERIES: dict[str, tuple[str, str]] = {
    "total_users": ("SELECT COUNT(*) FROM alpatrade.users", "scalar"),
    "new_users_7d": ("SELECT COUNT(*) FROM alpatrade.users WHERE created_at > NOW() - INTERVAL '7 days'", "scalar"),
    "new_users_30d": ("SELECT COUNT(*) FROM alpatrade.users WHERE created_at > NOW() - INTERVAL '30 days'", "scalar"),
    "new_users_daily": ("""
        SELECT (created_at AT TIME ZONE 'America/New_York')::date AS d, COUNT(*)
        FROM alpatrade.users WHERE created_at > NOW() - INTERVAL '14 days'
        GROUP BY 1 ORDER BY 1 DESC""", "rows"),
    "new_users_weekly": ("""
        SELECT date_trunc('week', created_at AT TIME ZONE 'America/New_York')::date AS w, COUNT(*)
        FROM alpatrade.users WHERE created_at > NOW() - INTERVAL '84 days'
        GROUP BY 1 ORDER BY 1 DESC""", "rows"),
    "roles": ("SELECT role, COUNT(*) FROM alpatrade.users GROUP BY 1 ORDER BY 2 DESC", "rows"),
    "teams": ("SELECT COUNT(*) FROM alpatrade.teams", "scalar"),
    "logins_total": ("SELECT COUNT(*) FROM alpatrade.user_logins", "scalar"),
    "logins_7d": ("SELECT COUNT(*) FROM alpatrade.user_logins WHERE created_at > NOW() - INTERVAL '7 days'", "scalar"),
    "logins_by_method_30d": ("""
        SELECT method, COUNT(*) FROM alpatrade.user_logins
        WHERE created_at > NOW() - INTERVAL '30 days' GROUP BY 1 ORDER BY 2 DESC""", "rows"),
    # Active = signed in OR did anything logged (chat/agent requests) in the window.
    "dau": ("""SELECT COUNT(DISTINCT user_id) FROM (
        SELECT user_id FROM alpatrade.user_logins WHERE created_at > NOW() - INTERVAL '1 day'
        UNION SELECT user_id FROM alpatrade.user_logging WHERE created_at > NOW() - INTERVAL '1 day') a""", "scalar"),
    "wau": ("""SELECT COUNT(DISTINCT user_id) FROM (
        SELECT user_id FROM alpatrade.user_logins WHERE created_at > NOW() - INTERVAL '7 days'
        UNION SELECT user_id FROM alpatrade.user_logging WHERE created_at > NOW() - INTERVAL '7 days') a""", "scalar"),
    "mau": ("""SELECT COUNT(DISTINCT user_id) FROM (
        SELECT user_id FROM alpatrade.user_logins WHERE created_at > NOW() - INTERVAL '30 days'
        UNION SELECT user_id FROM alpatrade.user_logging WHERE created_at > NOW() - INTERVAL '30 days') a""", "scalar"),
    "activations": ("""
        SELECT mode, COUNT(*) AS n, COUNT(DISTINCT user_id) AS users
        FROM alpatrade.user_strategy_activations GROUP BY 1 ORDER BY 1""", "rows"),
    "referrals": ("""
        SELECT COUNT(*) FILTER (WHERE status IN ('sent','accepted')),
               COUNT(*) FILTER (WHERE status = 'accepted'),
               COUNT(DISTINCT referrer_id)
        FROM alpatrade.referral_invites""", "rows"),
    "referred_signups": ("SELECT COUNT(*) FROM alpatrade.users WHERE referred_by IS NOT NULL", "scalar"),
    "backtests_total": ("SELECT COUNT(*) FROM alpatrade.runs WHERE mode = 'backtest'", "scalar"),
    "backtests_7d": ("SELECT COUNT(*) FROM alpatrade.runs WHERE mode = 'backtest' "
                     "AND created_at > NOW() - INTERVAL '7 days'", "scalar"),
    "backtest_users": ("SELECT COUNT(DISTINCT user_id) FROM alpatrade.runs WHERE mode = 'backtest'", "scalar"),
}


def snapshot(execute: Callable[[str], list] | None = None) -> dict[str, Any]:
    """Run every metric; ``execute(sql) -> rows`` is injectable for tests."""
    if execute is None:
        from sqlalchemy import text
        from utils.db.db_pool import DatabasePool
        from engine.rbac import ensure_schema
        try:
            ensure_schema()
        except Exception as exc:  # noqa: BLE001
            log.warning("rbac schema not applied: %s", type(exc).__name__)
        pool = DatabasePool()

        def execute(sql: str) -> list:
            with pool.get_session() as s:
                return [tuple(r) for r in s.execute(text(sql)).fetchall()]

    out: dict[str, Any] = {}
    for name, (sql, shape) in QUERIES.items():
        try:
            rows = execute(sql)
            out[name] = (rows[0][0] if rows else 0) if shape == "scalar" else rows
        except Exception as exc:  # noqa: BLE001
            log.warning("admin metric %s failed: %s", name, type(exc).__name__)
            out[name] = None
    return out
