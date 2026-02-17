"""
Email Utility — Postmark

Sends emails via the Postmark HTTP API.
Requires POSTMARK_API_KEY, TO_EMAIL, FROM_EMAIL env vars.
"""

import os
import logging
from typing import List, Dict, Any

import requests

logger = logging.getLogger(__name__)


def send_email(subject: str, body_html: str) -> bool:
    """
    Send an email via Postmark.

    Args:
        subject: Email subject line
        body_html: HTML body content

    Returns:
        True if sent successfully, False otherwise
    """
    api_key = os.getenv("POSTMARK_API_KEY")
    to_email = os.getenv("TO_EMAIL")
    from_email = os.getenv("FROM_EMAIL")

    if not all([api_key, to_email, from_email]):
        logger.warning("Postmark env vars not set (POSTMARK_API_KEY, TO_EMAIL, FROM_EMAIL)")
        return False

    try:
        resp = requests.post(
            "https://api.postmarkapp.com/email",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": api_key,
            },
            json={
                "From": from_email,
                "To": to_email,
                "Subject": subject,
                "HtmlBody": body_html,
                "MessageStream": "outbound",
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_daily_pnl_report(
    date: str,
    pnl: float,
    positions: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    cumulative_pnl: float = 0.0,
    win_rate: float = 0.0,
) -> bool:
    """
    Send a daily P&L report email.

    Args:
        date: Trading date string (YYYY-MM-DD)
        pnl: Daily P&L in dollars
        positions: List of position dicts (symbol, qty, avg_entry_price, current_price, unrealized_pl)
        trades: List of trade dicts executed today
        cumulative_pnl: Running total P&L
        win_rate: Overall win rate percentage

    Returns:
        True if sent successfully
    """
    pnl_color = "#28a745" if pnl >= 0 else "#dc3545"
    pnl_sign = "+" if pnl >= 0 else ""

    # Build positions table
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

    # Build trades table
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

    subject = f"AlpaTrade Daily Report — {date} — P&L: {pnl_sign}${abs(pnl):.2f}"

    body_html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #333;">AlpaTrade Daily Report</h2>
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

    return send_email(subject, body_html)
