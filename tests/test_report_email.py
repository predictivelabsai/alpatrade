#!/usr/bin/env python3
"""
Test script for the email PnL report with account/user grouping.
Sends a real email via Postmark and saves the HTML report locally.

Usage:
    python tests/test_report_email.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

# Load .env
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from utils.email_util import send_daily_pnl_report

# ---------------------------------------------------------------------------
# Sample data (mimics a real multi-position day)
# ---------------------------------------------------------------------------
DATE = datetime.now().strftime("%Y-%m-%d")

POSITIONS = [
    {"symbol": "AAPL",  "qty": 3, "avg_entry_price": 264.53, "current_price": 264.38, "unrealized_pl": -0.45},
    {"symbol": "AMZN",  "qty": 4, "avg_entry_price": 209.40, "current_price": 207.83, "unrealized_pl": -6.28},
    {"symbol": "GOOGL", "qty": 2, "avg_entry_price": 305.20, "current_price": 305.30, "unrealized_pl":  0.20},
    {"symbol": "MSFT",  "qty": 2, "avg_entry_price": 397.46, "current_price": 396.55, "unrealized_pl": -1.81},
    {"symbol": "TSLA",  "qty": 1, "avg_entry_price": 400.36, "current_price": 402.86, "unrealized_pl":  2.50},
]

TRADES = [
    {"symbol": "AAPL",  "side": "buy", "qty": 3, "price": 264.73, "pnl": None, "reason": ""},
    {"symbol": "MSFT",  "side": "buy", "qty": 2, "price": 399.26, "pnl": None, "reason": ""},
    {"symbol": "GOOGL", "side": "buy", "qty": 2, "price": 305.60, "pnl": None, "reason": ""},
    {"symbol": "AMZN",  "side": "buy", "qty": 4, "price": 207.35, "pnl": None, "reason": ""},
    {"symbol": "NVDA",  "side": "buy", "qty": 4, "price": 181.03, "pnl": None, "reason": ""},
    {"symbol": "TSLA",  "side": "buy", "qty": 1, "price": 402.62, "pnl": None, "reason": ""},
    {"symbol": "META",  "side": "buy", "qty": 1, "price": 654.65, "pnl": None, "reason": ""},
]

# ---------------------------------------------------------------------------
# Test: send two reports (simulating two accounts for the same user)
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {"account_name": "Main Trading", "user_name": "Alice Johnson"},
    {"account_name": "Aggressive Growth", "user_name": "Alice Johnson"},
]

# Ensure output dir exists
report_dir = project_root / "tests" / "reports"
report_dir.mkdir(parents=True, exist_ok=True)


def build_report_html(date, pnl, positions, trades, cumulative_pnl, win_rate,
                      account_name="", user_name=""):
    """
    Re-create the same HTML that send_daily_pnl_report builds, so we can
    save it locally for inspection without needing to open the email.
    """
    pnl_color = "#28a745" if pnl >= 0 else "#dc3545"
    pnl_sign = "+" if pnl >= 0 else ""

    positions_rows = ""
    for p in positions:
        sym = p.get("symbol", "")
        qty = p.get("qty", 0)
        entry = float(p.get("avg_entry_price", 0))
        current = float(p.get("current_price", 0))
        unrealized = float(p.get("unrealized_pl", 0))
        ucolor = "#28a745" if unrealized >= 0 else "#dc3545"
        positions_rows += (
            f"<tr><td>{sym}</td><td>{qty}</td><td>${entry:.2f}</td>"
            f"<td>${current:.2f}</td>"
            f"<td style='color:{ucolor}'>${unrealized:+.2f}</td></tr>\n"
        )
    if not positions_rows:
        positions_rows = "<tr><td colspan='5'>No open positions</td></tr>"

    trades_rows = ""
    for t in trades:
        sym = t.get("symbol", "")
        side = t.get("side", "")
        qty = t.get("qty", 0)
        price = float(t.get("price", t.get("entry_price", 0)))
        reason = t.get("reason", "")
        trade_pnl = t.get("pnl")
        pnl_cell = f"${float(trade_pnl):.2f}" if trade_pnl is not None else "-"
        trades_rows += (
            f"<tr><td>{sym}</td><td>{side}</td><td>{qty}</td>"
            f"<td>${price:.2f}</td><td>{pnl_cell}</td><td>{reason}</td></tr>\n"
        )
    if not trades_rows:
        trades_rows = "<tr><td colspan='6'>No trades today</td></tr>"

    # Account/user header
    account_header = ""
    if account_name or user_name:
        parts = []
        if account_name:
            parts.append(f"<strong>Account:</strong> {account_name}")
        if user_name:
            parts.append(f"<strong>User:</strong> {user_name}")
        account_header = (
            '<div style="background: #e3f2fd; padding: 12px 16px; border-radius: 8px; '
            'margin-bottom: 16px; border-left: 4px solid #1976d2;">'
            + " &nbsp;|&nbsp; ".join(parts)
            + "</div>"
        )

    return f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #333;">AlpaTrade Daily Report</h2>
      {account_header}
      <p><strong>Date:</strong> {date}</p>

      <div style="background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 16px 0;">
        <h3 style="margin-top:0;">Daily P&amp;L:
          <span style="color:{pnl_color}">{pnl_sign}${abs(pnl):.2f}</span>
        </h3>
        <p>Cumulative P&amp;L: <strong>${cumulative_pnl:+.2f}</strong></p>
        <p>Win Rate: <strong>{win_rate:.1f}%</strong></p>
      </div>

      <h3>Current Positions</h3>
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <tr style="background:#e9ecef;">
          <th style="padding:8px; text-align:left;">Symbol</th>
          <th style="padding:8px;">Qty</th>
          <th style="padding:8px;">Entry</th>
          <th style="padding:8px;">Current</th>
          <th style="padding:8px;">Unrealized</th>
        </tr>
        {positions_rows}
      </table>

      <h3>Trades Today</h3>
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <tr style="background:#e9ecef;">
          <th style="padding:8px; text-align:left;">Symbol</th>
          <th style="padding:8px;">Side</th>
          <th style="padding:8px;">Qty</th>
          <th style="padding:8px;">Price</th>
          <th style="padding:8px;">P&amp;L</th>
          <th style="padding:8px;">Reason</th>
        </tr>
        {trades_rows}
      </table>

      <hr style="margin-top:24px; border:none; border-top:1px solid #dee2e6;">
      <p style="color:#6c757d; font-size:12px;">
        Generated by AlpaTrade Multi-Agent Trading System
      </p>
    </div>
    """


if __name__ == "__main__":
    print("=" * 60)
    print("AlpaTrade — Test Email Report with Account Grouping")
    print("=" * 60)

    for i, acct in enumerate(ACCOUNTS, 1):
        account_name = acct["account_name"]
        user_name = acct["user_name"]
        pnl = 23.34 if i == 1 else -8.12  # different P&L per account
        cumulative = 23.34 if i == 1 else 15.22
        win_rate = 100.0 if i == 1 else 60.0

        print(f"\n--- Account {i}: {account_name} ---")

        # 1. Save HTML report locally
        html = build_report_html(
            date=DATE, pnl=pnl, positions=POSITIONS, trades=TRADES,
            cumulative_pnl=cumulative, win_rate=win_rate,
            account_name=account_name, user_name=user_name,
        )
        slug = account_name.lower().replace(" ", "_")
        report_path = report_dir / f"report_{slug}_{DATE}.html"
        report_path.write_text(html, encoding="utf-8")
        print(f"  [OK] Report saved: {report_path}")

        # 2. Send real email via Postmark
        print(f"  Sending email to {os.getenv('TO_EMAIL', '(not set)')}...")
        ok = send_daily_pnl_report(
            date=DATE, pnl=pnl, positions=POSITIONS, trades=TRADES,
            cumulative_pnl=cumulative, win_rate=win_rate,
            account_name=account_name, user_name=user_name,
        )
        if ok:
            print(f"  [OK] Email sent successfully!")
        else:
            print(f"  [FAIL] Email failed (check env vars / Postmark key)")

    print(f"\n{'=' * 60}")
    print(f"Reports saved to: {report_dir}")
    print(f"{'=' * 60}")
