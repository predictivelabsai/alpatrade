"""
Email Utility — Postmark

Sends emails via the Postmark HTTP API.
Requires POSTMARK_API_KEY, TO_EMAIL, FROM_EMAIL env vars.
"""

import os
import logging
import html
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


def send_email_to(to_email: str, subject: str, body_html: str) -> bool:
    """
    Send an email to a specific recipient via Postmark.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        body_html: HTML body content

    Returns:
        True if sent successfully, False otherwise
    """
    api_key = os.getenv("POSTMARK_API_KEY")
    from_email = os.getenv("FROM_EMAIL")

    if not all([api_key, from_email]):
        logger.warning("Postmark env vars not set (POSTMARK_API_KEY, FROM_EMAIL)")
        return False


def send_hermes_daily_report(
    report: Dict[str, Any], *, account_name: str = "", user_name: str = "",
    to_email: str,
) -> bool:
    """Send one validated, owner-targeted Hermes paper report."""
    gain, loss, neutral = "#18864b", "#c53b3b", "#475569"

    def money(value: float) -> str:
        value = float(value or 0)
        color = gain if value > 0 else loss if value < 0 else neutral
        value_text = (f"+${value:,.2f}" if value > 0 else
                      f"-${abs(value):,.2f}" if value < 0 else "$0.00")
        return f"<span style='color:{color};font-weight:700'>{value_text}</span>"

    position_rows = ""
    for position in report.get("positions") or []:
        pnl = float(position.get("unrealized_pl") or 0)
        position_rows += (
            "<tr>"
            f"<td>{html.escape(str(position.get('symbol') or ''))}</td>"
            f"<td>{html.escape(str(position.get('qty') or 0))}</td>"
            f"<td>${float(position.get('avg_entry_price') or 0):,.2f}</td>"
            f"<td>${float(position.get('current_price') or 0):,.2f}</td>"
            f"<td>{money(pnl)}</td></tr>"
        )
    position_rows = position_rows or "<tr><td colspan='5'>No open positions</td></tr>"

    exit_rows = ""
    for trade in report.get("closed_today") or []:
        exit_rows += (
            "<tr>"
            f"<td>{html.escape(str(trade.get('symbol') or ''))}</td>"
            f"<td>{html.escape(str(trade.get('qty') or trade.get('shares') or 0))}</td>"
            f"<td>${float(trade.get('exit_price') or trade.get('price') or 0):,.2f}</td>"
            f"<td>{money(float(trade.get('pnl') or 0))}</td>"
            f"<td>{html.escape(str(trade.get('reason') or ''))}</td></tr>"
        )
    exit_rows = exit_rows or "<tr><td colspan='5'>No completed exits today</td></tr>"

    entry_rows = ""
    for group in report.get("grouped_entries") or []:
        entry_rows += (
            "<tr>"
            f"<td>{html.escape(str(group['symbol']))}</td>"
            f"<td>{html.escape(str(group['side']))}</td>"
            f"<td>{int(group['fills'])}</td><td>{float(group['quantity']):g}</td>"
            f"<td>${float(group['average_price']):,.2f}</td></tr>"
        )
    entry_rows = entry_rows or "<tr><td colspan='5'>No new entry fills today</td></tr>"

    reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in report.get("reasons") or [])
    commands = "".join(
        "<li><code style='display:inline-block;background:#f1f5f9;padding:5px'>" +
        html.escape(command) + "</code></li>" for command in report.get("commands") or []
    )
    advice_items = report.get("advice") or []
    latest_by_symbol: dict[str, dict] = {}
    for item in advice_items:
        key = str(item.get("symbol") or item.get("summary") or item.get("advice_id") or "")
        latest_by_symbol.setdefault(key, item)
    advice_rows = "".join(
        f"<li><strong>{html.escape(str(item.get('summary') or ''))}</strong> — "
        f"{html.escape(str(item.get('rationale') or ''))}</li>"
        for item in latest_by_symbol.values()
    ) or "<li>No saved Hermes advice for this reporting window.</li>"

    status = str(report.get("status") or "AMBER")
    status_color = str(report.get("status_color") or "#b7791f")
    subject_value = float(report.get("realized_today") or 0)
    subject_pnl = (f"+${subject_value:,.2f}" if subject_value > 0 else
                   f"-${abs(subject_value):,.2f}" if subject_value < 0 else "$0.00")
    subject = (
        f"Hermes Daily Paper Report — {account_name or user_name or 'Account'} — "
        f"{status} — {subject_pnl} realized"
    )
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:760px;margin:auto;color:#1e293b">
      <h2>Hermes Daily Paper Report</h2>
      <p><strong>Account:</strong> {html.escape(account_name or 'Paper account')} &nbsp;|&nbsp;
         <strong>User:</strong> {html.escape(user_name or 'Authenticated user')} &nbsp;|&nbsp;
         <strong>Date:</strong> {html.escape(str(report.get('date') or ''))}</p>
      <div style="border-left:6px solid {status_color};background:#f8fafc;padding:16px">
        <div style="font-size:20px;color:{status_color};font-weight:800">{status}</div>
        <p>{html.escape(str(report.get('decision') or ''))}</p>
        <ul>{reasons}</ul>
      </div>
      <h3>Performance</h3>
      <table style="width:100%;border-collapse:collapse">
        <tr><td>Realized P&amp;L today</td><td>{money(report.get('realized_today', 0))}</td></tr>
        <tr><td>Session realized P&amp;L</td><td>{money(report.get('realized_session', 0))}</td></tr>
        <tr><td>Account-wide current unrealized P&amp;L</td><td>{money(report.get('unrealized', 0))}</td></tr>
        <tr><td>Completed exits / wins / losses</td><td>{report.get('completed_exits', 0)} / {report.get('wins', 0)} / {report.get('losses', 0)}</td></tr>
        <tr><td>Win rate</td><td>{float(report.get('win_rate') or 0):.1f}%</td></tr>
      </table>
      <h3>Current account positions</h3>
      <p style="color:#64748b">Broker positions are account-wide and may include other paper jobs. Realized figures above are scoped to this Hermes run.</p>
      <table style="width:100%;border-collapse:collapse"><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Current</th><th>Unrealized</th></tr>{position_rows}</table>
      <h3>Completed exits today</h3>
      <table style="width:100%;border-collapse:collapse"><tr><th>Symbol</th><th>Qty</th><th>Exit</th><th>P&amp;L</th><th>Reason</th></tr>{exit_rows}</table>
      <h3>Entry fills grouped</h3>
      <table style="width:100%;border-collapse:collapse"><tr><th>Symbol</th><th>Side</th><th>Fills</th><th>Total qty</th><th>Average</th></tr>{entry_rows}</table>
      <h3>Latest Hermes assessment by symbol</h3><ul>{advice_rows}</ul>
      <h3>Recommended next commands</h3><ol>{commands}</ol>
      <p><strong>Job:</strong> {html.escape(str(report.get('job_id') or ''))}<br>
         <strong>Run:</strong> {html.escape(str(report.get('run_id') or ''))}<br>
         <strong>Candidate:</strong> {html.escape(str(report.get('candidate_id') or ''))}</p>
      <p style="color:#64748b;font-size:12px">Paper mode only. No parameters were changed automatically. Hermes advice does not submit additional orders.</p>
    </div>
    """
    return send_email_to(to_email, subject, body)

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
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_daily_pnl_report(
    date: str,
    pnl: float,
    positions: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    cumulative_pnl: float = 0.0,
    win_rate: float = 0.0,
    account_name: str = "",
    user_name: str = "",
    to_email: str = "",
    agent_advice: List[Dict[str, Any]] | None = None,
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

    advice_html = ""
    if agent_advice:
        from engine.agents.hermes_advice import advice_email_html
        advice_html = advice_email_html(agent_advice)

    acct_label = f" — {account_name}" if account_name else ""
    subject = f"AlpaTrade Daily Report{acct_label} — {date} — P&L: {pnl_sign}${abs(pnl):.2f}"

    # Build optional account/user header
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

    body_html = f"""
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

      {advice_html}

      <hr style="margin-top:24px; border:none; border-top:1px solid #dee2e6;">
      <p style="color:#6c757d; font-size:12px;">
        Generated by AlpaTrade Multi-Agent Trading System
      </p>
    </div>
    """

    return send_email_to(to_email, subject, body_html) if to_email else send_email(subject, body_html)
