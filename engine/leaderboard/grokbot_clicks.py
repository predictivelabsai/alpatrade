"""Anonymous click counters for Grok Bot templates (sql/54_grokbot_template_clicks.sql)."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)
ACTIONS = ("open", "share", "copy_link", "copy_prompt", "download", "json")
_ready = False


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def _ensure(session) -> None:
    global _ready
    if _ready:
        return
    from sqlalchemy import text
    sql = Path(__file__).resolve().parents[2].joinpath("sql/54_grokbot_template_clicks.sql").read_text()
    session.execute(text(sql))
    _ready = True


def record(strategy_id: int, action: str) -> bool:
    if action not in ACTIONS:
        return False
    try:
        from sqlalchemy import text
        with _pool().get_session() as s:
            _ensure(s)
            s.execute(text("INSERT INTO alpatrade.grokbot_template_clicks (strategy_id, action, count) "
                           "VALUES (:sid, :a, 1) ON CONFLICT (strategy_id, action, day) "
                           "DO UPDATE SET count = alpatrade.grokbot_template_clicks.count + 1"),
                      {"sid": int(strategy_id), "a": action})
            s.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — analytics never break the page
        log.warning("grokbot click record failed: %s", type(exc).__name__)
        return False


def totals() -> list[dict]:
    try:
        from sqlalchemy import text
        with _pool().get_session() as s:
            _ensure(s)
            s.commit()
            rows = s.execute(text(
                "SELECT c.strategy_id, us.name, c.action, SUM(c.count) AS n, MAX(c.day) AS last_day "
                "FROM alpatrade.grokbot_template_clicks c LEFT JOIN alpatrade.user_strategies us "
                "ON us.id = c.strategy_id GROUP BY 1, 2, 3 ORDER BY 1, 3")).mappings().all()
        return [dict(r, last_day=str(r["last_day"])) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("grokbot click totals failed: %s", type(exc).__name__)
        return []
