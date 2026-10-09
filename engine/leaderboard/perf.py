"""Leaderboard figures from REAL live data inside AlpaTrade.

For a strategy linked to its owner's live runner (``live_strategy_slug``), the figures come
from that run in ``alpatrade.runs`` (``mode='live'``, same ``user_id``): the start date,
start equity and start SPY in ``config`` and the latest daily **session-close** snapshot in
``results.daily`` (account equity + SPY close, written by the runner's post-close pass).
These are the same numbers as ``/dashboard`` and the daily LIVE email:

* return          = time-weighted return since the live start: daily session-close equity
                    chained, each day net of that day's external cash flows (deposits /
                    withdrawals, Alpaca CSD/CSW/JNLC via the owner's read-only live link), so a
                    deposit is never counted as performance (engine/reporting/cash_flows.py).
                    Without flow data it falls back to equity / start_equity − 1.
* SPY return      = SPY / start_SPY − 1          (same period)
* alpha           = return − SPY return
* annualised      = (1+r)^(252/d) − 1 on the time-weighted return r (compounded; always shown,
                    with a "short period" hint in the tooltip below 63 trading days)
* simple          = r × 252 / d (shown in the tooltip)
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


def twr_pct(start: date, start_eq: float, points: list, flows: Optional[list]) -> tuple[float, float]:
    """(time-weighted return %, net deposits) from ascending [(day, equity)] session closes.
    Each segment's return = (E_k − flows in (prev_day, k]) / E_prev − 1 (flow at end of day)."""
    from engine.reporting.cash_flows import net_flows
    growth, prev_eq, prev_day, dep = 1.0, float(start_eq), start, 0.0
    for d, e in points:
        f = net_flows(flows or [], prev_day, d)
        if prev_eq > 0:
            growth *= (float(e) - f) / prev_eq
        prev_eq, prev_day, dep = float(e), d, dep + f
    return (growth - 1) * 100, round(dep, 2)


def metrics_from_run(run: Optional[dict], today: Optional[date] = None,
                     flows: Optional[list] = None) -> dict:
    """Pure: leaderboard metrics from one live ``alpatrade.runs`` row (config + results).
    ``flows`` = cash_flows.flow_rows() for the run's account (None = unknown -> simple return)."""
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
        pts = sorted((_day(k), _num((daily.get(k) or {}).get("equity"))) for k in daily
                     if _day(k) and start <= _day(k) <= d and _num((daily.get(k) or {}).get("equity")))
        if flows is not None:
            ret, dep = twr_pct(start, start_eq, pts, flows)
        else:
            ret, dep = (equity / start_eq - 1) * 100, None
        spy_ret = (spy / start_spy - 1) * 100
        days = trading_days_between(start, d)
        ann = annualize(ret, days, min_days=1)
        out.update(
            has_data=True, as_of=d.isoformat(), trading_days=days,
            net_deposits=dep, cash_flows_ok=flows is not None,
            annualised_short=days < 63,
            return_pct=ret, spy_return_pct=spy_ret, alpha_pct=ret - spy_ret,
            annualised_pct=ann["compound_pct"], annualised_simple_pct=ann["simple_pct"],
            annualised_compound_pct=None,
            equity=equity,
        )
        break
    return out


def _owner_flows(user_id: str, run: Optional[dict]) -> Optional[list]:
    """Cash-flow rows of the run's account via the OWNER's read-only live link (GET only).
    None when unavailable (figures then fall back to the simple equity ratio)."""
    if not run:
        return None
    cfg = run.get("config") or {}
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    acct = cfg.get("account_number")
    start = _day(cfg.get("started")) or _day(run.get("started_at"))
    if not acct or not start:
        return None
    try:
        from datetime import timedelta
        from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient
        from engine.live_accounts import get_live_account_credentials
        from engine.reporting.cash_flows import fetch_flows
        creds = get_live_account_credentials(user_id, str(acct))
        if not creds:
            return None
        client = LiveReadOnlyClient(creds["api_key"], creds["secret_key"],
                                    expected_account_number=creds["account_number"])
        return fetch_flows(client, start - timedelta(days=1))
    except Exception as exc:  # noqa: BLE001
        log.warning("leaderboard cash flows unavailable: %s", type(exc).__name__)
        return None


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
        "template": bm.get("template"), "episodes": bm.get("episodes") or [],
    })
    return out


def strategy_metrics(strategy: dict, today: Optional[date] = None) -> dict:
    """Live metrics for one strategy row (cached briefly); EMPTY when not linked/unavailable.
    Backtest strategies (``kind='backtest'``) return their stored backtest figures instead."""
    if strategy.get("kind") == "backtest":
        bm = strategy.get("backtest_metrics") if isinstance(strategy.get("backtest_metrics"), dict) else {}
        live_slug = bm.get("live_slug")
        if live_slug and strategy.get("user_id"):
            # Backtest placeholder (e.g. Semi 7) that switches to live figures as soon as its
            # live run has a session-close snapshot. Mutates the row so the page labels it Live.
            m = strategy_metrics({**strategy, "kind": "live", "live_strategy_slug": live_slug}, today)
            if m.get("has_data"):
                strategy["kind"] = "live"
                strategy["live_strategy_slug"] = live_slug
                return m
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
        run = _live_run(str(uid), slug)
        m = metrics_from_run(run, today, _owner_flows(str(uid), run))
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
    short = (f" Short period: only {m['trading_days']} trading days, so the annualised figure "
             "is very sensitive and says little about the future." if m.get("annualised_short") else "")
    return (f"Compounded (1+r)^(252/d)−1 on the time-weighted return r = {pct(m['return_pct'])} "
            f"(deposits/withdrawals excluded) over {m['trading_days']} trading days = "
            f"{pct(m['annualised_pct'])}; simple r × 252 / d = {pct(m.get('annualised_simple_pct'))}."
            f"{short} Live account, session close {fmt_day(m['as_of'])}.")


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
    if v is None and not bt and m.get("has_data") and m.get("return_pct") is not None:
        v = m["return_pct"]  # short live record: rank by its (non-annualised) return
    return (bt, 0, -v) if v is not None else (bt, 1, 0.0)
