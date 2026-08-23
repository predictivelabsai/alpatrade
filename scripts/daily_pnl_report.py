#!/usr/bin/env python3
"""Legacy manual paper-trading P&L renderer.

Pulls the live Alpaca **paper** account (equity, day change, open positions with
unrealised P&L) and the day's paper trades from the `alpatrade.trades` table, renders an
HTML digest, and can email an explicitly supplied recipient via Postmark. Scheduled
delivery moved to the tenant-scoped daily advisor in engine.autonomy.schedule.

The digest reports the strategy that is actually running (name, status, universe and
every tuned parameter from `alpatrade.runs.config`) and, for each trade, explains what
triggered it by reading the trade against those parameters — e.g. a buy is shown as the
observed dip against the configured dip threshold, an exit as the realised move against
the configured take-profit/stop-loss.

Usage:
  python scripts/daily_pnl_report.py                        # print HTML, no send
  python scripts/daily_pnl_report.py --date 2026-08-03      # re-render a past day
  python scripts/daily_pnl_report.py --send --to user@example.com
"""
from __future__ import annotations

import argparse
import html as _html
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass


# Pretty labels + units for the strategy parameters surfaced in the digest.
_PARAM_LABELS = {
    "dip_threshold": ("Dip threshold", "pct"),
    "take_profit_threshold": ("Take profit", "pct"),
    "stop_loss_threshold": ("Stop loss", "pct"),
    "hold_days": ("Max hold", "days"),
    "min_hold_days": ("Min hold", "days"),
    "capital_per_trade": ("Capital per trade", "usd"),
    "lookback_days": ("Lookback", "days"),
    "momentum_threshold": ("Momentum threshold", "pct"),
    "vix_threshold": ("VIX threshold", "num"),
}

_STRATEGY_LABELS = {
    "buy_the_dip": "Buy the Dip",
    "momentum": "Momentum",
    "vix": "VIX Fear Index",
    "box_wedge": "Box-Wedge",
}


def recipients(override: str | None = None) -> list[str]:
    """Legacy CLI recipients; there is deliberately no hardcoded distribution list."""
    raw = override or os.getenv("PNL_REPORT_TO") or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _e(v) -> str:
    """HTML-escape a value for interpolation into the digest."""
    return _html.escape(str(v if v is not None else ""))


def gather(day: str | None = None, keys: tuple[str, str] | None = None) -> dict:
    from engine.brokers.alpaca import AlpacaAPI
    api = AlpacaAPI(*keys, paper=True) if keys else AlpacaAPI(paper=True)
    acct = api.get_account() or {}
    positions = api.get_positions() or []
    equity = _f(acct.get("equity"))
    last_equity = _f(acct.get("last_equity")) or equity
    day_pnl = equity - last_equity
    day_pct = (equity / last_equity - 1) * 100 if last_equity else 0.0
    unreal = sum(_f(p.get("unrealized_pl")) for p in positions)
    trades = gather_trades(day)
    runs = gather_runs([t.get("run_id") for t in trades])
    return {
        "equity": equity, "last_equity": last_equity, "day_pnl": day_pnl, "day_pct": day_pct,
        "cash": _f(acct.get("cash")), "buying_power": _f(acct.get("buying_power")),
        "unrealized_pl": unreal, "daytrade_count": acct.get("daytrade_count"),
        "positions": positions,
        "trades": trades,
        "runs": runs,
        "active_runs": active_runs(),
        "day": day or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def gather_trades(day: str | None = None, limit: int = 100,
                  user_id: str | None = None,
                  account_id: str | None = None) -> list[dict]:
    """Paper trades booked on `day` (default: today UTC) — [] on any failure.

    Trades are matched by `created_at` falling on that UTC date, so the report reflects
    what was actually booked during the trading day regardless of entry/exit fill times.
    """
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        target = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with pool.get_session() as session:
            where = [
                "trade_type = 'paper'",
                "created_at >= CAST(:day AS DATE)",
                "created_at < CAST(:day AS DATE) + INTERVAL '1 day'",
            ]
            params = {"day": target, "lim": limit}
            if user_id:
                where.append("user_id = :user_id")
                params["user_id"] = user_id
            if account_id:
                where.append("account_id = :account_id")
                params["account_id"] = account_id
            result = session.execute(
                text(
                    "SELECT symbol, direction, shares, entry_price, exit_price, "
                    "       pnl, pnl_pct, reason, created_at, entry_time, exit_time, "
                    "       run_id, dip_pct, target_price, stop_price, hit_target, hit_stop "
                    "FROM alpatrade.trades "
                    f"WHERE {' AND '.join(where)} "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                params,
            )
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001 — report must never fail the email send
        return []


def gather_runs(run_ids) -> dict[str, dict]:
    """Strategy metadata (name, status, config/params) keyed by run_id."""
    ids = sorted({r for r in (run_ids or []) if r})
    if not ids:
        return {}
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(
                text("SELECT run_id, mode, strategy, strategy_slug, status, config, "
                     "       started_at, completed_at "
                     "FROM alpatrade.runs WHERE run_id = ANY(:ids)"),
                {"ids": ids},
            )
            cols = result.keys()
            return {row[0]: dict(zip(cols, row)) for row in result.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def active_runs(limit: int = 5) -> list[dict]:
    """Currently-running paper runs, newest first — the agent(s) live right now."""
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(
                text("SELECT run_id, mode, strategy, strategy_slug, status, config, "
                     "       started_at, completed_at "
                     "FROM alpatrade.runs "
                     "WHERE mode = 'paper' AND status = 'running' "
                     "ORDER BY started_at DESC LIMIT :lim"),
                {"lim": limit},
            )
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def _params_of(run: dict | None) -> dict:
    cfg = (run or {}).get("config") or {}
    if not isinstance(cfg, dict):
        return {}
    params = cfg.get("params")
    return params if isinstance(params, dict) else {}


def _fmt_param(key: str, value) -> tuple[str, str]:
    label, unit = _PARAM_LABELS.get(key, (key.replace("_", " ").capitalize(), "num"))
    if unit == "pct":
        return label, f"{_f(value):.2f}%"
    if unit == "usd":
        return label, f"${_f(value):,.0f}"
    if unit == "days":
        n = _f(value)
        return label, f"{n:.0f} day{'' if n == 1 else 's'}"
    return label, str(value)


def _held_days(t: dict) -> int | None:
    entry, exit_t = t.get("entry_time"), t.get("exit_time")
    if not entry:
        return None
    end = exit_t or datetime.now(timezone.utc)
    try:
        return max((end - entry).days, 0)
    except Exception:  # noqa: BLE001 — mixed tz-awareness shouldn't break the email
        return None


def _explain(t: dict, run: dict | None) -> str:
    """Explain *why* a trade happened, reading it against the strategy's parameters.

    Falls back to the raw `reason` string when there's nothing richer to say, so a
    strategy that stores its own reason text still renders sensibly.
    """
    params = _params_of(run)
    raw = (t.get("reason") or "").strip()
    code = raw.split("(")[0].strip().upper()
    pnl_pct = t.get("pnl_pct")
    dip = t.get("dip_pct")
    exit_p = _f(t.get("exit_price"))
    held = _held_days(t)
    bits: list[str] = []

    is_entry = not exit_p and t.get("pnl") is None
    if is_entry:
        if dip is not None:
            trigger = params.get("dip_threshold")
            bits.append(f"Dip -{_f(dip):.2f}%" +
                        (f" past -{_f(trigger):.2f}% trigger" if trigger is not None else ""))
        elif raw:
            bits.append(raw)
        else:
            bits.append("Entry signal")
        cap = params.get("capital_per_trade")
        if cap:
            bits.append(f"sized ${_f(cap):,.0f}/trade")
    elif code == "TAKE_PROFIT":
        tp = params.get("take_profit_threshold")
        bits.append(f"Take-profit {_f(pnl_pct):+.2f}%" +
                    (f" reached {_f(tp):.2f}% target" if tp is not None else ""))
    elif code in ("STOP_LOSS", "STOPLOSS"):
        sl = params.get("stop_loss_threshold")
        bits.append(f"Stop-loss {_f(pnl_pct):+.2f}%" +
                    (f" breached -{_f(sl):.2f}% limit" if sl is not None else ""))
    elif code in ("HOLD_DAYS", "MAX_HOLD", "TIME_EXIT", "TIMEOUT"):
        hd = params.get("hold_days")
        bits.append("Max hold reached" + (f" ({_f(hd):.0f}d)" if hd is not None else "") +
                    (f", exited {_f(pnl_pct):+.2f}%" if pnl_pct is not None else ""))
    elif raw:
        bits.append(raw)
    else:
        bits.append("—")

    if held is not None and not is_entry:
        mh = params.get("min_hold_days")
        bits.append(f"held {held}d" + (f" (min {_f(mh):.0f}d)" if mh is not None else ""))

    strategy = (run or {}).get("strategy")
    if strategy:
        bits.append(_STRATEGY_LABELS.get(strategy, strategy))
    return " · ".join(b for b in bits if b)


def _render_strategy(d: dict) -> str:
    """The 'what is running, and how is it tuned' block."""
    runs = list(d.get("active_runs") or [])
    seen = {r.get("run_id") for r in runs}
    # Include any run that produced today's trades but is no longer marked running.
    for rid, run in (d.get("runs") or {}).items():
        if rid not in seen:
            runs.append(run)
            seen.add(rid)
    if not runs:
        return ("<h3>Strategy &amp; agent</h3>"
                "<p style='color:#7A867E;font-size:13px'>No running paper strategy found.</p>")

    traded = {t.get("run_id") for t in d.get("trades", [])}

    # Stale paper runs are never marked completed, so several identical `running` rows
    # pile up. Collapse them by configuration and keep the one that actually traded
    # (else the newest), noting how many duplicates it stands for.
    groups: dict[tuple, list[dict]] = {}
    for run in runs:
        cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
        key = (run.get("strategy"), repr(sorted(_params_of(run).items())),
               repr(cfg.get("symbols")))
        groups.setdefault(key, []).append(run)
    deduped: list[tuple[dict, int]] = []
    for members in groups.values():
        pick = next((m for m in members if m.get("run_id") in traded), members[0])
        deduped.append((pick, len(members) - 1))

    blocks = ""
    for run, dupes in deduped:
        rid = run.get("run_id") or ""
        strategy = run.get("strategy") or "unknown"
        name = _STRATEGY_LABELS.get(strategy, strategy)
        status = (run.get("status") or "").lower()
        badge_bg = "#E4EFE7" if status == "running" else "#EFEDE4"
        badge_fg = "#1F5D43" if status == "running" else "#415046"
        started = run.get("started_at")
        started_s = started.strftime("%b %d, %Y %H:%M UTC") if hasattr(started, "strftime") else "—"
        cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
        symbols = cfg.get("symbols") or []
        params = _params_of(run)
        slug = run.get("strategy_slug")

        param_cells = "".join(
            f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>{_e(lbl)}</td>"
            f"<td><b>{_e(val)}</b></td></tr>"
            for lbl, val in (_fmt_param(k, v) for k, v in sorted(params.items()))
        ) or "<tr><td style='color:#7A867E'>No parameters recorded for this run.</td></tr>"

        note = ("<span style='color:#1F5D43;font-size:12px'>&nbsp;· traded today</span>"
                if rid in traded else "")
        dupe_note = (f"<div style='color:#7A867E;font-size:11px;margin-bottom:.35rem'>"
                     f"+{dupes} older run{'' if dupes == 1 else 's'} with identical configuration "
                     f"still marked running</div>" if dupes else "")
        blocks += f"""
  <div style="border:1px solid #DDD9CB;border-radius:6px;padding:10px 12px;margin:.4rem 0">
    <div style="font-size:15px"><b>{_e(name)}</b>
      <span style="background:{badge_bg};color:{badge_fg};font-size:11px;padding:2px 7px;
        border-radius:10px;margin-left:6px">{_e(status or 'unknown')}</span>{note}</div>
    <div style="color:#7A867E;font-size:12px;margin:.25rem 0">
      run <code>{_e(rid[:8])}</code> · {_e(run.get('mode') or 'paper')} · started {_e(started_s)}
      {('· slug <code>' + _e(slug) + '</code>') if slug else ''}</div>
    {dupe_note}
    <div style="font-size:12px;color:#415046;margin-bottom:.35rem">
      Universe: {_e(', '.join(symbols)) if symbols else '—'}</div>
    <table style="border-collapse:collapse;font-size:13px">{param_cells}</table>
  </div>"""
    return f"<h3>Strategy &amp; agent ({len(deduped)})</h3>{blocks}"


def _stale_notice(d: dict) -> str:
    """Warn when trades are back-dated but the account snapshot is necessarily live.

    Alpaca only exposes the account as it stands now, so a `--date` in the past mixes
    historical trades with a current portfolio. Say so rather than implying otherwise.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not d.get("day") or d["day"] == today:
        return ""
    return ("<p style='background:#FBF3E2;border-left:3px solid #C79A3B;padding:8px 10px;"
            "font-size:12px;color:#5B4A22;margin:.4rem 0'>Back-dated report: trades and "
            f"realised P&amp;L are for {_e(d['day'])}, but portfolio value, open positions "
            "and today's change are the <b>live</b> account as of now.</p>")


def render(d: dict) -> str:
    sign = "▲" if d["day_pnl"] >= 0 else "▼"
    color = "#1F5D43" if d["day_pnl"] >= 0 else "#b0653f"
    rows = ""
    for p in sorted(d["positions"], key=lambda x: _f(x.get("unrealized_pl")), reverse=True):
        pl = _f(p.get("unrealized_pl"))
        plc = _f(p.get("unrealized_plpc")) * 100
        c = "#1F5D43" if pl >= 0 else "#b0653f"
        rows += (f"<tr><td>{_e(p.get('symbol',''))}</td><td style='text-align:right'>{_f(p.get('qty')):g}</td>"
                 f"<td style='text-align:right'>${_f(p.get('avg_entry_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('current_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('market_value')):,.0f}</td>"
                 f"<td style='text-align:right;color:{c}'>${pl:,.0f} ({plc:+.1f}%)</td></tr>")
    if not rows:
        rows = "<tr><td colspan='6' style='color:#7A867E'>No open positions.</td></tr>"
    trade_rows, n_buys, n_sells, realized = _render_trades(d.get("trades", []), d.get("runs") or {})
    day_label = datetime.strptime(d.get("day"), "%Y-%m-%d").strftime("%b %d, %Y") \
        if d.get("day") else datetime.now(timezone.utc).strftime("%b %d, %Y")
    return f"""
<div style="font-family:Inter,Arial,sans-serif;color:#14231B;max-width:760px">
  <h2>AlpaTrade — Daily Paper PnL · {day_label}</h2>
  {_stale_notice(d)}
  <p style="font-size:20px;margin:.2rem 0"><b style="color:{color}">{sign} ${d['day_pnl']:,.2f}
     ({d['day_pct']:+.2f}%)</b> <span style="color:#7A867E">today</span></p>
  <table style="border-collapse:collapse;margin:.4rem 0">
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Portfolio value</td><td><b>${d['equity']:,.2f}</b></td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Cash</td><td>${d['cash']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Buying power</td><td>${d['buying_power']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Open unrealised P&amp;L</td><td>${d['unrealized_pl']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Day trades (5d)</td><td>{_e(d['daytrade_count']) or 'None'}</td></tr>
  </table>
  {_render_strategy(d)}
  <h3>Open positions ({len(d['positions'])})</h3>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Qty</th><th>Entry</th><th>Price</th><th>Value</th><th>Unrealised P&amp;L</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h3>Paper trades ({len(d.get('trades', []))})</h3>
  <p style="color:#415046;font-size:13px;margin:.15rem 0 .4rem">{n_buys} buy · {n_sells} sell
     · realised P&amp;L <b style="color:{'#1F5D43' if realized >= 0 else '#b0653f'}">${realized:,.2f}</b></p>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reasoning</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
  <p style="color:#7A867E;font-size:12px;margin-top:1rem">Paper trading — simulated, no real money.
  Not financial advice. AlpaTrade holds no funds.</p>
</div>"""


def _render_trades(trades: list[dict], runs: dict[str, dict]) -> tuple[str, int, int, float]:
    """Render the trades <tbody> and return (rows_html, n_buys, n_sells, realized_pnl)."""
    n_buys = n_sells = 0
    realized = 0.0
    rows = ""
    saw_realized = False
    for t in trades:
        sym = t.get("symbol") or ""
        side_raw = (t.get("direction") or "").lower()
        side = side_raw if side_raw in ("buy", "sell") else (
            "buy" if side_raw in ("long", "b") else "sell" if side_raw in ("short", "s") else side_raw
        )
        if side == "buy":
            n_buys += 1
        elif side == "sell":
            n_sells += 1
        qty = _f(t.get("shares"))
        entry = _f(t.get("entry_price"))
        exit_p = _f(t.get("exit_price"))
        pnl = t.get("pnl")
        pnl_val = _f(pnl)
        if pnl is not None:
            saw_realized = True
            realized += pnl_val
        c = "#1F5D43" if pnl_val >= 0 else "#b0653f"
        pnl_cell = (f"${pnl_val:,.2f}" if pnl is not None
                    else ("-" if not exit_p else f"${pnl_val:,.2f}"))
        exit_cell = f"${exit_p:,.2f}" if exit_p else "—"
        reasoning = _e(_explain(t, runs.get(t.get("run_id"))))
        rows += (f"<tr><td>{_e(sym)}</td><td>{_e(side or '—')}</td>"
                 f"<td style='text-align:right'>{qty:g}</td>"
                 f"<td style='text-align:right'>${entry:,.2f}</td>"
                 f"<td style='text-align:right'>{exit_cell}</td>"
                 f"<td style='text-align:right;color:{c}'>{pnl_cell}</td>"
                 f"<td style='font-size:12px;color:#415046'>{reasoning}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='7' style='color:#7A867E'>No paper trades booked.</td></tr>"
    # If no closed trades had a pnl value, don't pretend a $0.00 realised figure.
    if not saw_realized:
        realized = 0.0
    return rows, n_buys, n_sells, realized


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--date", default=None, help="UTC date to report on (YYYY-MM-DD, default today)")
    ap.add_argument("--to", default=None, help="comma-separated recipients (default: PNL_REPORT_TO)")
    args = ap.parse_args()

    if args.date:
        datetime.strptime(args.date, "%Y-%m-%d")  # fail fast on a bad date

    to_list = recipients(args.to)
    data = gather(args.date)
    html_out = render(data)
    if not args.send:
        print(html_out)
        n_tr = len(data.get("trades", []))
        n_runs = len(data.get("active_runs", []))
        print(f"\n[dry-run] {data['day']}: day PnL ${data['day_pnl']:,.2f} ({data['day_pct']:+.2f}%), "
              f"equity ${data['equity']:,.2f}, {len(data['positions'])} positions, "
              f"{n_tr} paper trades, {n_runs} running strategy run(s). "
              f"Would email → {', '.join(to_list)}")
        return 0
    if not to_list:
        ap.error("--send requires --to or PNL_REPORT_TO")
    from utils.email_util import send_email_to
    day_label = datetime.strptime(data["day"], "%Y-%m-%d").strftime("%b %d, %Y")
    subject = f"AlpaTrade Paper PnL — {day_label} "
    subject += f"({'+' if data['day_pnl'] >= 0 else ''}${data['day_pnl']:,.0f})"
    all_ok = True
    for to in to_list:
        ok = send_email_to(to, subject, html_out)
        all_ok &= ok
        print(f"email → {to}: {'SENT' if ok else 'FAILED (check POSTMARK_API_KEY / FROM_EMAIL)'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
