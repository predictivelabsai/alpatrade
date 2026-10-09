"""Leaderboard figures from REAL live data inside AlpaTrade.

For a strategy linked to its owner's live runner (``live_strategy_slug``), the figures come
from that run in ``alpatrade.runs`` (``mode='live'``, same ``user_id``): the start date,
start equity and start SPY in ``config`` and the latest daily **session-close** snapshot in
``results.daily`` (account equity + SPY close, written by the runner's post-close pass).
These are the same numbers as ``/dashboard`` and the daily LIVE email:

* return          = equity / start_equity − 1   (account return since the live start)
* SPY return      = SPY / start_SPY − 1          (same period)
* alpha           = return − SPY return
* annualised      = return × 252 / trading days  (simple; ``engine.reporting.annualize``)
* compounded      = (1+r)^(252/d) − 1             (indicative only — gains aren't reinvested
                                                   immediately)
* trading days    = NYSE sessions from the start date to the snapshot date, inclusive
                    (``trading_days_between``, same as the dashboard's since-start KPI)

Nothing is invented: if a strategy has no linked live run, or the run has no usable
snapshot yet, every figure is ``None`` and the page renders "—".
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.reporting.annualize import annualize, trading_days_between

log = logging.getLogger("leaderboard.perf")
ET = ZoneInfo("America/New_York")
_CACHE_TTL_S = 120.0
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def _num(v) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(v) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


EMPTY: dict[str, Any] = {
    "has_data": False, "start_date": None, "days_running": None, "trading_days": None,
    "as_of": None, "return_pct": None, "spy_return_pct": None, "alpha_pct": None,
    "annualised_pct": None, "annualised_compound_pct": None, "start_equity": None,
    "equity": None,
}


def metrics_from_run(run: Optional[dict], today: Optional[date] = None) -> dict:
    """Pure: leaderboard metrics from one live ``alpatrade.runs`` row (config + results)."""
    out = dict(EMPTY)
    if not run:
        return out
    cfg = run.get("config") or {}
    res = run.get("results") or {}
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    if isinstance(res, str):
        res = json.loads(res)
    start = _day(cfg.get("started")) or _day(run.get("started_at"))
    today = today or datetime.now(ET).date()
    if start:
        out["start_date"] = start.isoformat()
        out["days_running"] = max((today - start).days, 0)
    start_eq, start_spy = _num(cfg.get("start_equity")), _num(cfg.get("start_spy"))
    out["start_equity"] = start_eq
    daily = res.get("daily") or {}
    # Latest completed-session snapshot that carries both equity and SPY.
    for key in sorted(daily, reverse=True):
        snap = daily.get(key) or {}
        d = _day(key)
        equity, spy = _num(snap.get("equity")), _num(snap.get("spy"))
        if d is None or equity is None or spy is None or (start and d < start):
            continue
        if not (start and start_eq and start_spy):
            break
        ret = (equity / start_eq - 1) * 100
        spy_ret = (spy / start_spy - 1) * 100
        days = trading_days_between(start, d)
        ann = annualize(ret, days)
        out.update(
            has_data=ann["simple_pct"] is not None, as_of=d.isoformat(), trading_days=days,
            return_pct=ret, spy_return_pct=spy_ret, alpha_pct=ret - spy_ret,
            annualised_pct=ann["simple_pct"], annualised_compound_pct=ann["compound_pct"],
            equity=equity,
        )
        break
    return out


def _live_run(user_id: str, slug: str) -> Optional[dict]:
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    with DatabasePool().get_session() as session:
        row = session.execute(text("""
            SELECT run_id, config, results, started_at
            FROM alpatrade.runs
            WHERE mode = 'live' AND strategy_slug = :slug
              AND user_id = CAST(:uid AS UUID)
              AND COALESCE((config->>'test')::boolean, FALSE) = FALSE
            ORDER BY started_at DESC LIMIT 1
        """), {"slug": slug, "uid": str(user_id)}).mappings().first()
    return dict(row) if row else None


def backtest_metrics(strategy: dict) -> dict:
    """Figures for a ``kind='backtest'`` strategy from its stored ``backtest_metrics`` JSON
    (written by scripts/cwt_pipeline.py publish). Annualised = CAGR over the backtest period."""
    bm = strategy.get("backtest_metrics") or {}
    out = dict(EMPTY)
    out["is_backtest"] = True
    if not isinstance(bm, dict) or _num(bm.get("annualised_pct")) is None:
        return out
    out.update({
        "has_data": True, "start_date": bm.get("period_start"), "as_of": bm.get("period_end"),
        "trading_days": bm.get("trading_days"), "return_pct": _num(bm.get("total_return_pct")),
        "spy_return_pct": _num(bm.get("spy_return_pct")),
        # over a multi-year backtest the annualised gap (CAGR − SPY CAGR) is the comparable alpha
        "alpha_pct": _num(bm.get("alpha_annualised_pct")),
        "alpha_total_pct": _num(bm.get("alpha_pct")),
        "annualised_pct": _num(bm.get("annualised_pct")),
        "spy_annualised_pct": _num(bm.get("spy_annualised_pct")),
        "alpha_annualised_pct": _num(bm.get("alpha_annualised_pct")),
        "sharpe": _num(bm.get("sharpe")), "max_drawdown_pct": _num(bm.get("max_drawdown_pct")),
        "win_rate_pct": _num(bm.get("win_rate_pct")), "trades": bm.get("trades"),
        "test": bm.get("test") or {}, "universe": bm.get("universe"),
    })
    return out


def strategy_metrics(strategy: dict, today: Optional[date] = None) -> dict:
    """Live metrics for one strategy row (cached briefly); EMPTY when not linked/unavailable.
    Backtest strategies (``kind='backtest'``) return their stored backtest figures instead."""
    if strategy.get("kind") == "backtest":
        return backtest_metrics(strategy)
    slug, uid = strategy.get("live_strategy_slug"), strategy.get("user_id")
    if not slug or not uid:
        return dict(EMPTY)
    key = (str(uid), slug)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_S and today is None:
            return dict(hit[1])
    try:
        m = metrics_from_run(_live_run(str(uid), slug), today)
    except Exception as exc:  # noqa: BLE001 — DB down: show "—", never fake numbers
        log.warning("leaderboard live metrics failed: %s", type(exc).__name__)
        return dict(EMPTY)
    with _lock:
        _cache[key] = (now, m)
    return dict(m)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ── formatting ──────────────────────────────────────────────────────────────
def pct(v, digits: int = 2) -> str:
    return "—" if v is None else f"{v:+.{digits}f}%"


def fmt_day(v) -> str:
    d = _day(v)
    return d.strftime("%-d %b %Y") if d else "—"


def annualised_tip(m: dict) -> str:
    if m.get("is_backtest"):
        if m.get("annualised_pct") is None:
            return "No backtest figures stored for this strategy."
        return (f"Backtest CAGR {pct(m['annualised_pct'])} vs SPY {pct(m.get('spy_annualised_pct'))} "
                f"from {fmt_day(m['start_date'])} to {fmt_day(m['as_of'])} (daily bars, cash only, "
                f"slippage included). Hypothetical — never traded live.")
    if m.get("annualised_pct") is None:
        return "No live track record available for this strategy yet."
    return (f"Simple: return × 252 / trading days = {pct(m['return_pct'])} × 252 / "
            f"{m['trading_days']} = {pct(m['annualised_pct'])}. Compounded (1+r)^(252/d)−1 = "
            f"{pct(m['annualised_compound_pct'])} — indicative only, as gains aren't reinvested "
            f"immediately. Live account, session close {fmt_day(m['as_of'])}.")


def alpha_tip(m: dict) -> str:
    if m.get("is_backtest"):
        if m.get("alpha_pct") is None:
            return "No backtest figures stored for this strategy."
        return (f"Annualised alpha = backtest CAGR {pct(m['annualised_pct'])} − SPY CAGR "
                f"{pct(m.get('spy_annualised_pct'))} = {pct(m['alpha_pct'])} "
                f"({fmt_day(m['start_date'])}–{fmt_day(m['as_of'])}; total return "
                f"{pct(m['return_pct'])} vs SPY {pct(m['spy_return_pct'])}). Hypothetical — never "
                f"traded live.")
    if m.get("alpha_pct") is None:
        return "No live track record available for this strategy yet."
    return (f"Strategy {pct(m['return_pct'])} vs SPY {pct(m['spy_return_pct'])} from "
            f"{fmt_day(m['start_date'])} to the {fmt_day(m['as_of'])} close "
            f"({m['trading_days']} trading days).")


def rank_key(m: dict):
    """Sort: live strategies with figures first (by annualised return, desc), then live ones
    without figures, then backtests (by annualised return) — backtests never outrank live."""
    v = m.get("annualised_pct")
    bt = 1 if m.get("is_backtest") else 0
    return (bt, 0, -v) if v is not None else (bt, 1, 0.0)
