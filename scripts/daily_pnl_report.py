#!/usr/bin/env python3
"""Daily paper-trading PnL report — emailed after market close.

Pulls the live Alpaca **paper** account (equity, day change, open positions with
unrealised P&L) and any paper trades booked today, renders an HTML digest, and emails
it via Postmark. Designed to be fired nightly by engine.autonomy.schedule.

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
    }


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
  <p style="color:#7A867E;font-size:12px;margin-top:1rem">Paper trading — simulated, no real money.
  Not financial advice. AlpaTrade holds no funds.</p>
</div>"""


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
        print(f"\n[dry-run] day PnL ${data['day_pnl']:,.2f} ({data['day_pct']:+.2f}%), "
              f"equity ${data['equity']:,.2f}, {len(data['positions'])} positions. "
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
