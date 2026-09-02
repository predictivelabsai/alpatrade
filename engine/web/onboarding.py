"""First-run onboarding state — Start Here checklist + paper-deploy links.

Reads only existing production tables (``alpatrade.runs``,
``alpatrade.backtest_summaries``) scoped to the signed-in user, so the
dashboard checklist can never drift from reality: every step is a query,
not a stored flag. Paper-deploy commands are composed from a backtest
run's best variation so "deploy to paper" really does trade the tested
config. Read-only, DB-failure tolerant — checklist rendering must never
break the dashboard. Also hosts the activation-event funnel (phase 3):
``record_event`` writes first-occurrence markers into
``alpatrade.activation_events``; ``funnel_counts`` / ``week1_cohorts``
read them for the monitoring dial.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.parse import quote

from utils.paper_strategies import (
    PARAM_SCHEMA,
    canonical_strategy,
    storage_params,
    strategy_command,
)


def _pool():
    from utils.db.db_pool import DatabasePool
    return DatabasePool()


def has_linked_account(user_id: str) -> bool:
    """True when the user has their own Alpaca keys (not the shared fallback)."""
    try:
        from engine.auth import get_user_accounts
        return bool(get_user_accounts(user_id))
    except Exception:  # noqa: BLE001
        return False


def has_backtests(user_id: str) -> bool:
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            row = session.execute(
                text("""
                    SELECT 1 FROM alpatrade.runs
                    WHERE user_id = :uid AND mode = 'backtest'
                    LIMIT 1
                """),
                {"uid": user_id},
            ).first()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def has_paper_activity(user_id: str) -> bool:
    """True when the user has ever run a paper session (live or recorded)."""
    try:
        from utils.agent_runner import get_all_running_agents
        if any(r.get("mode") == "paper" for r in get_all_running_agents(user_id=user_id)):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            row = session.execute(
                text("""
                    SELECT 1 FROM alpatrade.runs
                    WHERE user_id = :uid AND mode = 'paper'
                    LIMIT 1
                """),
                {"uid": user_id},
            ).first()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def best_backtest_for_run(run_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The best-variation row (strategy slug + params + headline metrics) of a run.

    Two storage paths exist in production: the agent-storage grid path writes
    ``alpatrade.backtest_summaries`` rows (is_best) and the orchestrator path
    stores everything in ``alpatrade.runs.results`` JSON under ``best_config``.
    This returns whichever carries the run's parameters.
    """
    from sqlalchemy import text
    sql = text("""
        SELECT r.strategy, r.strategy_slug, s.params, s.total_return,
               s.win_rate, s.max_drawdown, s.total_trades
        FROM alpatrade.runs r
        LEFT JOIN alpatrade.backtest_summaries s
               ON s.run_id = r.run_id AND s.is_best
        WHERE r.run_id = :run_id AND r.mode = 'backtest'
              {scope}
        ORDER BY r.created_at DESC
        LIMIT 1
    """)
    binds: Dict[str, Any] = {"run_id": run_id}
    scope = ""
    if user_id:
        scope = "AND r.user_id = :uid"
        binds["uid"] = user_id
    try:
        with _pool().get_session() as session:
            row = session.execute(
                text(str(sql).format(scope=scope)), binds).mappings().first()
        if row and row.get("params"):
            return dict(row)
        if not row:
            return None
        return dict(row) | _best_config_from_results(run_id) or dict(row)
    except Exception:  # noqa: BLE001
        return None


def _best_config_from_results(run_id: str) -> Optional[Dict[str, Any]]:
    """Best-variation data from the orchestrator path's runs.results JSON."""
    from sqlalchemy import text
    try:
        import json as _json
        with _pool().get_session() as session:
            r = session.execute(
                text("""
                    SELECT results FROM alpatrade.runs
                    WHERE run_id = :r AND mode = 'backtest'
                """),
                {"r": run_id},
            ).mappings().first()
        if not r or not r["results"]:
            return None
        res = r["results"]
        if isinstance(res, str):
            res = _json.loads(res)
        cfg = res.get("best_config") or {}
        params = cfg.get("params") or {}
        if not isinstance(params, dict):
            return None
        # Metrics live in all_results_summary entries keyed by params.
        metrics = {}
        for entry in (res.get("all_results_summary") or []):
            if entry.get("params") == params:
                metrics = entry
                break
        return {
            "strategy": (res.get("strategy") or (cfg.get("config") or {}).get("strategy")),
            "strategy_slug": None,
            "params": params,
            "total_return": metrics.get("total_return"),
            "win_rate": metrics.get("win_rate"),
            "max_drawdown": metrics.get("max_drawdown"),
            "total_trades": metrics.get("total_trades"),
        }
    except Exception:  # noqa: BLE001
        return None


def latest_backtest_config(user_id: str) -> Optional[Dict[str, Any]]:
    """The user's most recent backtest run and its best-variation config."""
    if not user_id:
        return None
    from sqlalchemy import text
    try:
        with _pool().get_session() as session:
            row = session.execute(
                text("""
                    SELECT run_id FROM alpatrade.runs
                    WHERE user_id = :uid AND mode = 'backtest'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"uid": user_id},
            ).first()
        if not row:
            return None
        return best_backtest_for_run(str(row[0]), user_id)
    except Exception:  # noqa: BLE001
        return None


def paper_deploy_command(cfg: Optional[Dict[str, Any]]) -> Optional[str]:
    """A user-runnable ``agent:paper`` command trading the backtested params.

    Thin wrapper over ``utils.paper_strategies`` — any of the four strategies
    whose backtest recorded params can be deployed. DB backtest params use the
    storage convention (ratio percents, legacy key names like ``take_profit``);
    the schema module owns the renames and ratio→percent translation, so this
    layer no longer needs its own. Returns None for unknown strategies or
    params the schema cannot resolve — the caller just omits the CTA instead
    of pretending precision.
    """
    if not cfg:
        return None
    strategy = canonical_strategy(str(cfg.get("strategy") or ""))
    if strategy not in PARAM_SCHEMA:
        return None
    params = cfg.get("params")
    if isinstance(params, str):
        try:
            import json as _json
            params = _json.loads(params)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(params, dict):
        return None
    try:
        command = strategy_command(strategy, storage_params(strategy, params))
    except (ValueError, TypeError):  # noqa: BLE001
        return None
    raw_symbols = params.get("symbols")
    if isinstance(raw_symbols, (list, tuple)) and raw_symbols:
        clean = [str(s).upper().strip() for s in raw_symbols if s][:10]
        if clean:
            command += " symbols:" + ",".join(clean)
    return command


def autorun_url(command: str, draft: bool = False) -> str:
    """Open a fresh chat that (auto-)sends ``command`` through the normal
    chat pipeline — the same endpooint the composer posts to."""
    return f"/app?new=1&autorun={quote(command)}" + ("&draft=1" if draft else "")


# ---------------------------------------------------------------------------
# Param formatting — shared by the runs table and the shareable report pages,
# so both surfaces always agree on units (ratios → %, VIX in points, days).
# ---------------------------------------------------------------------------

PARAM_LABELS = {
    "dip_threshold": "dip", "take_profit": "TP",
    "take_profit_threshold": "TP", "stop_loss": "SL",
    "stop_loss_threshold": "SL", "hold_days": "hold",
    "momentum_threshold": "mom", "lookback_period": "lb",
    "vix_threshold": "VIX", "hold_overnight": "overnight",
    "risk_pct": "risk", "risk_per_trade_pct": "risk",
    "contraction_threshold": "contract",
    "box_lookback": "box", "wedge_lookback": "wedge",
    "scale_out_1_5r_pct": "1.5R", "scale_out_3r_pct": "3R",
    "capital_per_trade": "cap", "position_size": "pos",
}

# Units per param kind: percent-ish params render with "%", hold/lookback in
# days ("d"), VIX level in points (no unit), dimensionless ratios unscaled,
# dollar amounts with "$"; unlabeled numeric params default to percent.
PARAM_KINDS = {
    "dip_threshold": "percent", "take_profit": "percent",
    "take_profit_threshold": "percent", "stop_loss": "percent",
    "stop_loss_threshold": "percent", "momentum_threshold": "percent",
    "risk_pct": "percent", "risk_per_trade_pct": "percent",
    "scale_out_1_5r_pct": "percent", "scale_out_3r_pct": "percent",
    "hold_days": "days", "lookback_period": "days",
    "box_lookback": "days", "wedge_lookback": "days",
    "vix_threshold": "points",
    "contraction_threshold": "ratio", "position_size": "ratio",
    "capital_per_trade": "dollars", "hold_overnight": "bool",
}


def format_params(params: dict) -> str:
    """Compact human summary of best-config params, e.g. ``dip 5% · hold 3d``.

    Ratio values (0 < |v| < 1) are percent-scaled per the storage convention
    except for ``points`` (VIX level), ``ratio`` (dimensionless thresholds)
    and ``days`` keys; ``bool`` renders on/off; dollar amounts keep the "$"
    and are never percent-scaled; unknown keys fall back to ``key value`` so
    no strategy's params ever render as an empty string.
    """
    bits = []
    for key, value in (params or {}).items():
        if value is None:
            continue
        kind = PARAM_KINDS.get(key)
        label = PARAM_LABELS.get(key, key)
        if kind == "bool":
            bits.append(f"{label} {'on' if value else 'off'}")
            continue
        if kind in ("ratio", "points") \
                or not isinstance(value, (int, float)) or isinstance(value, bool):
            bits.append(f"{label} {value}")
        elif kind == "days":
            bits.append(f"{label} {value:g}d")
        elif kind == "dollars":
            bits.append(f"{label} ${float(value):,.0f}")
        else:  # percent-kind: storage ratios scale to percent
            scaled = float(value) * 100 if 0 < abs(value) < 1 else value
            bits.append(f"{label} {scaled:g}%")
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Activation events (Start Here plan, phase 3) — the funnel dial.
# ---------------------------------------------------------------------------

_ACTIVATION_EVENTS = ("registered", "keys_connected",
                      "first_backtest", "first_paper_run")


def record_event(user_id, event: str, meta: Optional[dict] = None) -> None:
    """Record the first occurrence of an activation event. Idempotent and
    failure-tolerant: measuring must never break the flow that feeds it."""
    if not user_id or event not in _ACTIVATION_EVENTS:
        return
    from sqlalchemy import text

    from utils.db.db_pool import DatabasePool
    try:
        with _pool().get_session() as session:
            session.execute(
                text("""
                    INSERT INTO alpatrade.activation_events (user_id, event, meta)
                    VALUES (CAST(:uid AS UUID), :event, CAST(:meta AS JSONB))
                    ON CONFLICT (user_id, event) DO NOTHING
                """),
                {"uid": str(user_id), "event": event,
                 "meta": json.dumps(meta) if meta else None},
            )
    except Exception:  # noqa: BLE001
        pass


def funnel_counts() -> Dict[str, int]:
    """How many users have reached each activation step."""
    from sqlalchemy import text

    counts = {e: 0 for e in _ACTIVATION_EVENTS}
    try:
        with _pool().get_session() as session:
            rows = session.execute(
                text("""
                    SELECT event, COUNT(DISTINCT user_id)::int AS n
                    FROM alpatrade.activation_events
                    GROUP BY event
                """),
            ).fetchall()
        for event, n in rows:
            if event in counts:
                counts[event] = n
        return counts
    except Exception:  # noqa: BLE001
        return counts


def week1_cohorts(days: int = 30) -> Dict[str, Any]:
    """Week-1 retention for recent signups.

    For every user registered in the last ``days`` days: did any trading or
    chat activity happen 1–7 days after registration? Returns cohort-wide
    counts plus the per-user list for the monitoring view.
    """
    from sqlalchemy import text

    try:
        with _pool().get_session() as session:
            rows = session.execute(
                text("""
                    WITH regs AS (
                        SELECT user_id, first_at
                        FROM alpatrade.activation_events
                        WHERE event = 'registered'
                              AND first_at > NOW() - (:days * INTERVAL '1 day')
                    )
                    SELECT r.user_id::text AS user_id,
                           r.first_at,
                           EXISTS (
                               SELECT 1 FROM alpatrade.runs run
                               WHERE run.user_id = r.user_id
                                     AND run.created_at >= r.first_at + INTERVAL '1 day'
                                     AND run.created_at <  r.first_at + INTERVAL '8 days'
                           ) OR EXISTS (
                               SELECT 1
                               FROM alpatrade.chat_conversations c
                               JOIN alpatrade.chat_messages m
                                     ON m.thread_id = c.thread_id
                               WHERE c.user_id = r.user_id
                                     AND m.created_at >= r.first_at + INTERVAL '1 day'
                                     AND m.created_at <  r.first_at + INTERVAL '8 days'
                           ) AS returned_d7
                    FROM regs r
                    ORDER BY r.first_at DESC
                """),
                {"days": days},
            ).mappings().all()
        users = [dict(r) for r in rows]
        returned = sum(1 for u in users if u.get("returned_d7"))
        return {"users": users, "returned": returned, "total": len(users)}
    except Exception:  # noqa: BLE001
        return {"users": [], "returned": 0, "total": 0}