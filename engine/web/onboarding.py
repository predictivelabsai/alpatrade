"""First-run onboarding state — Start Here checklist + paper-deploy links.

Reads only existing production tables (``alpatrade.runs``,
``alpatrade.backtest_summaries``) scoped to the signed-in user, so the
dashboard checklist can never drift from reality: every step is a query,
not a stored flag. Paper-deploy commands are composed from a backtest
run's best variation so "deploy to paper" really does trade the tested
config. Read-only, DB-failure tolerant — checklist rendering must never
break the dashboard.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.parse import quote


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
    """The best-variation row (strategy slug + params + headline metrics) of a run."""
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
        return dict(row) if row else None
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

    Only buy-the-dip is supported today — it is the one strategy whose
    paper agent consumes explicit thresholds. Returns None otherwise, and
    the caller just omits the CTA instead of pretending precision.
    """
    if not cfg:
        return None
    strategy = str(cfg.get("strategy") or "")
    if strategy != "buy_the_dip":
        return None
    params = cfg.get("params")
    if isinstance(params, str):
        try:
            import json as _json
            params = _json.loads(params)
        except Exception:  # noqa: BLE001
            params = {}
    if not isinstance(params, dict):
        return None
    try:
        dip = _pct(params["dip_threshold"])
        tp = _pct(params["take_profit"])
        sl = _pct(params["stop_loss"])
        hold = int(params["hold_days"])
    except (KeyError, TypeError, ValueError):
        return None
    symbols = ""
    raw_symbols = params.get("symbols")
    if isinstance(raw_symbols, (list, tuple)) and raw_symbols:
        clean = [str(s).upper().strip() for s in raw_symbols if s][:5]
        if clean:
            symbols = " symbols:" + ",".join(clean)
    return (
        f"agent:paper strategy:{strategy}"
        f" dip_threshold:{_num(dip)}"
        f" take_profit_threshold:{_num(tp)}"
        f" stop_loss_threshold:{_num(sl)}"
        f" hold_days:{hold}"
        f"{symbols}"
    )


def _pct(value: Any) -> float:
    """Backtest params store ratios (0.05 = 5%); agent:paper wants percent.

    Same convention as ``utils.strategy_slug._fmt_pct``: anything in (0,1)
    is treated as a ratio and scaled by 100.
    """
    v = float(value)
    if 0 < abs(v) < 1:
        return round(v * 100, 4)
    return v


def _num(value: float) -> str:
    return f"{value:g}"


def autorun_url(command: str, draft: bool = False) -> str:
    """Open a fresh chat that (auto-)sends ``command`` through the normal
    chat pipeline — the same endpooint the composer posts to."""
    return f"/app?new=1&autorun={quote(command)}" + ("&draft=1" if draft else "")