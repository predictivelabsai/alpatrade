"""Admin "Running strategies + user activity" data (read-only SQL, each block isolated).

Runner liveness comes from alpatrade.live_runner_heartbeats / live_runner_state, written by
scripts/user_live_scheduler.py (key ``user-btd:<account>:<cid_prefix>[:paper]``) and the
operator btd-scheduler (``buy_the_dip_mag7_minhold_live:<account>``). Nothing here writes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

log = logging.getLogger("engine.admin_running")

ACTING = ("act", "renew", "takeover")
# A runner that acted within this window is "running" (passes stop outside market hours and
# over weekends, so allow a long weekend). Within LIVE_NOW it is "running now".
FRESH = timedelta(hours=96)
LIVE_NOW = timedelta(minutes=30)
ACTIVE_STATES = ("active", "pending_runner", "paused", "queued", "running")


def runner_key(mode: str, account_ref: Any, cid_prefix: Any) -> Optional[str]:
    if not account_ref or not cid_prefix:
        return None
    return f"user-btd:{account_ref}:{cid_prefix}" + (":paper" if mode == "paper" else "")


def _aware(ts):
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def best_heartbeat(rows: list[dict]) -> Optional[dict]:
    """The acting instance's heartbeat (latest last_acted_at), else the latest pass."""
    if not rows:
        return None
    acting = [r for r in rows if r.get("last_acted_at")]
    pool = acting or rows
    return max(pool, key=lambda r: _aware(r.get("last_acted_at") or r.get("last_pass_at"))
               or datetime.min.replace(tzinfo=timezone.utc))


def runner_alive(hb: Optional[dict], now: Optional[datetime] = None, window: timedelta = FRESH) -> bool:
    if not hb or (hb.get("last_decision") or "") not in ACTING:
        return False
    t = _aware(hb.get("last_acted_at"))
    return bool(t and (now or datetime.now(timezone.utc)) - t <= window)


def effective_status(status: str, hb: Optional[dict], now: Optional[datetime] = None) -> str:
    """Display status: a 'pending_runner'/'active' activation whose runner heartbeat confirms
    it is acting reads 'running' (the DB row itself is never changed here)."""
    if status in ("pending_runner", "active") and runner_alive(hb, now):
        return "running"
    if status == "active":
        return "active (no runner heartbeat)" if hb is not None else "active"
    return status


def runner_note(hb: Optional[dict], now: Optional[datetime] = None) -> str:
    if not hb:
        return "no heartbeat"
    now = now or datetime.now(timezone.utc)
    t = _aware(hb.get("last_acted_at") or hb.get("last_pass_at"))
    if not t:
        return "no heartbeat"
    age = now - t
    when = (f"{int(age.total_seconds() // 60)}m ago" if age < timedelta(hours=2)
            else f"{age.total_seconds() / 3600:.0f}h ago")
    idle = "" if age <= LIVE_NOW else " (idle, outside market hours)" if age <= FRESH else " (stale)"
    return f"{hb.get('instance') or '?'} · {hb.get('last_decision') or '?'} · {when}{idle}"


Q_ACTIVATIONS = """
SELECT a.id, u.email, u.display_name, a.user_strategy_id, s.name AS strategy, a.mode, a.account_ref,
       a.cid_prefix, a.allocation_usd, a.cash_only, a.status, a.job_id, a.confirmed_at, a.created_at, a.updated_at
FROM alpatrade.user_strategy_activations a
JOIN alpatrade.users u ON u.user_id = a.user_id
LEFT JOIN alpatrade.user_strategies s ON s.id = a.user_strategy_id
ORDER BY a.id"""
Q_HEARTBEATS = """
SELECT runner_key, instance, host, role, mode, last_pass_at, last_acted_at, last_decision, last_detail
FROM alpatrade.live_runner_heartbeats"""
Q_STATE = """
SELECT st.runner_key, st.run_id, st.lease_holder, st.lease_expires_at, st.created_at,
       r.strategy, r.config, u.email, u.display_name
FROM alpatrade.live_runner_state st
LEFT JOIN alpatrade.runs r ON r.run_id::text = st.run_id
LEFT JOIN alpatrade.users u ON u.user_id = r.user_id"""
Q_LAST_TRADE = """
SELECT run_id, MAX(GREATEST(entry_time, COALESCE(exit_time, entry_time))) AS last_trade, COUNT(*) AS n
FROM alpatrade.trades WHERE trade_type = 'live' GROUP BY run_id"""

Q_USERS = """
SELECT u.user_id::text, u.email, u.display_name, u.role, u.created_at, u.last_login_at,
       (u.alpaca_api_key_enc IS NOT NULL) AS has_keys,
       (SELECT COUNT(*) FROM alpatrade.user_logins l WHERE l.user_id = u.user_id
          AND l.created_at > NOW() - INTERVAL '7 days') AS logins_7d,
       (SELECT COUNT(*) FROM alpatrade.user_logins l WHERE l.user_id = u.user_id
          AND l.created_at > NOW() - INTERVAL '30 days') AS logins_30d,
       (SELECT COUNT(*) FROM alpatrade.user_strategies s WHERE s.user_id = u.user_id) AS strategies,
       (SELECT COUNT(*) FROM alpatrade.user_strategies s WHERE s.user_id = u.user_id
          AND s.cloned_from_id IS NOT NULL) AS clones,
       (SELECT COUNT(*) FROM alpatrade.user_strategy_activations a WHERE a.user_id = u.user_id) AS activations,
       (SELECT COUNT(*) FROM alpatrade.user_strategy_activations a WHERE a.user_id = u.user_id
          AND a.status = ANY(ARRAY['active','pending_runner','paused','queued','running'])) AS active_activations
FROM alpatrade.users u
ORDER BY GREATEST(u.last_login_at, u.created_at) DESC NULLS LAST"""

Q_EVENTS = """
SELECT * FROM (
  SELECT l.created_at AS at, u.email, 'login' AS kind, COALESCE(l.method, '') AS detail
  FROM alpatrade.user_logins l JOIN alpatrade.users u ON u.user_id = l.user_id
  UNION ALL
  SELECT s.created_at, u.email, CASE WHEN s.cloned_from_id IS NOT NULL THEN 'clone' ELSE 'strategy' END, s.name
  FROM alpatrade.user_strategies s JOIN alpatrade.users u ON u.user_id = s.user_id
  UNION ALL
  SELECT a.created_at, u.email, 'activation', a.mode || ' · ' || COALESCE(s.name, '#' || a.user_strategy_id)
  FROM alpatrade.user_strategy_activations a JOIN alpatrade.users u ON u.user_id = a.user_id
  LEFT JOIN alpatrade.user_strategies s ON s.id = a.user_strategy_id
  UNION ALL
  SELECT a.updated_at, u.email, 'deactivation', a.mode || ' · ' || COALESCE(s.name, '#' || a.user_strategy_id)
  FROM alpatrade.user_strategy_activations a JOIN alpatrade.users u ON u.user_id = a.user_id
  LEFT JOIN alpatrade.user_strategies s ON s.id = a.user_strategy_id
  WHERE a.status = 'deactivated' AND a.updated_at IS NOT NULL
  UNION ALL
  SELECT e.first_at, u.email, e.event, ''
  FROM alpatrade.activation_events e JOIN alpatrade.users u ON u.user_id = e.user_id
  WHERE e.event IN ('registered', 'keys_connected')
) x WHERE at IS NOT NULL ORDER BY at DESC LIMIT :lim"""


def _default_execute():
    from sqlalchemy import text
    from utils.db.db_pool import DatabasePool
    pool = DatabasePool()

    def execute(sql: str, params: dict | None = None) -> list[dict]:
        with pool.get_session() as s:
            return [dict(r) for r in s.execute(text(sql), params or {}).mappings().all()]
    return execute


def _safe(execute, name, sql, params=None):
    try:
        return execute(sql, params or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("admin running %s failed: %s", name, type(exc).__name__)
        return None


def running(execute: Callable | None = None, now: datetime | None = None, include_all: bool = False) -> dict:
    """{'rows': [...], 'error': bool}. One row per activation plus operator (system) runners."""
    execute = execute or _default_execute()
    now = now or datetime.now(timezone.utc)
    acts = _safe(execute, "activations", Q_ACTIVATIONS)
    hbs = _safe(execute, "heartbeats", Q_HEARTBEATS) or []
    states = _safe(execute, "state", Q_STATE) or []
    trades = {str(r["run_id"]): r for r in (_safe(execute, "trades", Q_LAST_TRADE) or [])}
    by_key: dict[str, list] = {}
    for h in hbs:
        by_key.setdefault(str(h["runner_key"]), []).append(h)
    state_by_key = {str(s["runner_key"]): s for s in states}
    rows = []
    for a in acts or []:
        key = runner_key(a["mode"], a["account_ref"], a["cid_prefix"])
        hb = best_heartbeat(by_key.get(key or "", []))
        st = state_by_key.get(key or "") or {}
        tr = trades.get(str(st.get("run_id"))) if st.get("run_id") else None
        rows.append({"kind": "user", "id": a["id"], "email": a["email"], "name": a["display_name"],
                     "strategy": a["strategy"] or f"#{a['user_strategy_id']}", "mode": a["mode"],
                     "account": a["account_ref"], "prefix": a["cid_prefix"], "allocation": a["allocation_usd"],
                     "db_status": a["status"], "status": effective_status(a["status"], hb, now),
                     "runner": runner_note(hb, now) if key else ("paper job " + str(a["job_id"])[:8] if a["job_id"] else "—"),
                     "last_trade": tr["last_trade"] if tr else None, "trades": tr["n"] if tr else 0,
                     "created": a["created_at"], "active": a["status"] in ACTIVE_STATES})
    for key, st in state_by_key.items():
        if key.startswith("user-btd:"):
            continue
        hb = best_heartbeat(by_key.get(key, []))
        tr = trades.get(str(st.get("run_id"))) if st.get("run_id") else None
        cfg = st.get("config") or {}
        alloc = cfg.get("allocation_usd") or cfg.get("capital") if isinstance(cfg, dict) else None
        if not alloc and isinstance(cfg, dict) and cfg.get("position_size"):
            alloc = f"{float(cfg['position_size']) * 100:.1f}% of equity / position"
        slug, _, acct = key.rpartition(":")
        alive = runner_alive(hb, now)
        rows.append({"kind": "system", "id": None, "email": st.get("email") or "system",
                     "name": (st.get("display_name") or "") + " (system)", "strategy": st.get("strategy") or slug,
                     "mode": "live" if "live" in slug else "paper", "account": acct, "prefix": slug,
                     "allocation": alloc, "db_status": "system", "status": "running" if alive else "stopped",
                     "runner": runner_note(hb, now), "last_trade": tr["last_trade"] if tr else None,
                     "trades": tr["n"] if tr else 0, "created": st.get("created_at"), "active": alive})
    if not include_all:
        rows = [r for r in rows if r["active"]]
    return {"rows": rows, "error": acts is None}


def activity(execute: Callable | None = None, limit: int = 60) -> dict:
    execute = execute or _default_execute()
    return {"users": _safe(execute, "users", Q_USERS),
            "events": _safe(execute, "events", Q_EVENTS, {"lim": int(limit)})}


def heartbeats_for(execute: Callable, keys: list[str]) -> dict[str, dict]:
    """runner_key -> best heartbeat, for status labels elsewhere (My strategies)."""
    if not keys:
        return {}
    rows = execute(Q_HEARTBEATS + " WHERE runner_key = ANY(:k)", {"k": list(keys)})
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(str(r["runner_key"]), []).append(r)
    return {k: best_heartbeat(v) for k, v in by.items()}
