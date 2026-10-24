"""Admin approval of new accounts (v0.56.0).

Every new sign-up (email, Google, API) starts ``pending`` (``alpatrade.users.approval_status``,
``sql/58_user_approval.sql``). Pending and rejected users can sign in, but the web app sends
them to ``/pending`` (see :func:`engine.web.ph_approval.approval_gate`), the API refuses their
JWT, and the domain actions (store broker keys, activate paper/live) refuse them too.

Approvers: the emails notified on each sign-up. Read from env ``SIGNUP_APPROVER_EMAILS``
(comma-separated) when set, else ``alpatrade.app_settings['signup_approvers']``, else
:data:`DEFAULT_APPROVERS`. Admins (``engine.rbac``) and approvers may review sign-ups.

Every helper fails open for *existing* users: a status we cannot read is treated as
"not blocked", so a DB hiccup never locks out an approved user (only an explicit
``pending`` / ``rejected`` blocks).
"""
from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("engine.approval")

STATUSES = ("pending", "approved", "rejected")
BLOCKED = ("pending", "rejected")
DEFAULT_APPROVERS = ("kaljuvee@gmail.com", "joosep.laats@gmail.com")
SETTINGS_KEY = "signup_approvers"
REVIEW_PATH = "/admin/running#approvals"
CACHE_TTL = 10.0  # seconds; decide() clears the entry immediately in this process

NOT_APPROVED_MSG = ("Your AlpaTrade account is awaiting admin approval. Strategies, broker keys "
                    "and trading unlock once it is approved.")
REJECTED_MSG = "Your AlpaTrade account was not approved."

_SQL = Path(__file__).resolve().parents[1] / "sql" / "58_user_approval.sql"
_ready = False
_cache: dict[str, tuple[float, Optional[str]]] = {}
_lock = threading.Lock()


class NotApprovedError(ValueError):
    """Raised by domain actions (e.g. storing broker keys) for a pending/rejected user."""


def _pool():
    # Tests must never reach the shared (prod) DB through this module: they fake status_of or
    # patch _pool with a throwaway database (tests/test_user_approval_postgres.py).
    if os.getenv("PYTEST_CURRENT_TEST"):
        raise RuntimeError("engine.approval: real DB disabled under pytest")
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


def base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "https://alpatrade.chat").rstrip("/")


# --------------------------------------------------------------------------- status
def status_of(user_id, *, fresh: bool = False) -> Optional[str]:
    """``pending`` / ``approved`` / ``rejected``, or None (unknown user / unreadable)."""
    if not user_id:
        return None
    uid = str(user_id)
    now = time.monotonic()
    if not fresh:
        with _lock:
            hit = _cache.get(uid)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    st: Optional[str] = None
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            row = s.execute(text("SELECT approval_status FROM alpatrade.users "
                                 "WHERE user_id = CAST(:u AS UUID)"), {"u": uid}).fetchone()
        st = row[0] if row else None
    except Exception as exc:  # noqa: BLE001 — fail open (see module doc)
        log.warning("approval status lookup failed: %s", type(exc).__name__)
        return None
    with _lock:
        _cache[uid] = (now, st)
    return st


def forget(user_id) -> None:
    with _lock:
        _cache.pop(str(user_id), None)


def is_blocked(user_id) -> bool:
    return status_of(user_id) in BLOCKED


def block_message(user_id) -> str:
    """``""`` when the user may act, else the message to show."""
    st = status_of(user_id)
    if st == "pending":
        return NOT_APPROVED_MSG
    if st == "rejected":
        return REJECTED_MSG
    return ""


def require_approved(user_id) -> None:
    msg = block_message(user_id)
    if msg:
        raise NotApprovedError(msg)


# --------------------------------------------------------------------------- approvers
def _clean_emails(items) -> list[str]:
    out: list[str] = []
    for e in items or []:
        e = str(e or "").strip().lower()
        if e and "@" in e and " " not in e and e not in out:
            out.append(e)
    return out


def approvers() -> list[str]:
    env = os.getenv("SIGNUP_APPROVER_EMAILS", "").strip()
    if env:
        return _clean_emails(env.split(","))
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            row = s.execute(text("SELECT value FROM alpatrade.app_settings WHERE key = :k"),
                            {"k": SETTINGS_KEY}).fetchone()
        if row and row[0]:
            val = row[0] if isinstance(row[0], list) else json.loads(row[0])
            got = _clean_emails(val)
            if got:
                return got
    except Exception as exc:  # noqa: BLE001
        log.warning("approver list lookup failed: %s", type(exc).__name__)
    return list(DEFAULT_APPROVERS)


def set_approvers(emails, by_user_id=None) -> list[str]:
    clean = _clean_emails(emails)
    if not clean:
        raise ValueError("at least one approver email is required")
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("INSERT INTO alpatrade.app_settings (key, value, updated_at, updated_by) "
                       "VALUES (:k, CAST(:v AS JSONB), NOW(), CAST(:by AS UUID)) "
                       "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                       "updated_at = NOW(), updated_by = EXCLUDED.updated_by"),
                  {"k": SETTINGS_KEY, "v": json.dumps(clean), "by": str(by_user_id) if by_user_id else None})
        s.commit()
    return clean


def can_review(user: Optional[dict]) -> bool:
    """Admins, plus anyone on the approver list, may review sign-ups."""
    if not user:
        return False
    try:
        from engine.rbac import is_admin
        if is_admin(user):
            return True
    except Exception:  # noqa: BLE001
        pass
    return (user.get("email") or "").strip().lower() in approvers()


# --------------------------------------------------------------------------- sign-up
def _fmt_times(ts: datetime) -> str:
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    zones = [("America/New_York", "ET"), ("Europe/London", "UK"), ("Europe/Tallinn", "Tallinn")]
    return " · ".join(f"{ts.astimezone(ZoneInfo(z)):%Y-%m-%d %H:%M} {lbl}" for z, lbl in zones)


def record_signup(user_id, method: str, ip: str = "", user_agent: str = "") -> None:
    """Stamp how/where the account was created. Never raises."""
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            s.execute(text("UPDATE alpatrade.users SET signup_method = :m, signup_ip = :ip, "
                           "signup_user_agent = :ua WHERE user_id = CAST(:u AS UUID)"),
                      {"m": (method or "")[:16] or None, "ip": (ip or "")[:64] or None,
                       "ua": (user_agent or "")[:300] or None, "u": str(user_id)})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("signup stamp failed: %s", type(exc).__name__)


def render_admin_email(user: dict, method: str, ip: str = "", user_agent: str = "",
                       when: Optional[datetime] = None) -> tuple[str, str]:
    e = html.escape
    when = when or datetime.now(timezone.utc)
    name = user.get("display_name") or (user.get("email") or "").split("@")[0]
    link = base_url() + REVIEW_PATH
    rows = [("Name", name), ("Email", user.get("email") or ""), ("Sign-up method", method),
            ("Time", _fmt_times(when)), ("IP", ip or "—"), ("User agent", (user_agent or "—")[:200])]
    tr = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#6c757d'>{e(k)}</td>"
                 f"<td style='padding:4px 0'><b>{e(str(v))}</b></td></tr>" for k, v in rows)
    subject = f"AlpaTrade: new sign-up awaiting approval: {name} <{user.get('email', '')}>"
    body = ("<div style=\"font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto\">"
            "<h2>New AlpaTrade sign-up</h2><p>This account is <b>pending</b>. It can sign in but cannot "
            "use the app until an admin approves it.</p>"
            f"<table style='font-size:14px;border-collapse:collapse'>{tr}</table>"
            f"<p><a href=\"{e(link)}\" style=\"display:inline-block;padding:12px 24px;background:#1F5D43;"
            "color:#fff;text-decoration:none;border-radius:6px\">Review sign-ups</a></p>"
            f"<p style='color:#6c757d;font-size:13px'>Or open {e(link)}</p></div>")
    return subject, body


def notify_admins(user: dict, method: str, ip: str = "", user_agent: str = "",
                  send: Optional[Callable[[str, str, str], bool]] = None,
                  background: bool = True) -> list[str]:
    """Email every approver about a new pending sign-up. Returns the recipient list.

    Sent from a daemon thread by default so a slow Postmark call never delays sign-up.
    """
    to = approvers()
    subject, body = render_admin_email(user, method, ip, user_agent)
    if send is None:
        from utils.email_util import send_email_to as send

    def _go():
        for addr in to:
            try:
                if not send(addr, subject, body):
                    log.warning("sign-up approval email not sent to %s", addr)
            except Exception as exc:  # noqa: BLE001
                log.warning("sign-up approval email failed: %s", type(exc).__name__)

    if background and not os.getenv("PYTEST_CURRENT_TEST"):
        threading.Thread(target=_go, name="signup-approval-mail", daemon=True).start()
    else:
        _go()
    return to


def on_signup(user: dict, method: str, ip: str = "", user_agent: str = "") -> None:
    """Call once right after a new account is created. Never raises."""
    if not user or not user.get("user_id"):
        return
    record_signup(user["user_id"], method, ip, user_agent)
    try:
        notify_admins(user, method, ip, user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("sign-up approval notify failed: %s", type(exc).__name__)


# --------------------------------------------------------------------------- review
Q_LIST = """
SELECT u.user_id, u.email, u.display_name, u.role, u.created_at, u.approval_status,
       u.approval_decided_at, d.email AS decided_by, u.signup_method, u.signup_ip,
       u.signup_user_agent, u.email_verified_at, u.google_id IS NOT NULL AS has_google,
       u.password_hash IS NOT NULL AS has_password, u.last_login_at,
       r.email AS referred_by,
       (SELECT l.ip FROM alpatrade.user_logins l WHERE l.user_id = u.user_id
         ORDER BY l.created_at DESC LIMIT 1) AS last_ip,
       (SELECT l.user_agent FROM alpatrade.user_logins l WHERE l.user_id = u.user_id
         ORDER BY l.created_at DESC LIMIT 1) AS last_ua,
       (SELECT COUNT(*) FROM alpatrade.user_logins l WHERE l.user_id = u.user_id) AS logins
FROM alpatrade.users u
LEFT JOIN alpatrade.users d ON d.user_id = u.approval_decided_by
LEFT JOIN alpatrade.users r ON r.user_id = u.referred_by
WHERE u.is_active = TRUE AND (:st = 'all' OR u.approval_status = :st)
ORDER BY u.created_at DESC
LIMIT :lim
"""


def method_label(row: dict) -> str:
    m = (row.get("signup_method") or "").strip()
    if m:
        return m
    if row.get("has_google") and not row.get("has_password"):
        return "google"
    return "email" if row.get("has_password") else "—"


def list_users(status: str = "pending", limit: int = 200) -> Optional[list[dict]]:
    st = status if status in STATUSES else "all"
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            res = s.execute(text(Q_LIST), {"st": st, "lim": int(limit)})
            keys = list(res.keys())
            return [dict(zip(keys, r)) for r in res.fetchall()]
    except Exception as exc:  # noqa: BLE001
        log.warning("approval list failed: %s", type(exc).__name__)
        return None


def counts() -> dict:
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            rows = s.execute(text("SELECT approval_status, COUNT(*) FROM alpatrade.users "
                                  "WHERE is_active = TRUE GROUP BY 1")).fetchall()
        out = {k: 0 for k in STATUSES}
        out.update({r[0]: int(r[1]) for r in rows})
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("approval counts failed: %s", type(exc).__name__)
        return {}


def render_user_email(user: dict) -> tuple[str, str]:
    name = html.escape(user.get("display_name") or "there")
    link = base_url() + "/dashboard"
    body = ("<div style=\"font-family:-apple-system,sans-serif;max-width:500px;margin:0 auto\">"
            f"<h2>Your AlpaTrade account is approved</h2><p>Hi {name}, an admin has approved your account. "
            "You can now connect your Alpaca paper keys, run backtests and activate strategies.</p>"
            f"<p><a href=\"{html.escape(link)}\" style=\"display:inline-block;padding:12px 24px;"
            "background:#1F5D43;color:#fff;text-decoration:none;border-radius:6px\">Open AlpaTrade</a></p></div>")
    return "AlpaTrade: your account is approved", body


def decide(user_id, status: str, by_user: Optional[dict] = None, *, notify_user: bool = False,
           send: Optional[Callable[[str, str, str], bool]] = None) -> dict:
    """Set a user's approval status. Returns ``{'ok', 'message', 'email'?}``."""
    if status not in STATUSES:
        return {"ok": False, "message": f"Unknown status {status!r}."}
    if by_user and str(by_user.get("user_id")) == str(user_id) and status != "approved":
        return {"ok": False, "message": "You cannot change your own approval status."}
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        row = s.execute(text(
            "UPDATE alpatrade.users SET approval_status = :st, approval_decided_at = NOW(), "
            "approval_decided_by = CAST(:by AS UUID), updated_at = NOW() "
            "WHERE user_id = CAST(:u AS UUID) RETURNING email, display_name"),
            {"st": status, "by": str(by_user["user_id"]) if by_user and by_user.get("user_id") else None,
             "u": str(user_id)}).fetchone()
        s.commit()
    forget(user_id)
    if not row:
        return {"ok": False, "message": "User not found."}
    email, name = row[0], row[1]
    log.info("approval: %s -> %s by %s", email, status, (by_user or {}).get("email"))
    out = {"ok": True, "email": email, "message": f"{name or email} is now {status}."}
    if notify_user and status == "approved":
        subject, body = render_user_email({"display_name": name, "email": email})
        if send is None:
            from utils.email_util import send_email_to as send
        try:
            sent = send(email, subject, body)
        except Exception:  # noqa: BLE001
            sent = False
        out["message"] += " Approval email sent." if sent else " (Approval email could not be sent.)"
    return out
