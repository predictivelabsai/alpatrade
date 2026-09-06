"""Tenant-scoped saved public-market filters and in-app digest alerts."""
from __future__ import annotations

from datetime import date
import json
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import text

from engine.db.pool import DatabasePool

_PAGES = {
    "ipo-pipeline": ("IPO Pipeline", "/ipo-pipeline"),
    "spacs": ("SPACs", "/spacs"),
    "filings": ("SEC Filings", "/filings"),
    "hedge-funds": ("Hedge Fund Filings", "/hedge-funds"),
    "press": ("Press Releases", "/press"),
}
_FILTER_KEYS = {"q", "ticker", "forms", "form", "status", "sort"}


def available_pages() -> dict[str, tuple[str, str]]:
    return _PAGES.copy()


def _filters(values: dict) -> dict[str, str]:
    return {key: str(value).strip() for key, value in values.items()
            if key in _FILTER_KEYS and value is not None and str(value).strip()}


def view_path(page_key: str, filters: dict) -> str:
    _label, path = _PAGES[page_key]
    query = urlencode(_filters(filters))
    return f"{path}?{query}" if query else path


def list_views(user_id: str) -> list[dict]:
    with DatabasePool().get_session() as session:
        rows = session.execute(text("""
            SELECT view_id, name, page_key, filters, daily_digest, created_at
            FROM alpatrade.saved_market_views
            WHERE user_id = CAST(:uid AS UUID) AND is_active = TRUE
            ORDER BY created_at DESC
        """), {"uid": user_id}).mappings().all()
    return [{**dict(row), "view_id": str(row["view_id"]),
             "path": view_path(row["page_key"], row["filters"] or {})} for row in rows]


def save_view(user_id: str, name: str, page_key: str, filters: dict,
              daily_digest: bool = False) -> str | None:
    if page_key not in _PAGES or not (name := name.strip()) or len(name) > 100:
        return None
    with DatabasePool().get_session() as session:
        view_id = session.execute(text("""
            INSERT INTO alpatrade.saved_market_views (user_id, name, page_key, filters, daily_digest)
            VALUES (CAST(:uid AS UUID), :name, :page, CAST(:filters AS JSONB), :daily)
            RETURNING view_id
        """), {"uid": user_id, "name": name, "page": page_key,
               "filters": json.dumps(_filters(filters)), "daily": daily_digest}).scalar()
    return str(view_id) if view_id else None


def delete_view(user_id: str, view_id: str) -> bool:
    try:
        UUID(view_id)
    except (TypeError, ValueError):
        return False
    with DatabasePool().get_session() as session:
        result = session.execute(text("""
            DELETE FROM alpatrade.saved_market_views
            WHERE view_id = CAST(:view_id AS UUID) AND user_id = CAST(:uid AS UUID)
        """), {"view_id": view_id, "uid": user_id})
    return result.rowcount == 1


def list_alerts(user_id: str, limit: int = 30) -> list[dict]:
    with DatabasePool().get_session() as session:
        rows = session.execute(text("""
            SELECT alert_id, title, body, target_path, read_at, created_at
            FROM alpatrade.market_alerts
            WHERE user_id = CAST(:uid AS UUID)
            ORDER BY created_at DESC LIMIT :limit
        """), {"uid": user_id, "limit": min(max(limit, 1), 100)}).mappings().all()
    return [{**dict(row), "alert_id": str(row["alert_id"])} for row in rows]


def mark_alerts_read(user_id: str) -> None:
    with DatabasePool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.market_alerts SET read_at = NOW()
            WHERE user_id = CAST(:uid AS UUID) AND read_at IS NULL
        """), {"uid": user_id})


def generate_daily_alerts(alert_date: date | None = None) -> int:
    """Create one in-app digest alert per opted-in saved view per UTC day."""
    alert_date = alert_date or date.today()
    with DatabasePool().get_session() as session:
        views = session.execute(text("""
            SELECT view_id, user_id, name, page_key, filters
            FROM alpatrade.saved_market_views
            WHERE is_active = TRUE AND daily_digest = TRUE
        """)).mappings().all()
        count = 0
        for view in views:
            path = view_path(view["page_key"], view["filters"] or {})
            result = session.execute(text("""
                INSERT INTO alpatrade.market_alerts
                    (user_id, view_id, alert_date, title, body, target_path)
                VALUES (:uid, :view_id, :alert_date, :title, :body, :path)
                ON CONFLICT (view_id, alert_date) DO NOTHING
            """), {"uid": view["user_id"], "view_id": view["view_id"], "alert_date": alert_date,
                   "title": f"Daily view ready: {view['name']}",
                   "body": "Your saved market view is ready to review.", "path": path})
            count += int(result.rowcount or 0)
    return count
