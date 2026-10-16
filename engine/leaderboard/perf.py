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
* annualised      = simple return × 252 / trading days, including short records
* compounded      = (1+r)^(252/d) − 1 (tooltip only, indicative)
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

import numpy as np
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
    """(time-weighted return %, net deposits); shared with the daily email / dashboard."""
    from engine.reporting.cash_flows import twr_pct as _twr
    return _twr(start, start_eq, points, flows)


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
        from engine.metrics import MIN_TRACK_DAYS
        out.update(
            has_data=True, as_of=d.isoformat(), trading_days=days,
            net_deposits=dep, cash_flows_ok=flows is not None,
            annualised_short=days < MIN_TRACK_DAYS,
            return_pct=ret, spy_return_pct=spy_ret, alpha_pct=ret - spy_ret,
            annualised_pct=ann["simple_pct"], annualised_simple_pct=ann["simple_pct"],
            annualised_compound_pct=ann["compound_pct"],
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


def _bt_days(bm: dict) -> Optional[int]:
    d = bm.get("trading_days")
    try:
        if d:
            return int(d)
    except (TypeError, ValueError):
        pass
    a, b = _day(bm.get("period_start")), _day(bm.get("period_end"))
    return trading_days_between(a, b) if a and b else None


def simple_from_cagr(cagr_pct, start, end) -> Optional[float]:
    """Convert a stored CAGR to simple annualised return for its test window."""
    c, a, b = _num(cagr_pct), _day(start), _day(end)
    if c is None or not a or not b:
        return None
    days = trading_days_between(a, b)
    if not days or c <= -100:
        return None
    total = ((1 + c / 100) ** (days / 252) - 1) * 100
    return annualize(total, days, min_days=1)["simple_pct"]


def backtest_metrics(strategy: dict) -> dict:
    """Figures for a ``kind='backtest'`` strategy from its stored ``backtest_metrics`` JSON
    (written by scripts/cwt_pipeline.py publish / scripts/seed_semi7_backtest.py).

    Headline annualised = simple total return × 252 / trading days; alpha uses the
    same period and rule for SPY. Stored annualised figures are ignored."""
    bm = strategy.get("backtest_metrics") or {}
    out = dict(EMPTY)
    out["is_backtest"] = True
    if not isinstance(bm, dict):
        return out
    tot, spy_tot, days = _num(bm.get("total_return_pct")), _num(bm.get("spy_return_pct")), _bt_days(bm)
    if tot is None or not days:
        return out
    a = annualize(tot, days, min_days=1)
    sa = annualize(spy_tot, days, min_days=1) if spy_tot is not None else {}
    ann, spy_ann = a["simple_pct"], sa.get("simple_pct")
    alpha = None if ann is None or spy_ann is None else ann - spy_ann
    out.update({
        "has_data": True, "start_date": bm.get("period_start"), "as_of": bm.get("period_end"),
        "trading_days": days, "return_pct": tot, "spy_return_pct": spy_tot,
        "alpha_pct": alpha,
        "alpha_total_pct": None if spy_tot is None else tot - spy_tot,
        "annualised_pct": ann, "annualised_simple_pct": a["simple_pct"],
        "annualised_short": days < 60,
        "annualised_out_of_bounds": False,
        "annualised_cagr_pct": a["compound_pct"],
        "spy_annualised_pct": spy_ann, "spy_annualised_cagr_pct": sa.get("compound_pct"),
        "alpha_annualised_pct": alpha,
        "alpha_cagr_pct": (None if a["compound_pct"] is None or sa.get("compound_pct") is None
                           else a["compound_pct"] - sa["compound_pct"]),
        "sharpe": _num(bm.get("sharpe")), "max_drawdown_pct": _num(bm.get("max_drawdown_pct")),
        "win_rate_pct": _num(bm.get("win_rate_pct")), "trades": bm.get("trades"),
        "test": bm.get("test") or {}, "universe": bm.get("universe"),
        "template": bm.get("template"), "episodes": bm.get("episodes") or [],
    })
    return out


def strategy_metrics(strategy: dict, today: Optional[date] = None) -> dict:
    """Live metrics for one strategy row (cached briefly); EMPTY when not linked/unavailable.
    Backtest strategies (``kind='backtest'``) return their stored backtest figures instead."""
    if strategy.get("kind") != "live" and strategy.get("user_id") and strategy.get("id") is not None:
        am = activation_metrics(strategy, today)
        if am is not None:
            return am
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


def _activation_row(user_id: str, sid: int):
    """The strategy's current activation (live preferred over paper), or None. Read-only."""
    from sqlalchemy import text
    from engine.auth import _get_pool
    with _get_pool().get_session() as s:
        try:
            return s.execute(text("""
                SELECT mode, status, cid_prefix, allocation_usd, confirmed_at
                FROM alpatrade.user_strategy_activations
                WHERE user_id = CAST(:u AS UUID) AND user_strategy_id = :i AND status <> 'deactivated'
                  AND cid_prefix IS NOT NULL AND confirmed_at IS NOT NULL
                ORDER BY (mode = 'live') DESC LIMIT 1"""), {"u": str(user_id), "i": int(sid)}).mappings().first()
        except Exception:  # noqa: BLE001 -- table not created yet
            return None


def _activation_pnl(user_id: str, prefix: str, mode: str, since) -> dict:
    """Realized + unrealized P&L of THIS activation's own runs (its prefix, since activation)."""
    from sqlalchemy import text
    from engine.auth import _get_pool
    with _get_pool().get_session() as s:
        r = s.execute(text("""
            WITH rr AS (SELECT run_id, config FROM alpatrade.runs WHERE user_id = CAST(:u AS UUID) AND mode = :m
                          AND config->>'cid_prefix' = :p AND started_at >= :since - INTERVAL '5 minutes')
            SELECT (SELECT COALESCE(SUM(pnl), 0) FROM alpatrade.trades t JOIN rr USING (run_id)
                     WHERE t.trade_type = :m AND t.exit_price IS NOT NULL),
                   (SELECT COUNT(*) FROM alpatrade.trades t JOIN rr USING (run_id)
                     WHERE t.trade_type = :m AND t.entry_price IS NOT NULL),
                   (SELECT COALESCE(SUM(unrealized_pnl), 0) FROM alpatrade.positions p JOIN rr USING (run_id)
                     WHERE p.status = 'open'
                       -- excluded junk securities (sql/53, engine/reporting/exclusions.py)
                       AND NOT EXISTS (SELECT 1 FROM alpatrade.excluded_securities x
                             WHERE upper(x.symbol) = upper(p.symbol)
                               AND (x.scope = 'global' OR upper(x.account_ref) IN (
                                    upper(COALESCE(rr.config->>'account_number', '')),
                                    upper(COALESCE(rr.config->>'account_id', ''))))))"""),
                      {"u": str(user_id), "m": mode, "p": prefix, "since": since}).first()
    return {"realized": float(r[0] or 0), "fills": int(r[1] or 0), "unrealized": float(r[2] or 0)}


def activation_metrics(strategy: dict, today: Optional[date] = None, *, row_fn=None, pnl_fn=None,
                       spy_fn=None) -> Optional[dict]:
    """Since-activation figures for an activated user strategy, or None when not activated.

    Measured only from the activation timestamp against its allocation, using this activation's own
    fills/positions (its client_order_id prefix); the account's other holdings and history are
    excluded. 0.00% until the strategy's first fill or a price move of its own positions."""
    uid, sid = str(strategy.get("user_id")), int(strategy["id"])
    key = ("act", uid, sid)
    now = time.monotonic()
    if row_fn is None and today is None:
        with _lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < _CACHE_TTL_S:
                return None if hit[1] is None else dict(hit[1])
    try:
        row = (row_fn or _activation_row)(uid, sid)
        if not row:
            m = None
        else:
            since = row["confirmed_at"]
            alloc = float(row["allocation_usd"] or 0) or 1.0
            pnl = (pnl_fn or _activation_pnl)(uid, row["cid_prefix"], row["mode"], since)
            total = pnl["realized"] + pnl["unrealized"]
            ret = round(total / alloc * 100.0, 4)
            start = since.date() if hasattr(since, "date") else since
            end = today or date.today()
            td = max(int(np.busday_count(start, end)) if end > start else 0, 0)
            ann = annualize(ret, max(td, 1), min_days=1)["simple_pct"]
            spy = alpha = None
            if pnl["fills"]:
                closes = (spy_fn or _spy_since)(start, end)
                if closes:
                    spy = closes
                    alpha = round(ret - spy, 4)
            m = {**EMPTY, "has_data": True, "is_activation": True, "activation_mode": row["mode"],
                 "activation_status": row["status"], "start_date": start, "as_of": end,
                 "days_running": (end - start).days, "trading_days": td, "return_pct": ret,
                 "annualised_pct": ann, "annualised_short": td < 60, "spy_return_pct": spy,
                 "alpha_pct": alpha, "start_equity": alloc, "equity": alloc + total,
                 "pnl_usd": round(total, 2), "fills": pnl["fills"]}
    except Exception as exc:  # noqa: BLE001
        log.warning("activation metrics failed: %s", type(exc).__name__)
        return None
    if row_fn is None and today is None:
        with _lock:
            _cache[key] = (now, m)
    return None if m is None else dict(m)


def _spy_since(start: date, end: date) -> Optional[float]:
    from engine.reporting.perf_chart import spy_closes
    c = spy_closes(start, end)
    if not c:
        return None
    ks = sorted(c)
    base = [k for k in ks if k <= start.isoformat()] or ks
    return round((c[ks[-1]] / c[base[-1]] - 1) * 100.0, 4)


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
    if m.get("is_activation"):
        return (f"Since you activated it ({m.get('activation_mode')}) on {fmt_day(m['start_date'])}: "
                f"P&L ${m.get('pnl_usd', 0):,.2f} on a ${m['start_equity']:,.0f} allocation = {pct(m['return_pct'])}; "
                f"{_ann_phrase(m)}. Only this "
                "strategy's own fills and positions count; the account's other holdings are excluded.")
    if m.get("is_backtest"):
        if m.get("annualised_pct") is None:
            return "No backtest figures stored for this strategy."
        return (f"Simple annualised: total return {pct(m['return_pct'])} × 252 / {m['trading_days']} trading days "
                f"= {pct(m['annualised_pct'])}/yr (SPY total {pct(m.get('spy_return_pct'))} = "
                f"{pct(m.get('spy_annualised_pct'))}/yr), {fmt_day(m['start_date'])} – {fmt_day(m['as_of'])}. "
                f"Daily-bar backtest, hypothetical — never traded live.")
    if m.get("annualised_pct") is None:
        return "No live track record available for this strategy yet."
    short = (f" Short period: only {m['trading_days']} trading days, so the annualised figure "
             "is very sensitive and says little about the future." if m.get("annualised_short") else "")
    return (f"Simple annualised return on time-weighted return = {pct(m['return_pct'])} × 252 "
            f"/ {m['trading_days']} trading days (deposits/withdrawals excluded) = "
            f"{pct(m['annualised_pct'])}."
            f"{short} Live account, session close {fmt_day(m['as_of'])}.")


def _ann_phrase(m: dict) -> str:
    if m.get("annualised_pct") is None:
        return "no measured return yet"
    return f"simple annualised ×252/{max(m['trading_days'], 1)} trading days = {pct(m['annualised_pct'])}"


def ann_display(m: dict) -> str:
    """Leaderboard/strategy headline: simple annualised return."""
    if m.get("annualised_pct") is not None:
        return pct(m["annualised_pct"])
    return "—"


def alpha_tip(m: dict) -> str:
    if m.get("is_activation"):
        if m.get("alpha_pct") is None:
            return "No fills since activation yet, so no alpha vs SPY."
        return (f"Since activation: strategy {pct(m['return_pct'])} vs SPY {pct(m['spy_return_pct'])}.")
    if m.get("is_backtest"):
        if m.get("alpha_pct") is None:
            return "No backtest figures stored for this strategy."
        return (f"Annualised alpha (simple) = {pct(m['annualised_pct'])} − SPY "
                f"{pct(m.get('spy_annualised_pct'))} = {pct(m['alpha_pct'])} over {m['trading_days']} "
                f"trading days "
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
