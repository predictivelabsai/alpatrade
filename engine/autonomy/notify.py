"""Notifier — push autonomy digests (promotion candidates, run summaries).

``format_digest`` is pure/testable HTML; ``send_promotion_digest`` delivers it via the
repo's Postmark util and, if configured, a Hermes channel. All sends are best-effort.
"""
from __future__ import annotations

import os
from typing import Optional


def format_digest(promotions: list[dict], title: str = "AlpaTrade — paper→live candidates") -> str:
    """Render promotion candidates as an HTML digest (pure)."""
    if not promotions:
        body = "<p>No new promotion candidates this run.</p>"
    else:
        rows = []
        for p in promotions:
            ev = p.get("evidence", {})
            rows.append(
                f"<tr><td>{p.get('strategy_slug','?')}</td><td>{p.get('symbol','')}</td>"
                f"<td>{ev.get('sharpe',0):.2f}</td><td>{ev.get('return_pct',0):.2f}%</td>"
                f"<td>{ev.get('max_drawdown_pct',0):.2f}%</td><td>{ev.get('trades',0)}</td></tr>"
            )
        body = (
            "<table border='1' cellpadding='6' style='border-collapse:collapse'>"
            "<thead><tr><th>Strategy</th><th>Symbol</th><th>Sharpe</th>"
            "<th>Return</th><th>Max DD</th><th>Trades</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    return (
        f"<div style='font-family:Inter,Arial,sans-serif;color:#14231B'>"
        f"<h2>{title}</h2>{body}"
        "<p style='color:#7A867E;font-size:12px'>Paper-verified candidates only. Not financial "
        "advice; AlpaTrade holds no funds and places no live orders — promotion is your decision.</p>"
        "</div>"
    )


def send_promotion_digest(promotions: list[dict], to: Optional[str] = None) -> bool:
    """Email the digest (Postmark) and mirror to Hermes if configured. Best-effort."""
    html = format_digest(promotions)
    sent = False
    to = to or os.getenv("TO_EMAIL")
    if to:
        try:
            from utils.email_util import send_email_to
            sent = bool(send_email_to(to, "AlpaTrade — promotion candidates", html))
        except Exception:  # noqa: BLE001
            sent = False
    if os.getenv("HERMES_WEBHOOK_URL"):
        try:
            from engine.agents.runtime.hermes_rt import HermesRuntime
            HermesRuntime().notify(f"{len(promotions)} paper→live candidate(s) this run.")
        except Exception:  # noqa: BLE001
            pass
    return sent
