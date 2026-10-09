"""CRUD for ``alpatrade.user_strategies`` (sql/42_user_strategies.sql).

Every write is scoped by the owner's ``user_id`` (taken from the session by the caller), so
a user can only edit, publish, unpublish or delete their own strategies. Reads of another
user's strategy are limited to public ones.
"""
from __future__ import annotations

import html
import re
from typing import Optional

TABLE = "alpatrade.user_strategies"
_COLS = ("s.id, s.user_id, s.name, s.author_name, s.description, s.skill_md, s.is_public, "
         "s.live_strategy_slug, s.seed_key, s.cloned_from_id, s.created_at, s.updated_at, "
         "s.kind, s.source, s.source_url, s.backtest_metrics, "
         "u.display_name AS user_display_name, u.email AS user_email")
_FROM = f"{TABLE} s LEFT JOIN alpatrade.users u ON u.user_id = s.user_id"

MAX_NAME = 160
MAX_AUTHOR = 60  # public "Shown as" name (DB column allows 120)
MAX_DESC = 2000
MAX_SKILL = 60000


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def is_backtest(row: dict) -> bool:
    return (row or {}).get("kind") == "backtest"


def public_name(display_name: Optional[str], email: Optional[str] = None) -> str:
    """A display name that never exposes an email address."""
    n = (display_name or "").strip()
    if n and "@" not in n:
        return n
    src = n or (email or "")
    return src.split("@", 1)[0] if src else "AlpaTrade user"


_TAG = re.compile(r"<[^>]*>")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def default_author(user: Optional[dict]) -> str:
    """Default public "Shown as" name for a new / cloned strategy: the email's local part."""
    user = user or {}
    email = (user.get("email") or "").strip()
    if email:
        return email.split("@", 1)[0][:MAX_AUTHOR] or "AlpaTrade user"
    return public_name(user.get("display_name"))[:MAX_AUTHOR]


def clean_author(raw: Optional[str], default: Optional[str] = None) -> Optional[str]:
    """Sanitise a "Shown as" name: strip HTML tags / control chars, collapse whitespace,
    trim, cap at ``MAX_AUTHOR``; blank falls back to ``default`` (itself cleaned).
    Output is still HTML-escaped on render."""
    v = _TAG.sub("", html.unescape(str(raw or "")))
    v = re.sub(r"\s+", " ", _CTRL.sub(" ", v)).strip()[:MAX_AUTHOR].strip()
    if v:
        return v
    if default is not None and str(default).strip():
        return clean_author(default)
    return None


def author_of(row: dict) -> str:
    return (row.get("author_name") or "").strip() or public_name(
        row.get("user_display_name"), row.get("user_email"))


def _clean(name, description, skill_md, author_name):
    from engine.leaderboard.skill import with_author
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        raise ValueError("A strategy needs a name.")
    author = clean_author(author_name)
    md = (skill_md or "")[:MAX_SKILL]
    if author:  # keep the skill's front-matter ``author:`` in step with "Shown as"
        md = with_author(md, author)[:MAX_SKILL]
    return (name, (description or "").strip()[:MAX_DESC], md, author)


def _rows(sql: str, params: dict) -> list[dict]:
    from sqlalchemy import text
    with _pool().get_session() as session:
        rows = session.execute(text(sql), params).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["user_id"] = str(d["user_id"]) if d.get("user_id") else None
        d["author"] = author_of(d)
        d["kind"] = d.get("kind") or "live"
        bm = d.get("backtest_metrics")
        if isinstance(bm, str):
            import json
            try:
                d["backtest_metrics"] = json.loads(bm)
            except ValueError:
                d["backtest_metrics"] = None
        d.pop("user_email", None)
        out.append(d)
    return out


def list_public() -> list[dict]:
    return _rows(f"SELECT {_COLS} FROM {_FROM} WHERE s.is_public ORDER BY s.created_at", {})


def list_for_user(user_id: str) -> list[dict]:
    if not user_id:
        return []
    return _rows(f"SELECT {_COLS} FROM {_FROM} WHERE s.user_id = CAST(:uid AS UUID) "
                 "ORDER BY s.created_at", {"uid": str(user_id)})


def get(strategy_id: int) -> Optional[dict]:
    rows = _rows(f"SELECT {_COLS} FROM {_FROM} WHERE s.id = :id", {"id": int(strategy_id)})
    return rows[0] if rows else None


def get_visible(strategy_id: int, user_id: Optional[str]) -> Optional[dict]:
    """The strategy if it is public or owned by ``user_id``; else None (render as 404)."""
    s = get(strategy_id)
    if not s:
        return None
    if s["is_public"] or (user_id and s["user_id"] == str(user_id)):
        return s
    return None


def create(user_id: str, name: str, description: str = "", skill_md: str = "",
           author_name: Optional[str] = None, is_public: bool = False,
           cloned_from_id: Optional[int] = None) -> int:
    if not user_id:
        raise ValueError("Sign in to create a strategy.")
    name, description, skill_md, author_name = _clean(name, description, skill_md, author_name)
    from sqlalchemy import text
    with _pool().get_session() as session:
        new_id = session.execute(text(f"""
            INSERT INTO {TABLE} (user_id, name, author_name, description, skill_md,
                                 is_public, cloned_from_id)
            VALUES (CAST(:uid AS UUID), :name, :author, :desc, :md, :pub, :src)
            RETURNING id
        """), {"uid": str(user_id), "name": name, "author": author_name, "desc": description,
                "md": skill_md, "pub": bool(is_public), "src": cloned_from_id}).scalar_one()
    return int(new_id)


def update(strategy_id: int, user_id: str, name: str, description: str, skill_md: str,
           author_name: Optional[str], is_public: bool) -> bool:
    name, description, skill_md, author_name = _clean(name, description, skill_md, author_name)
    from sqlalchemy import text
    with _pool().get_session() as session:
        n = session.execute(text(f"""
            UPDATE {TABLE} SET name = :name, author_name = :author, description = :desc,
                   skill_md = :md, is_public = :pub, updated_at = NOW()
            WHERE id = :id AND user_id = CAST(:uid AS UUID)
        """), {"id": int(strategy_id), "uid": str(user_id), "name": name, "author": author_name,
                "desc": description, "md": skill_md, "pub": bool(is_public)}).rowcount
    return n == 1


def set_public(strategy_id: int, user_id: str, is_public: bool) -> bool:
    from sqlalchemy import text
    with _pool().get_session() as session:
        n = session.execute(text(f"""
            UPDATE {TABLE} SET is_public = :pub, updated_at = NOW()
            WHERE id = :id AND user_id = CAST(:uid AS UUID)
        """), {"id": int(strategy_id), "uid": str(user_id), "pub": bool(is_public)}).rowcount
    return n == 1


def delete(strategy_id: int, user_id: str) -> bool:
    from sqlalchemy import text
    with _pool().get_session() as session:
        n = session.execute(text(f"""
            DELETE FROM {TABLE} WHERE id = :id AND user_id = CAST(:uid AS UUID)
        """), {"id": int(strategy_id), "uid": str(user_id)}).rowcount
    return n == 1


def clone(strategy_id: int, user_id: str, author_name: Optional[str] = None) -> Optional[int]:
    """Copy a public (or own) strategy into ``user_id``'s strategies — private, no live link."""
    src = get_visible(strategy_id, user_id)
    if not src:
        return None
    name = src["name"]
    if not name.endswith("(copy)"):
        name = f"{name} (copy)"[:MAX_NAME]
    return create(user_id, name, src.get("description") or "", src.get("skill_md") or "",
                  author_name=author_name, is_public=False, cloned_from_id=src["id"])
