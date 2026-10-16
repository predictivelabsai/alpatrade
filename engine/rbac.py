"""Roles (admin / member / user), teams and login tracking.

* ``admin``  — platform operator; sees /admin analytics.
* ``member`` — a user who belongs to a team (``users.team_id``).
* ``user``   — everyone else (default).

Role checks are server-side: :func:`role_of` reads ``alpatrade.users.role``
(falling back to the legacy ``is_admin`` flag when the column is not there yet)
and :func:`is_admin` gates admin routes. Schema: ``sql/51_rbac_referrals_logins.sql``,
applied idempotently on first use.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("engine.rbac")

ROLES = ("admin", "member", "user")
_SQL = Path(__file__).resolve().parents[1] / "sql" / "51_rbac_referrals_logins.sql"
_ready = False


def _pool():
    from utils.db.db_pool import DatabasePool
    return DatabasePool()


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text(_SQL.read_text()))
        s.commit()
    _ready = True


def normalize_role(role: Optional[str], *, is_admin: bool = False, team_id=None) -> str:
    r = (role or "").strip().lower()
    if r not in ROLES:
        r = "user"
    if is_admin:
        return "admin"
    if r == "user" and team_id:
        return "member"
    return r


def role_of(user: Optional[dict]) -> str:
    """Server-side role for a user dict (``user_id`` required). Unknown → ``user``."""
    if not user:
        return "user"
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            row = s.execute(text("SELECT role, is_admin, team_id FROM alpatrade.users "
                                 "WHERE user_id = CAST(:u AS UUID)"),
                            {"u": str(user["user_id"])}).fetchone()
        if row:
            return normalize_role(row[0], is_admin=bool(row[1]), team_id=row[2])
    except Exception as exc:  # noqa: BLE001
        log.warning("role lookup failed: %s", type(exc).__name__)
    return "admin" if user.get("is_admin") else "user"


def is_admin(user: Optional[dict]) -> bool:
    return role_of(user) == "admin"


def record_login(user_id: str, method: str = "password", ip: str = "", user_agent: str = "") -> None:
    """Append a login row and stamp ``users.last_login_at``. Never raises."""
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            s.execute(text("INSERT INTO alpatrade.user_logins (user_id, method, ip, user_agent) "
                           "VALUES (CAST(:u AS UUID), :m, :ip, :ua)"),
                      {"u": str(user_id), "m": (method or "password")[:16],
                       "ip": (ip or "")[:64] or None, "ua": (user_agent or "")[:300] or None})
            s.execute(text("UPDATE alpatrade.users SET last_login_at = NOW() "
                           "WHERE user_id = CAST(:u AS UUID)"), {"u": str(user_id)})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("login tracking failed: %s", type(exc).__name__)


def set_role(user_id: str, role: str, team_id: Optional[int] = None) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("UPDATE alpatrade.users SET role = :r, is_admin = (:r = 'admin'), "
                       "team_id = COALESCE(:t, team_id) WHERE user_id = CAST(:u AS UUID)"),
                  {"r": role, "t": team_id, "u": str(user_id)})
        s.commit()
