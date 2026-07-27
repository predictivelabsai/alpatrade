#!/usr/bin/env python3
"""Daily paper-trading PnL + trade report — emailed after market close.

Pulls the live Alpaca **paper** account (equity, day change, open positions with
unrealised P&L) and today's paper trades from the `alpatrade.trades` table, renders an
HTML digest, and emails it via Postmark. Designed to be fired nightly by
engine.autonomy.schedule.

Usage:
  python scripts/daily_pnl_report.py                 # print HTML, no send
  python scripts/daily_pnl_report.py --send          # email to PNL_REPORT_TO / TO_EMAIL
  python scripts/daily_pnl_report.py --send --to kaljuvee@gmail.com
"""
from __future__ import annotations

import argparse
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


# Default distribution list (override with PNL_REPORT_TO, comma-separated).
DEFAULT_RECIPIENTS = ("kaljuvee@gmail.com,"
                      "siwei.feng@predictivelabs.co.uk,"
                      "raslen.guesmi@predictivelabs.co.uk")


def recipients(override: str | None = None) -> list[str]:
    raw = override or os.getenv("PNL_REPORT_TO") or DEFAULT_RECIPIENTS
    return [e.strip() for e in raw.split(",") if e.strip()]


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def gather() -> dict:
    from engine.brokers.alpaca import AlpacaAPI
    api = AlpacaAPI(paper=True)
    acct = api.get_account() or {}
    positions = api.get_positions() or []
    equity = _f(acct.get("equity"))
    last_equity = _f(acct.get("last_equity")) or equity
    day_pnl = equity - last_equity
    day_pct = (equity / last_equity - 1) * 100 if last_equity else 0.0
    unreal = sum(_f(p.get("unrealized_pl")) for p in positions)
    return {
        "equity": equity, "last_equity": last_equity, "day_pnl": day_pnl, "day_pct": day_pct,
        "cash": _f(acct.get("cash")), "buying_power": _f(acct.get("buying_power")),
        "unrealized_pl": unreal, "daytrade_count": acct.get("daytrade_count"),
        "positions": positions,
        "trades": gather_trades(),
    }


def gather_trades(limit: int = 100) -> list[dict]:
    """Today's paper trades from `alpatrade.trades` (best-effort — [] on any failure).

    Trades are matched by `created_at` falling on today's UTC date, so the report reflects
    what was actually booked during the trading day regardless of entry/exit fill times.
    """
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with pool.get_session() as session:
            result = session.execute(
                text(
                    "SELECT symbol, direction, shares, entry_price, exit_price, "
                    "       pnl, pnl_pct, reason, created_at, entry_time, exit_time "
                    "FROM alpatrade.trades "
                    "WHERE trade_type = 'paper' "
                    "  AND created_at >= CAST(:today AS DATE) "
                    "  AND created_at <  CAST(:today AS DATE) + INTERVAL '1 day' "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"today": today, "lim": limit},
            )
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001 — report must never fail the email send
        return []


def render(d: dict) -> str:
    sign = "▲" if d["day_pnl"] >= 0 else "▼"
    color = "#1F5D43" if d["day_pnl"] >= 0 else "#b0653f"
    rows = ""
    for p in sorted(d["positions"], key=lambda x: _f(x.get("unrealized_pl")), reverse=True):
        pl = _f(p.get("unrealized_pl"))
        plc = _f(p.get("unrealized_plpc")) * 100
        c = "#1F5D43" if pl >= 0 else "#b0653f"
        rows += (f"<tr><td>{p.get('symbol','')}</td><td style='text-align:right'>{_f(p.get('qty')):g}</td>"
                 f"<td style='text-align:right'>${_f(p.get('avg_entry_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('current_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('market_value')):,.0f}</td>"
                 f"<td style='text-align:right;color:{c}'>${pl:,.0f} ({plc:+.1f}%)</td></tr>")
    if not rows:
        rows = "<tr><td colspan='6' style='color:#7A867E'>No open positions.</td></tr>"
    trade_rows, n_buys, n_sells, realized = _render_trades(d.get("trades", []))
    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    return f"""
<div style="font-family:Inter,Arial,sans-serif;color:#14231B;max-width:680px">
  <h2>AlpaTrade — Daily Paper PnL · {today}</h2>
  <p style="font-size:20px;margin:.2rem 0"><b style="color:{color}">{sign} ${d['day_pnl']:,.2f}
     ({d['day_pct']:+.2f}%)</b> <span style="color:#7A867E">today</span></p>
  <table style="border-collapse:collapse;margin:.4rem 0">
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Portfolio value</td><td><b>${d['equity']:,.2f}</b></td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Cash</td><td>${d['cash']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Buying power</td><td>${d['buying_power']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Open unrealised P&amp;L</td><td>${d['unrealized_pl']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Day trades (5d)</td><td>{d['daytrade_count']}</td></tr>
  </table>
  <h3>Open positions ({len(d['positions'])})</h3>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Qty</th><th>Entry</th><th>Price</th><th>Value</th><th>Unrealised P&amp;L</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h3>Today's paper trades ({len(d.get('trades', []))})</h3>
  <p style="color:#415046;font-size:13px;margin:.15rem 0 .4rem">{n_buys} buy · {n_sells} sell
     · realised P&amp;L <b style="color:{'#1F5D43' if realized >= 0 else '#b0653f'}">${realized:,.2f}</b></p>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reason</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
  <p style="color:#7A867E;font-size:12px;margin-top:1rem">Paper trading — simulated, no real money.
  Not financial advice. AlpaTrade holds no funds.</p>
</div>"""


def _render_trades(trades: list[dict]) -> tuple[str, int, int, float]:
    """Render the today's-trades <tbody> and return (rows_html, n_buys, n_sells, realized_pnl)."""
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
        reason = (t.get("reason") or "").replace("<", "&lt;").replace(">", "&gt;") or "—"
        rows += (f"<tr><td>{sym}</td><td>{side or '—'}</td>"
                 f"<td style='text-align:right'>{qty:g}</td>"
                 f"<td style='text-align:right'>${entry:,.2f}</td>"
                 f"<td style='text-align:right'>${exit_p:,.2f}</td>"
                 f"<td style='text-align:right;color:{c}'>{pnl_cell}</td>"
                 f"<td style='font-size:12px;color:#415046'>{reason}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='7' style='color:#7A867E'>No paper trades booked today.</td></tr>"
    # If no closed trades had a pnl value, don't pretend a $0.00 realised figure.
    if not saw_realized:
        realized = 0.0
    return rows, n_buys, n_sells, realized


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--to", default=None, help="comma-separated recipients (default: PNL_REPORT_TO / list)")
    args = ap.parse_args()

    to_list = recipients(args.to)
    data = gather()
    html = render(data)
    if not args.send:
        print(html)
        n_tr = len(data.get("trades", []))
        print(f"\n[dry-run] day PnL ${data['day_pnl']:,.2f} ({data['day_pct']:+.2f}%), "
              f"equity ${data['equity']:,.2f}, {len(data['positions'])} positions, "
              f"{n_tr} paper trades today. "
              f"Would email → {', '.join(to_list)}")
        return 0
    from utils.email_util import send_email_to
    subject = f"AlpaTrade Paper PnL — {datetime.now(timezone.utc).strftime('%b %d, %Y')} "
    subject += f"({'+' if data['day_pnl'] >= 0 else ''}${data['day_pnl']:,.0f})"
    all_ok = True
    for to in to_list:
        ok = send_email_to(to, subject, html)
        all_ok &= ok
        print(f"email → {to}: {'SENT' if ok else 'FAILED (check POSTMARK_API_KEY / FROM_EMAIL)'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
