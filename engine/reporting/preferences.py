"""Per-user daily email report preferences (``alpatrade.user_report_preferences``).

Two scheduled emails honour these flags (see :mod:`engine.autonomy.schedule`):

* ``report_live_daily``  — ``scripts/daily_live_report.py`` (default **on**)
* ``report_paper_daily`` — ``scripts/daily_pnl_report.py``  (default **off**)

A user without a row gets :data:`DEFAULTS`. The table comes from
``sql/39_user_report_preferences.sql``; writes also create it lazily so the
Settings page works before the migration is applied.

If the preference lookup itself fails (DB down / table missing) the senders keep
their pre-preference behaviour and log a warning, rather than silently dropping
every report for the day.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

log = logging.getLogger("reporting.preferences")

TABLE = "alpatrade.user_report_preferences"
LIVE = "report_live_daily"
PAPER = "report_paper_daily"
FIELDS = (LIVE, PAPER)
DEFAULTS = {LIVE: True, PAPER: False}

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    user_id UUID PRIMARY KEY REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    report_live_daily  BOOLEAN NOT NULL DEFAULT TRUE,
    report_paper_daily BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"""
_ddl_done = False


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def _row_to_prefs(row) -> dict:
    return {LIVE: bool(row[0]), PAPER: bool(row[1])}


def get_report_preferences(user_id: str) -> dict:
    """The user's effective preferences (defaults when no row or on error)."""
    prefs = preferences_for([user_id]) if user_id else {}
    return dict((prefs or {}).get(str(user_id)) or DEFAULTS)


def preferences_for(user_ids: Iterable[str]) -> Optional[dict[str, dict]]:
    """Effective preferences for many users: ``{user_id: {field: bool}}``.

    Users without a row get :data:`DEFAULTS`. Returns ``None`` when the lookup
    fails so callers can fall back to legacy behaviour explicitly."""
    ids = sorted({str(u) for u in user_ids if u})
    out = {uid: dict(DEFAULTS) for uid in ids}
    if not ids:
        return out
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            rows = session.execute(text(f"""
                SELECT CAST(user_id AS TEXT), {LIVE}, {PAPER}
                FROM {TABLE}
                WHERE CAST(user_id AS TEXT) = ANY(:ids)
            """), {"ids": ids}).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning("report preference lookup failed: %s", type(exc).__name__)
        return None
    for uid, live, paper in rows:
        out[str(uid)] = _row_to_prefs((live, paper))
    return out


def store_report_preferences(user_id: str, **fields) -> None:
    """Upsert any subset of :data:`FIELDS` (booleans) for one user."""
    updates = {k: bool(v) for k, v in fields.items() if k in FIELDS}
    if not user_id or not updates:
        return
    global _ddl_done
    from sqlalchemy import text
    cols = list(updates)
    set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols] + ["updated_at = NOW()"])
    with _pool().get_session() as session:
        if not _ddl_done:
            session.execute(text(_DDL))
            _ddl_done = True
        session.execute(text(f"""
            INSERT INTO {TABLE} (user_id, {", ".join(cols)})
            VALUES (:user_id, {", ".join(f":{c}" for c in cols)})
            ON CONFLICT (user_id) DO UPDATE SET {set_clause}
        """), {"user_id": user_id, **updates})


def filter_opted_in(targets: list[dict], field: str, report: str) -> list[dict]:
    """Keep only targets whose owner wants ``field``; log each opted-out skip.

    On a failed lookup every target is kept (legacy behaviour) with a warning."""
    prefs = preferences_for(t.get("user_id") for t in targets)
    if prefs is None:
        log.warning("%s: report preferences unavailable — sending to all %d target(s)",
                    report, len(targets))
        return list(targets)
    kept = []
    for t in targets:
        if prefs.get(str(t.get("user_id")), DEFAULTS).get(field, DEFAULTS[field]):
            kept.append(t)
        else:
            log.info("%s skipped for user=%s (opted out in Settings)", report, t.get("user_id"))
    return kept


__all__ = ["DEFAULTS", "FIELDS", "LIVE", "PAPER", "filter_opted_in",
           "get_report_preferences", "preferences_for", "store_report_preferences"]
