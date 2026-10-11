""""View more" detail for a leaderboard strategy: equity curve vs SPY (same base 100),
drawdown, daily returns, trade markers, parameters and the skill text.

Live strategies: daily session-close equity from the owner's live run (``results.daily``),
chained as a time-weighted index with each day's deposits/withdrawals removed
(engine/reporting/cash_flows.py), so a deposit never shows as a jump. SPY is indexed to 100
on the same start. Trades come from ``alpatrade.trades`` for that run; parameters from
``alpatrade.strategy_configs`` (name = the strategy's live slug).

Backtest strategies: ``backtest_metrics.equity_curve`` = {dates, equity, spy} stored when the
backtest is published (scripts/cwt_pipeline.py, scripts/seed_semi7_backtest.py); parameters from
the skill's Parameters block. If no curve is stored the charts are omitted (never invented).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

log = logging.getLogger("leaderboard.detail")


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def index_series(dates: list, equity: list, spy: list, flows: Optional[list] = None,
                 start_equity: Optional[float] = None, start_spy: Optional[float] = None) -> dict:
    """Base-100 TWR index vs SPY; the shared implementation lives in
    engine/reporting/perf_chart.performance_series (also used by /dashboard and /live/account)."""
    from engine.reporting.perf_chart import performance_series
    return performance_series(dates, equity, spy, flows, start_equity, start_spy)


def _strategy_config(slug: str) -> Optional[dict]:
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    with DatabasePool().get_session() as s:
        r = s.execute(text("SELECT name, display_name, params, execution, version, is_active "
                           "FROM alpatrade.strategy_configs WHERE name = :n"), {"n": slug}).mappings().first()
    if not r:
        return None
    d = dict(r)
    for k in ("params", "execution"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


def _trades(run_id: Optional[str]) -> list[dict]:
    if not run_id:
        return []
    from scripts.daily_live_report import runner_trades
    out = []
    for t in runner_trades(run_id):
        out.append({"symbol": t.get("symbol"),
                    "entry": str(t.get("entry_time") or "")[:10] or None,
                    "exit": str(t.get("exit_time") or "")[:10] or None,
                    "pnl": _num(t.get("pnl")), "entry_price": _num(t.get("entry_price")),
                    "exit_price": _num(t.get("exit_price"))})
    return out


def live_detail(strategy: dict) -> dict:
    """Series + params + trades for a live strategy (best-effort, {} parts when unavailable)."""
    from engine.leaderboard import perf
    slug, uid = strategy.get("live_strategy_slug"), strategy.get("user_id")
    out: dict[str, Any] = {"kind": "live", "series": {}, "trades": [], "config": None}
    if not slug or not uid:
        return out
    try:
        run = perf._live_run(str(uid), slug)
    except Exception as exc:  # noqa: BLE001
        log.warning("detail run lookup failed: %s", type(exc).__name__)
        run = None
    if run:
        cfg = run.get("config") or {}
        res = run.get("results") or {}
        cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
        res = json.loads(res) if isinstance(res, str) else res
        daily = res.get("daily") or {}
        keys = sorted(k for k in daily if str(k) >= str(cfg.get("started") or ""))
        flows = perf._owner_flows(str(uid), run)
        out["series"] = index_series(keys, [daily[k].get("equity") for k in keys],
                                     [daily[k].get("spy") for k in keys], flows,
                                     cfg.get("start_equity"), cfg.get("start_spy"))
        out["cash_flows_ok"] = flows is not None
        try:
            out["trades"] = _trades(run.get("run_id"))
        except Exception:  # noqa: BLE001
            out["trades"] = []
    try:
        out["config"] = _strategy_config(slug)
    except Exception as exc:  # noqa: BLE001
        log.warning("detail config lookup failed: %s", type(exc).__name__)
    return out


def backtest_detail(strategy: dict) -> dict:
    from engine.leaderboard.skill import extract_params
    bm = strategy.get("backtest_metrics") if isinstance(strategy.get("backtest_metrics"), dict) else {}
    cur = bm.get("equity_curve") or {}
    series = {}
    if cur.get("dates") and cur.get("equity"):
        series = index_series(cur["dates"], cur["equity"], cur.get("spy") or [None] * len(cur["dates"]))
    p = extract_params(strategy.get("skill_md") or "") or {}
    return {"kind": "backtest", "series": series, "trades": [],
            "config": {"name": p.get("name"), "params": p.get("params") or p, "execution": p.get("execution")}}


def detail(strategy: dict, metrics: dict) -> dict:
    if metrics.get("is_backtest"):
        return backtest_detail(strategy)
    return live_detail(strategy)
