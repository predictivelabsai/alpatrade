#!/usr/bin/env python3
"""Daily LIVE-account report — emailed after the US close to the account owner.

The live counterpart of ``scripts/daily_pnl_report.py`` (which stays paper-only).
For every user with an active, read-only live broker link
(``alpatrade.user_live_broker_accounts``) it reads the real-money Alpaca account
through the GET-only :class:`engine.brokers.alpaca_live_readonly.LiveReadOnlyClient`
(account, positions, open orders, FILL activities, closed orders, portfolio history,
calendar — nothing can be placed, cancelled or closed) plus the live BTD runner's
recorded run/trades (``alpatrade.runs`` mode='live', ``alpatrade.trades``
trade_type='live'), renders an HTML digest and emails it via Postmark.

Recipient: only the linked user's own email (``alpatrade.users.email``); there is
no distribution list and no ``--to`` override.

Scheduled by engine.autonomy.schedule (session close + LIVE_REPORT_CLOSE_DELAY_MINUTES,
trading days only — weekends/holidays are skipped via Alpaca's calendar).

Usage:
  python scripts/daily_live_report.py --email kaljuvee@gmail.com              # print, no send
  python scripts/daily_live_report.py --email kaljuvee@gmail.com --date 2026-09-25 \
      --html-out /tmp/live.html --send
"""
from __future__ import annotations

import argparse
import html as _html
import json
import logging
import os
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

log = logging.getLogger("daily_live_report")

ET = ZoneInfo("America/New_York")
REPORT_KIND = "daily_live"
GREEN, RED, MUTED = "#1F5D43", "#b0653f", "#7A867E"
NEAR_SIGNAL_FRACTION = 2 / 3  # a dip >= 2/3 of the threshold is shown as "near"


# --------------------------------------------------------------------------- utils
def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _fn(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _e(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def _ts(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _money(v, signed: bool = False) -> str:
    if v is None:
        return "—"
    v = float(v)
    if signed:
        return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"
    return f"${v:,.2f}"


def _pct(v) -> str:
    return "—" if v is None else f"{float(v):+.2f}%"


def _col(v) -> str:
    return GREEN if (v or 0) >= 0 else RED


def _qty(v) -> str:
    q = _f(v)
    return f"{q:,.6f}".rstrip("0").rstrip(".") if q % 1 else f"{q:,.0f}"


# ------------------------------------------------------------------ targets / DB
def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def report_targets(email: str | None = None) -> list[dict]:
    """Active read-only live links joined to their owner's email (no key material).

    Each target is emailed only to its own ``users.email``."""
    try:
        from sqlalchemy import text
        where = ["l.is_active", "l.read_only", "u.email IS NOT NULL"]
        params: dict = {}
        if email:
            where.append("LOWER(u.email) = LOWER(:email)")
            params["email"] = email
        with _pool().get_session() as session:
            rows = session.execute(text(f"""
                SELECT u.user_id, u.email, l.account_number, l.label
                FROM alpatrade.user_live_broker_accounts l
                JOIN alpatrade.users u ON u.user_id = l.user_id
                WHERE {' AND '.join(where)}
                ORDER BY u.user_id, l.created_at
            """), params).fetchall()
        return [{"user_id": str(r[0]), "email": r[1], "account_number": str(r[2]),
                 "label": r[3]} for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("live report targets unavailable: %s", type(exc).__name__)
        return []


def client_for(target: dict):
    """GET-only live client for the target's own link (verified account number)."""
    from engine.live_accounts import get_live_account_credentials
    from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient
    creds = get_live_account_credentials(target["user_id"], target.get("account_number"))
    if not creds:
        return None
    return LiveReadOnlyClient(creds["api_key"], creds["secret_key"],
                              expected_account_number=creds["account_number"])


_DDL = """
CREATE TABLE IF NOT EXISTS alpatrade.live_report_deliveries (
    delivery_id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_number VARCHAR(32) NOT NULL,
    report_date DATE NOT NULL,
    report_kind VARCHAR(32) NOT NULL DEFAULT 'daily_live',
    status VARCHAR(16) NOT NULL DEFAULT 'sending',
    message_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    UNIQUE (user_id, account_number, report_date, report_kind)
)"""
_ddl_done = False


def _ensure_table(session) -> None:
    global _ddl_done
    if not _ddl_done:
        from sqlalchemy import text
        session.execute(text(_DDL))
        _ddl_done = True


def claim_live_delivery(user_id: str, account_number: str, day: str,
                        force: bool = False) -> bool:
    """Atomically reserve one live report per user/account/trading day."""
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            _ensure_table(session)
            row = session.execute(text(f"""
                INSERT INTO alpatrade.live_report_deliveries
                    (user_id, account_number, report_date, report_kind)
                VALUES (:uid, :acct, CAST(:day AS DATE), '{REPORT_KIND}')
                ON CONFLICT (user_id, account_number, report_date, report_kind) DO UPDATE
                    SET status = 'sending', created_at = NOW()
                    WHERE :force
                       OR alpatrade.live_report_deliveries.status = 'failed'
                       OR (alpatrade.live_report_deliveries.status = 'sending'
                           AND alpatrade.live_report_deliveries.created_at < NOW() - INTERVAL '2 hours')
                RETURNING delivery_id
            """), {"uid": user_id, "acct": account_number, "day": day,
                    "force": bool(force)}).fetchone()
            return bool(row)
    except Exception as exc:  # noqa: BLE001
        log.warning("live report claim failed: %s", type(exc).__name__)
        return False


def finish_live_delivery(user_id: str, account_number: str, day: str, sent: bool,
                         message_id: str | None = None) -> None:
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            session.execute(text(f"""
                UPDATE alpatrade.live_report_deliveries
                SET status = :status, message_id = :mid,
                    sent_at = CASE WHEN :sent THEN NOW() ELSE NULL END
                WHERE user_id = :uid AND account_number = :acct
                  AND report_date = CAST(:day AS DATE) AND report_kind = '{REPORT_KIND}'
            """), {"uid": user_id, "acct": account_number, "day": day, "sent": sent,
                    "status": "sent" if sent else "failed", "mid": message_id})
    except Exception:  # noqa: BLE001
        pass


def live_run(user_id: str, account_number: str | None = None) -> dict:
    """The user's most recent live runner run (prefer one tagged with this account)."""
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            rows = session.execute(text("""
                SELECT run_id, strategy, strategy_slug, status, config, results,
                       started_at, heartbeat_at
                FROM alpatrade.runs
                WHERE user_id = CAST(:uid AS UUID) AND mode = 'live'
                  AND COALESCE((config->>'test')::boolean, FALSE) = FALSE
                ORDER BY started_at DESC LIMIT 10
            """), {"uid": user_id}).mappings().all()
        rows = [dict(r) for r in rows]
        for r in rows:
            for k in ("config", "results"):
                if isinstance(r.get(k), str):
                    r[k] = json.loads(r[k])
        tagged = [r for r in rows if str((r.get("config") or {}).get("account_number") or "")
                  == str(account_number or "")]
        return (tagged or rows or [{}])[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("live run lookup failed: %s", type(exc).__name__)
        return {}


def runner_trades(run_id: str | None) -> list[dict]:
    """All live trade rows the runner recorded for one run (oldest first)."""
    if not run_id:
        return []
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            rows = session.execute(text("""
                SELECT symbol, direction, shares, entry_price, exit_price, pnl, pnl_pct,
                       reason, entry_time, exit_time, order_id, dip_pct, target_price,
                       stop_price, created_at
                FROM alpatrade.trades
                WHERE run_id = :rid AND trade_type = 'live'
                ORDER BY COALESCE(entry_time, created_at)
            """), {"rid": run_id}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def _db_ok() -> bool:
    try:
        from sqlalchemy import text
        with _pool().get_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ trading days
def session_for(client, day: date) -> dict | None:
    """Alpaca calendar entry for ``day`` ({date, open, close} as ET datetimes) or None."""
    cal = client.get_calendar(day.isoformat(), day.isoformat())
    for c in cal or []:
        if str(c.get("date")) == day.isoformat():
            o = datetime.combine(day, dtime.fromisoformat(str(c["open"])), ET)
            cl = datetime.combine(day, dtime.fromisoformat(str(c["close"])), ET)
            return {"date": day, "open": o, "close": cl}
    return None


def previous_session(client, day: date) -> dict | None:
    cal = client.get_calendar((day - timedelta(days=10)).isoformat(),
                              (day - timedelta(days=1)).isoformat())
    days = sorted(str(c.get("date")) for c in cal or [] if str(c.get("date")) < day.isoformat())
    return session_for(client, date.fromisoformat(days[-1])) if days else None


def latest_completed_session(client, now: datetime | None = None,
                             delay_minutes: int = 0) -> dict | None:
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    cal = client.get_calendar((now.date() - timedelta(days=10)).isoformat(),
                              now.date().isoformat())
    for c in sorted(cal or [], key=lambda c: str(c.get("date")), reverse=True):
        s = session_for(client, date.fromisoformat(str(c["date"])))
        if s and now >= s["close"] + timedelta(minutes=delay_minutes):
            return s
    return None


# ------------------------------------------------------------------ fills / P&L
def aggregate_fills(fills: list[dict]) -> list[dict]:
    """Collapse partial FILL activities into one row per order (VWAP price)."""
    orders: dict[str, dict] = {}
    for f in fills:
        oid = str(f.get("order_id") or f.get("id"))
        q, px = _f(f.get("qty")), _f(f.get("price"))
        o = orders.setdefault(oid, {"order_id": oid, "symbol": f.get("symbol"),
                                    "side": str(f.get("side") or "").lower(), "qty": 0.0,
                                    "value": 0.0, "time": _ts(f.get("transaction_time"))})
        o["qty"] += q
        o["value"] += q * px
        t = _ts(f.get("transaction_time"))
        if t and (o["time"] is None or t > o["time"]):
            o["time"] = t
    out = []
    for o in orders.values():
        o["price"] = o["value"] / o["qty"] if o["qty"] else 0.0
        out.append(o)
    return sorted(out, key=lambda o: o["time"] or datetime.min.replace(tzinfo=timezone.utc))


def fifo_realized(history: list[dict], targets: list[dict]) -> dict[str, float | None]:
    """FIFO realised P&L for sell orders in ``targets`` using the full fill history.

    Returns {order_id: pnl or None}; None when the history doesn't hold enough prior
    buys (e.g. shares transferred in) to know the cost basis."""
    want = {o["order_id"] for o in targets if o["side"] == "sell"}
    lots: dict[str, list[list[float]]] = {}
    pnl: dict[str, float | None] = {}
    for f in sorted(history, key=lambda f: str(f.get("transaction_time") or "")):
        sym, side = f.get("symbol"), str(f.get("side") or "").lower()
        q, px = _f(f.get("qty")), _f(f.get("price"))
        oid = str(f.get("order_id") or f.get("id"))
        book = lots.setdefault(sym, [])
        if side == "buy":
            book.append([q, px])
            continue
        realised, remaining = 0.0, q
        while remaining > 1e-9 and book:
            lot = book[0]
            take = min(lot[0], remaining)
            realised += take * (px - lot[1])
            lot[0] -= take
            remaining -= take
            if lot[0] <= 1e-9:
                book.pop(0)
        if oid in want:
            if remaining > 1e-6 or pnl.get(oid, 0.0) is None:
                pnl[oid] = None
            else:
                pnl[oid] = pnl.get(oid, 0.0) + realised
    return pnl


def _historical_equity(client, day: date):
    """(equity at end of ``day``, previous trading day's equity) from portfolio history."""
    try:
        hist = client.get_portfolio_history((day - timedelta(days=10)).isoformat(),
                                            day.isoformat(), "1D")
        ts, eq = hist.get("timestamp") or [], hist.get("equity") or []
        upto = [float(e) for t, e in zip(ts, eq)
                if e is not None and datetime.fromtimestamp(int(t), ET).date() <= day]
        if not upto:
            return None
        return upto[-1], (upto[-2] if len(upto) >= 2 else upto[-1])
    except Exception:  # noqa: BLE001
        return None


def spy_close(day: date, run: dict) -> float | None:
    """SPY close for ``day`` (market-data feed), else the runner's recorded SPY."""
    try:
        import pandas as pd
        from engine.feeds.market_data import get_historical_data
        df = get_historical_data("SPY", datetime.combine(day - timedelta(days=7), dtime.min),
                                 datetime.combine(day + timedelta(days=1), dtime.min),
                                 timeframe="day")
        if df is not None and not df.empty and "Close" in df:
            closes = df["Close"].dropna()
            closes = closes[pd.to_datetime(closes.index).date <= day]
            if len(closes):
                return float(closes.iloc[-1])
    except Exception:  # noqa: BLE001
        pass
    res = run.get("results") or {}
    snap = (res.get("daily") or {}).get(day.isoformat()) or {}
    return _fn(snap.get("spy")) or _fn((res.get("latest") or {}).get("spy"))


def dip_signals(symbols: list[str], day: date, threshold: float) -> list[dict]:
    """Dip vs 20-bar high at the ``day`` close for each runner symbol (best-effort)."""
    out = []
    try:
        import pandas as pd
        from engine.feeds.market_data import get_historical_data
    except Exception:  # noqa: BLE001
        return out
    for sym in symbols:
        try:
            df = get_historical_data(sym, datetime.combine(day - timedelta(days=45), dtime.min),
                                     datetime.combine(day + timedelta(days=1), dtime.min),
                                     timeframe="day")
            if df is None or df.empty or "Close" not in df or "High" not in df:
                continue
            df = df[pd.to_datetime(df.index).date <= day].tail(20)
            if df.empty:
                continue
            high20, close = float(df["High"].max()), float(df["Close"].iloc[-1])
            dip = (high20 - close) / high20 * 100 if high20 else 0.0
            status = ("signal" if dip >= threshold else
                      "near" if dip >= threshold * NEAR_SIGNAL_FRACTION else "no")
            out.append({"symbol": sym, "close": close, "high20": high20, "dip": dip,
                        "status": status})
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------- gather
def gather(client, target: dict, day: date | None = None, now: datetime | None = None,
           with_signals: bool = True) -> dict:
    """Collect everything the live digest shows for one trading ``day`` (ET)."""
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    warnings: list[str] = []
    sess = session_for(client, day) if day else latest_completed_session(client, now)
    if day and not sess:
        return {"no_trading_day": True, "day": day.isoformat(), **target}
    if not sess:
        raise RuntimeError("no completed trading session found in the last 10 days")
    day = sess["date"]
    prev = previous_session(client, day)
    # Window: after the previous session's extended hours (20:00 ET) through this
    # session's 20:00 ET — so overnight (24/5) fills count toward the next trade date.
    win_start = (datetime.combine(prev["date"], dtime(20, 0), ET) if prev
                 else datetime.combine(day, dtime(0, 0), ET))
    win_end = min(datetime.combine(day, dtime(20, 0), ET), now)

    acct = client.get_account()
    positions = client.get_positions()
    open_orders = client.get_open_orders()
    equity, last_equity = _f(acct.get("equity")), _f(acct.get("last_equity"))
    backdated = now.date() != day
    if backdated:
        hist = _historical_equity(client, day)
        if hist:
            equity_day, last_equity = hist
        else:
            equity_day = equity
            warnings.append("Portfolio history unavailable: day P&L uses the live account.")
    else:
        equity_day = equity
    last_equity = last_equity or equity_day
    day_pnl = equity_day - last_equity
    day_pct = (equity_day / last_equity - 1) * 100 if last_equity else 0.0

    # Fills in the window, aggregated per order, labelled runner vs other.
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    window_fills = client.get_fills(after=iso(win_start), until=iso(win_end))
    orders = aggregate_fills(window_fills)
    history = client.get_fills(after="2015-01-01T00:00:00Z", until=iso(win_end))
    realized = fifo_realized(history, orders)
    try:
        closed = client.get_order_history(iso(win_start - timedelta(days=7)), iso(win_end))
    except Exception:  # noqa: BLE001
        closed = []
    cids = {str(o.get("id")): str(o.get("client_order_id") or "") for o in closed}

    run = live_run(target["user_id"], target.get("account_number"))
    rtrades = runner_trades(run.get("run_id"))
    by_cid = {str(t.get("order_id") or ""): t for t in rtrades}
    for o in orders:
        cid = cids.get(o["order_id"], "")
        o["client_order_id"] = cid
        o["source"] = "runner" if cid.startswith(("btd-", "btdx-")) else "other"
        o["realized"] = realized.get(o["order_id"]) if o["side"] == "sell" else None
        o["realized_src"] = "FIFO" if o["realized"] is not None else None
        if o["side"] == "sell" and cid.startswith("btdx-"):
            entry = next((t for t in rtrades if t.get("symbol") == o["symbol"]
                          and t.get("pnl") is not None and _ts(t.get("exit_time"))
                          and win_start <= _ts(t["exit_time"]) <= win_end + timedelta(hours=12)),
                         None)
            if entry:
                o["realized"], o["realized_src"] = _f(entry["pnl"]), "runner"

    # Runner status: open lots, today's actions, heartbeat, params.
    cfg = run.get("config") or {}
    min_hold, max_hold = int(_f(cfg.get("min_hold_days"), 3)), int(_f(cfg.get("hold_days"), 3))
    pos_by_sym = {p.get("symbol"): p for p in positions}
    runner_open, actions = [], []
    for t in rtrades:
        et = _ts(t.get("entry_time"))
        xt = _ts(t.get("exit_time"))
        if t.get("exit_price") is None and _f(t.get("shares")) > 0 and et:
            ed = et.astimezone(ET).date()
            p = pos_by_sym.get(t.get("symbol")) or {}
            runner_open.append({
                "symbol": t.get("symbol"), "entry_date": ed, "qty": _f(t.get("shares")),
                "entry_price": _fn(t.get("entry_price")),
                "tp_sl_from": ed + timedelta(days=min_hold),
                "max_hold_exit": ed + timedelta(days=max_hold),
                "target": _fn(t.get("target_price")), "stop": _fn(t.get("stop_price")),
                "current": _fn(p.get("current_price")), "upl": _fn(p.get("unrealized_pl")),
                "uplpc": (_f(p.get("unrealized_plpc")) * 100) if p else None})
        touched = [x for x in (et, xt, _ts(t.get("created_at"))) if x]
        if any(win_start <= x <= win_end for x in touched):
            actions.append(t)
    hb = _ts(run.get("heartbeat_at"))
    if run.get("run_id"):
        entry_win = sess["close"] - timedelta(minutes=15)
        if hb is None or hb < entry_win - timedelta(minutes=5):
            warnings.append(
                "Runner did not check in during this session's entry window "
                f"(last heartbeat {hb.astimezone(ET).strftime('%a %b %d %H:%M ET') if hb else 'never'})"
                " — passes may have been missed (host asleep/offline?).")

    # Performance since the live run started vs SPY.
    perf = {}
    start_eq, start_spy = _fn(cfg.get("start_equity")), _fn(cfg.get("start_spy"))
    latest = (run.get("results") or {}).get("latest") or {}
    if run.get("run_id"):
        spy = spy_close(day, run)
        acct_ret = (equity_day / start_eq - 1) * 100 if start_eq else None
        spy_ret = (spy / start_spy - 1) * 100 if spy and start_spy else None
        perf = {"started": cfg.get("started") or run.get("started_at"),
                "start_equity": start_eq, "equity": equity_day, "account_return_pct": acct_ret,
                "account_pnl": (equity_day - start_eq) if start_eq else None,
                "spy_start": start_spy, "spy": spy, "spy_return_pct": spy_ret,
                "excess_pct": (acct_ret - spy_ret) if acct_ret is not None and spy_ret is not None else None,
                "strategy_realized": _fn(latest.get("realized_pnl")),
                "strategy_unrealized": sum(_f(r["upl"]) for r in runner_open) if runner_open else 0.0,
                "closed_trades": latest.get("closed_trades")}
        perf["strategy_pnl"] = _f(perf["strategy_realized"]) + _f(perf["strategy_unrealized"])

    signals = []
    if with_signals and run.get("run_id"):
        signals = dip_signals([s for s in (cfg.get("symbols") or [])],
                              day, _f(cfg.get("dip_threshold"), 3.0))

    return {
        **target, "day": day.isoformat(), "session_close": sess["close"],
        "generated_at": now, "backdated": backdated, "window": (win_start, win_end),
        "equity": equity_day, "equity_now": equity, "last_equity": last_equity,
        "day_pnl": day_pnl, "day_pct": day_pct, "cash": _f(acct.get("cash")),
        "buying_power": _f(acct.get("buying_power")),
        "long_market_value": _f(acct.get("long_market_value")),
        "positions": positions, "open_orders": open_orders, "fills": orders,
        "run": run, "perf": perf, "runner_open": runner_open, "runner_actions": actions,
        "runner_heartbeat": hb, "signals": signals, "warnings": warnings,
        "db_ok": _db_ok(), "account_ok": True,
    }


# ---------------------------------------------------------------------- render
_TH = "style='background:#EFEDE4;text-align:left'"
_TABLE = "border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'"
_R = "style='text-align:right'"


def _fills_table(fills: list[dict]) -> str:
    rows = ""
    for o in fills:
        rp = o.get("realized")
        rp_cell = (f"<span style='color:{_col(rp)}'>{_money(rp, True)}</span>"
                   f" <small style='color:{MUTED}'>{_e(o.get('realized_src'))}</small>"
                   if rp is not None else ("n/a" if o["side"] == "sell" else "—"))
        t = o.get("time")
        rows += (f"<tr><td>{_e(t.astimezone(ET).strftime('%a %H:%M ET') if t else '—')}</td>"
                 f"<td><b>{_e(o['symbol'])}</b></td><td>{_e(o['side'])}</td>"
                 f"<td {_R}>{_qty(o['qty'])}</td><td {_R}>{_money(o['price'])}</td>"
                 f"<td {_R}>{_money(o['qty'] * o['price'])}</td><td {_R}>{rp_cell}</td>"
                 f"<td>{'runner' if o.get('source') == 'runner' else 'manual / other'}</td></tr>")
    if not rows:
        rows = f"<tr><td colspan='8' style='color:{MUTED}'>No fills in this session.</td></tr>"
    return (f"<table {_TABLE}><thead><tr {_TH}><th>Time</th><th>Symbol</th><th>Side</th>"
            "<th>Qty</th><th>Avg price</th><th>Value</th><th>Realised P&amp;L</th>"
            f"<th>Source</th></tr></thead><tbody>{rows}</tbody></table>")


def _positions_table(positions: list[dict]) -> str:
    rows = ""
    for p in sorted(positions, key=lambda x: _f(x.get("market_value")), reverse=True):
        pl = _f(p.get("unrealized_pl"))
        rows += (f"<tr><td><b>{_e(p.get('symbol'))}</b></td><td {_R}>{_qty(p.get('qty'))}</td>"
                 f"<td {_R}>{_money(_f(p.get('avg_entry_price')))}</td>"
                 f"<td {_R}>{_money(_f(p.get('current_price')))}</td>"
                 f"<td {_R}>{_money(_f(p.get('market_value')))}</td>"
                 f"<td {_R} style='color:{_col(pl)}'>{_money(pl, True)} "
                 f"({_f(p.get('unrealized_plpc')) * 100:+.2f}%)</td></tr>")
    if not rows:
        rows = f"<tr><td colspan='6' style='color:{MUTED}'>No open positions.</td></tr>"
    return (f"<table {_TABLE}><thead><tr {_TH}><th>Symbol</th><th>Qty</th><th>Avg entry</th>"
            "<th>Price</th><th>Value</th><th>Unrealised P&amp;L</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _orders_table(orders: list[dict]) -> str:
    rows = ""
    for o in orders:
        size = (f"{_qty(o.get('qty'))} sh" if o.get("qty") else
                f"{_money(_f(o.get('notional')))} notional" if o.get("notional") else "—")
        lim = f" @ {_money(_f(o.get('limit_price')))}" if o.get("limit_price") else ""
        sub = _ts(o.get("submitted_at"))
        rows += (f"<tr><td><b>{_e(o.get('symbol'))}</b></td><td>{_e(o.get('side'))}</td>"
                 f"<td>{_e(o.get('type'))}{_e(lim)}</td><td>{_e(size)}</td>"
                 f"<td>{_e(o.get('time_in_force'))}</td><td>{_e(o.get('status'))}</td>"
                 f"<td>{_e(sub.astimezone(ET).strftime('%b %d %H:%M ET') if sub else '—')}</td></tr>")
    if not rows:
        rows = f"<tr><td colspan='7' style='color:{MUTED}'>No open orders.</td></tr>"
    return (f"<table {_TABLE}><thead><tr {_TH}><th>Symbol</th><th>Side</th><th>Type</th>"
            "<th>Size</th><th>TIF</th><th>Status</th><th>Submitted</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _perf_block(d: dict) -> str:
    p = d.get("perf") or {}
    if not p:
        return (f"<p style='color:{MUTED};font-size:13px'>No live runner run is recorded for "
                "this account yet, so performance since start is unavailable.</p>")
    started = p.get("started")
    started_s = started.strftime("%b %d, %Y") if hasattr(started, "strftime") else _e(started or "—")
    ex = p.get("excess_pct")
    return (
        "<table style='border-collapse:collapse;font-size:13px;margin:.3rem 0'>"
        f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>Live run started</td><td>{started_s}"
        f" · start equity {_money(p.get('start_equity'))}</td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>Account since start</td>"
        f"<td><b style='color:{_col(p.get('account_pnl'))}'>{_money(p.get('account_pnl'), True)} "
        f"({_pct(p.get('account_return_pct'))})</b></td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>SPY since start</td>"
        f"<td>{_pct(p.get('spy_return_pct'))} <small style='color:{MUTED}'>"
        f"({_money(p.get('spy_start'))} → {_money(p.get('spy'))})</small></td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>Excess vs SPY</td>"
        f"<td><b style='color:{_col(ex)}'>{_pct(ex)}</b></td></tr>"
        f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>Runner strategy P&amp;L</td>"
        f"<td>{_money(p.get('strategy_pnl'), True)} <small style='color:{MUTED}'>realised "
        f"{_money(p.get('strategy_realized') or 0, True)} · open {_money(p.get('strategy_unrealized'), True)}"
        f" · {int(_f(p.get('closed_trades')))} closed</small></td></tr></table>"
        f"<p style='font-size:11px;color:{MUTED};margin:.1rem 0'>Account return is equity vs the "
        "equity when the runner started; deposits/withdrawals and pre-existing holdings are "
        "included.</p>")


def _runner_block(d: dict) -> str:
    run = d.get("run") or {}
    if not run.get("run_id"):
        return f"<p style='color:{MUTED};font-size:13px'>No live runner run recorded.</p>"
    cfg = run.get("config") or {}
    hb = d.get("runner_heartbeat")
    params = (f"dip ≥ {_f(cfg.get('dip_threshold')):g}% vs {_e(cfg.get('dip_reference') or 'ref')}"
              f" · TP +{_f(cfg.get('take_profit')):g}% · SL -{_f(cfg.get('stop_loss')):g}%"
              f" · min hold {int(_f(cfg.get('min_hold_days')))}d · max hold "
              f"{int(_f(cfg.get('hold_days')))}d · {_f(cfg.get('position_size')) * 100:.1f}% equity/position")
    head = (f"<div style='border:1px solid #DDD9CB;border-radius:6px;padding:10px 12px;margin:.4rem 0'>"
            f"<div style='font-size:15px'><b>{_e(run.get('strategy'))}</b> <span style='background:"
            f"#E4EFE7;color:{GREEN};font-size:11px;padding:2px 7px;border-radius:10px'>"
            f"{_e(run.get('status'))}</span></div>"
            f"<div style='color:{MUTED};font-size:12px;margin:.25rem 0'>run <code>"
            f"{_e(str(run.get('run_id'))[:8])}</code> · universe {_e(', '.join(cfg.get('symbols') or []))}"
            f" · last runner pass {_e(hb.astimezone(ET).strftime('%a %b %d %H:%M ET') if hb else '—')}</div>"
            f"<div style='font-size:12px;color:#415046'>{params}</div></div>")
    rows = ""
    for r in d.get("runner_open") or []:
        rows += (f"<tr><td><b>{_e(r['symbol'])}</b></td><td>{r['entry_date']:%a %b %d}</td>"
                 f"<td {_R}>{_qty(r['qty'])}</td><td {_R}>{_money(r['entry_price'])}</td>"
                 f"<td {_R} style='color:{_col(r['upl'])}'>{_money(r['upl'], True)} ({_pct(r['uplpc'])})</td>"
                 f"<td>{r['tp_sl_from']:%a %b %d}</td><td>{r['max_hold_exit']:%a %b %d} (close)</td>"
                 f"<td {_R}>{_money(r['target'])} / {_money(r['stop'])}</td></tr>")
    if not rows:
        rows = f"<tr><td colspan='8' style='color:{MUTED}'>The runner holds no open positions.</td></tr>"
    lots = (f"<table {_TABLE}><thead><tr {_TH}><th>Symbol</th><th>Entry date</th><th>Qty</th>"
            "<th>Entry</th><th>Unrealised</th><th>TP/SL from</th><th>Max-hold exit</th>"
            f"<th>TP / SL price</th></tr></thead><tbody>{rows}</tbody></table>")
    acts = ""
    for t in d.get("runner_actions") or []:
        kind = ("exit" if t.get("exit_price") is not None else
                "entry filled" if _f(t.get("shares")) > 0 else (t.get("reason") or "entry"))
        acts += (f"<li><b>{_e(t.get('symbol'))}</b> {_e(kind)}"
                 + (f" · {_qty(t.get('shares'))} @ {_money(_fn(t.get('entry_price')))}"
                    if _f(t.get("shares")) > 0 else "")
                 + (f" → exit {_money(_fn(t.get('exit_price')))} P&amp;L "
                    f"{_money(_fn(t.get('pnl')), True)} ({_e(t.get('reason'))})"
                    if t.get("exit_price") is not None else "")
                 + (f" · dip {_f(t.get('dip_pct')):.2f}%" if t.get("dip_pct") is not None else "")
                 + "</li>")
    acts = (f"<ul style='font-size:13px;margin:.2rem 0'>{acts}</ul>" if acts else
            f"<p style='font-size:13px;color:{MUTED}'>No runner entries or exits this session.</p>")
    sig_rows = ""
    for s in d.get("signals") or []:
        badge = {"signal": ("#FCE8E6", RED, "SIGNAL"), "near": ("#FBF3E2", "#8a6a1f", "near"),
                 "no": ("#F2F2EE", MUTED, "no")}[s["status"]]
        sig_rows += (f"<tr><td>{_e(s['symbol'])}</td><td {_R}>{_money(s['close'])}</td>"
                     f"<td {_R}>{_money(s['high20'])}</td><td {_R}>{s['dip']:.2f}%</td>"
                     f"<td><span style='background:{badge[0]};color:{badge[1]};padding:1px 6px;"
                     f"border-radius:8px;font-size:11px'>{badge[2]}</span></td></tr>")
    sigs = ""
    if sig_rows:
        sigs = (f"<p style='font-size:12px;color:#415046;margin:.5rem 0 .2rem'>Dip vs 20-day high at "
                f"the close (entry needs ≥ {_f(cfg.get('dip_threshold'), 3):g}% in the 15:45–15:55 ET "
                "window; held names are skipped):</p>"
                f"<table {_TABLE}><thead><tr {_TH}><th>Symbol</th><th>Close</th><th>20d high</th>"
                f"<th>Dip</th><th>Status</th></tr></thead><tbody>{sig_rows}</tbody></table>")
    return head + "<h4 style='margin:.5rem 0 .2rem'>Runner actions this session</h4>" + acts + \
        f"<h4 style='margin:.5rem 0 .2rem'>Runner open positions</h4>{lots}{sigs}"


def render(d: dict) -> str:
    day_label = datetime.strptime(d["day"], "%Y-%m-%d").strftime("%a %b %d, %Y")
    if d.get("no_trading_day"):
        return (f"<div style='font-family:Inter,Arial,sans-serif'><h2>AlpaTrade — Daily LIVE "
                f"report · {day_label}</h2><p>No trading day (US market closed).</p></div>")
    sign = "▲" if d["day_pnl"] >= 0 else "▼"
    warn = "".join(
        "<p style='background:#FCE8E6;border-left:3px solid #B4472F;padding:8px 10px;"
        f"font-size:12px;color:#7A2E1D;margin:.4rem 0'><b>Attention:</b> {_e(w)}</p>"
        for w in d.get("warnings") or [])
    if not d.get("db_ok", True):
        warn += ("<p style='background:#FCE8E6;padding:8px 10px;font-size:12px'>The AlpaTrade "
                 "database was unreachable: runner sections may be empty for that reason.</p>")
    back = ""
    if d.get("backdated"):
        back = ("<p style='background:#FBF3E2;border-left:3px solid #C79A3B;padding:8px 10px;"
                "font-size:12px;color:#5B4A22;margin:.4rem 0'>Report for the session of "
                f"{day_label}: equity/day P&amp;L are that session's close (Alpaca history) and "
                "fills are that session's; positions, open orders, cash and buying power are the "
                f"<b>live</b> account as of {d['generated_at']:%a %b %d %H:%M ET}.</p>")
    fills = d.get("fills") or []
    realised = [o["realized"] for o in fills if o.get("realized") is not None]
    buys = sum(1 for o in fills if o["side"] == "buy")
    sells = sum(1 for o in fills if o["side"] == "sell")
    upl = sum(_f(p.get("unrealized_pl")) for p in d.get("positions") or [])
    return f"""
<div style="font-family:Inter,Arial,sans-serif;color:#14231B;max-width:780px">
  <h2 style="margin-bottom:.2rem">AlpaTrade — Daily LIVE report · {day_label}</h2>
  <p style="background:#EFEDE4;padding:8px 10px;margin:.3rem 0">Alpaca live account
     <b>{_e(d.get('account_number'))}</b> · {_e(d.get('label') or 'Alpaca live')} · owner
     {_e(d.get('email') or '')} <span style="background:#B4472F;color:#fff;font-size:11px;
     padding:1px 6px;border-radius:8px">REAL MONEY</span></p>
  {warn}{back}
  <p style="font-size:20px;margin:.4rem 0"><b style="color:{_col(d['day_pnl'])}">{sign}
     {_money(d['day_pnl'], True)} ({d['day_pct']:+.2f}%)</b>
     <span style="color:{MUTED}">day <span style="font-size:12px">(vs prior close
     {_money(d['last_equity'])})</span></span></p>
  <table style="border-collapse:collapse;margin:.4rem 0;font-size:14px">
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Equity (session close)</td><td><b>{_money(d['equity'])}</b></td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Equity now</td><td>{_money(d['equity_now'])}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Cash</td><td>{_money(d['cash'])}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Buying power</td><td>{_money(d['buying_power'])}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Open unrealised P&amp;L</td><td style="color:{_col(upl)}">{_money(upl, True)}</td></tr>
  </table>
  <h3 style="margin:.9rem 0 .2rem">Performance since live start vs SPY</h3>
  {_perf_block(d)}
  <h3>Fills this session ({len(fills)})</h3>
  <p style="color:#415046;font-size:13px;margin:.15rem 0 .4rem">{buys} buy · {sells} sell ·
     realised P&amp;L <b style="color:{_col(sum(realised))}">{_money(sum(realised), True) if realised else '—'}</b>
     <span style="color:{MUTED};font-size:11px">(window {d['window'][0]:%a %H:%M} – {d['window'][1]:%a %H:%M} ET,
     incl. overnight session)</span></p>
  {_fills_table(fills)}
  <h3>Current positions ({len(d.get('positions') or [])})</h3>
  {_positions_table(d.get('positions') or [])}
  <h3>Open orders ({len(d.get('open_orders') or [])})</h3>
  {_orders_table(d.get('open_orders') or [])}
  <h3>Live runner (Mag-7 buy-the-dip)</h3>
  {_runner_block(d)}
  <p style="color:{MUTED};font-size:12px;margin-top:1rem">Live trading — real money. This report
  is read-only (it cannot place, cancel or close anything). Realised P&amp;L is the runner's
  recorded P&amp;L or a FIFO estimate from Alpaca fill history. Not financial advice.</p>
</div>"""


def subject_for(d: dict) -> str:
    day_label = datetime.strptime(d["day"], "%Y-%m-%d").strftime("%b %d, %Y")
    if d.get("no_trading_day"):
        return f"AlpaTrade LIVE — {day_label} (no trading day)"
    return (f"AlpaTrade LIVE PnL — {day_label} "
            f"({'+' if d['day_pnl'] >= 0 else '-'}${abs(d['day_pnl']):,.0f}, {d['day_pct']:+.2f}%)")


def plain_summary(d: dict) -> str:
    if d.get("no_trading_day"):
        return f"{d['day']}: no trading day"
    lines = [f"{d['day']} acct {d.get('account_number')}: equity {_money(d['equity'])} "
             f"(now {_money(d['equity_now'])}), cash {_money(d['cash'])}, day "
             f"{_money(d['day_pnl'], True)} ({d['day_pct']:+.2f}%)"]
    for o in d.get("fills") or []:
        lines.append(f"  fill {o['time'].astimezone(ET):%a %H:%M ET} {o['symbol']} {o['side']} "
                     f"{_qty(o['qty'])} @ {_money(o['price'])} realised "
                     f"{_money(o['realized'], True) if o.get('realized') is not None else 'n/a'} "
                     f"[{o['source']}]")
    for p in d.get("positions") or []:
        lines.append(f"  pos {p.get('symbol')} {p.get('qty')} @ {_f(p.get('avg_entry_price')):.2f} "
                     f"upl {_money(_f(p.get('unrealized_pl')), True)}")
    for o in d.get("open_orders") or []:
        lines.append(f"  open order {o.get('symbol')} {o.get('side')} {o.get('qty') or o.get('notional')}"
                     f" {o.get('type')} {o.get('status')}")
    for r in d.get("runner_open") or []:
        lines.append(f"  runner lot {r['symbol']} entry {r['entry_date']} max-hold exit {r['max_hold_exit']}")
    for s in d.get("signals") or []:
        lines.append(f"  dip {s['symbol']} {s['dip']:.2f}% {s['status']}")
    p = d.get("perf") or {}
    if p:
        lines.append(f"  since start: acct {_pct(p.get('account_return_pct'))} vs SPY "
                     f"{_pct(p.get('spy_return_pct'))}")
    lines += [f"  WARNING: {w}" for w in d.get("warnings") or []]
    return "\n".join(lines)


# ------------------------------------------------------------------- send / job
def send_report(target: dict, day: date | None = None, force: bool = False,
                html_out: str | None = None, send: bool = True, client=None) -> dict:
    """Gather, render and (optionally) email one live report to the target's owner."""
    from utils.email_util import send_email_to_result
    client = client or client_for(target)
    if client is None:
        return {"ok": False, "error": "no live credentials"}
    d = gather(client, target, day=day)
    html_body = render(d)
    if html_out:
        Path(html_out).write_text(html_body)
    out = {"ok": True, "day": d["day"], "data": d, "sent": False, "message_id": None}
    if d.get("no_trading_day") or not send:
        return out
    if not claim_live_delivery(target["user_id"], target["account_number"], d["day"], force=force):
        return {**out, "ok": False, "error": "already sent (use --force to resend)"}
    res = {"ok": False, "message_id": None, "error": None}
    try:
        res = send_email_to_result(target["email"], subject_for(d), html_body)
    finally:
        finish_live_delivery(target["user_id"], target["account_number"], d["day"],
                             bool(res.get("ok")), res.get("message_id"))
    return {**out, "ok": bool(res.get("ok")), "sent": bool(res.get("ok")),
            "message_id": res.get("message_id"), "error": res.get("error")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--email", default=None, help="owner email of the live link (default: all)")
    ap.add_argument("--date", default=None, help="ET trading date YYYY-MM-DD (default: latest completed)")
    ap.add_argument("--send", action="store_true", help="email the owner (default: print only)")
    ap.add_argument("--force", action="store_true", help="resend even if already delivered")
    ap.add_argument("--html-out", default=None, help="also write the rendered HTML here")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    day = date.fromisoformat(args.date) if args.date else None
    targets = report_targets(args.email)
    if not targets:
        print("no active live-account links found" + (f" for {args.email}" if args.email else ""))
        return 2
    rc = 0
    for t in targets:
        html_out = args.html_out
        if html_out and len(targets) > 1:
            html_out = html_out.replace(".html", f"-{t['account_number']}.html")
        res = send_report(t, day=day, force=args.force, html_out=html_out, send=args.send)
        d = res.get("data") or {}
        print(plain_summary(d) if d else res)
        if html_out:
            print(f"html → {html_out}")
        if args.send:
            print(f"email → {t['email']} (owner only): "
                  f"{'SENT message_id=' + str(res.get('message_id')) if res.get('sent') else 'NOT SENT ' + str(res.get('error'))}")
            rc |= 0 if res.get("sent") or d.get("no_trading_day") else 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
