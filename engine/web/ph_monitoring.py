"""Authenticated monitor and paper-only controls for the autonomy pipeline."""
from __future__ import annotations

import html
import os
from typing import Optional

from fasthtml.common import Div, NotStr, Style
from sqlalchemy import text
from starlette.responses import RedirectResponse

from engine.db.pool import DatabasePool
from engine.web import ph_layout
from engine.web.ph_layout import page

_CSS = """
.monitor{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}.monitor h1{font-size:1.35rem}
.monitor-head,.monitor-actions,.run-head,.pipeline{display:flex;align-items:center}.monitor-head{justify-content:space-between;
gap:1rem;flex-wrap:wrap}.monitor-actions{gap:.5rem;flex-wrap:wrap}.monitor button,.monitor select{border:1px solid
var(--line);background:#fff;border-radius:.45rem;padding:.5rem .75rem;color:var(--ink);cursor:pointer}.monitor .primary{
background:var(--accent);color:#fff;border-color:var(--accent)}.status-grid{display:grid;grid-template-columns:repeat(4,1fr);
gap:.7rem;margin:1rem 0}.metric,.run{background:#fff;border:1px solid var(--line);border-radius:.65rem;padding:1rem}
.metric-label{font-size:.72rem;text-transform:uppercase;color:var(--ink-muted)}.metric-value{font-size:1.25rem;
font-weight:650;margin-top:.2rem}.pipeline{gap:.25rem;flex-wrap:wrap;margin:.8rem 0}.step{font-size:.72rem;padding:.3rem .5rem;
border-radius:1rem;background:#ecece8;color:#6f756f}.step.done{background:#dcefe5;color:#176441}.step.failed{background:#f8dedb;
color:#9b302b}.run{margin:.7rem 0}.run-head{justify-content:space-between;gap:1rem}.pill{font-size:.7rem;border-radius:1rem;
padding:.25rem .5rem;background:#ecece8}.pill.running{background:#fff0c8;color:#775a00}.pill.done{background:#dcefe5;
color:#176441}.pill.failed{background:#f8dedb;color:#9b302b}.muted{font-size:.78rem;color:var(--ink-muted)}
.error{color:#9b302b}.empty{text-align:center;padding:2rem}.retry{float:right}
.funnel{background:#fff;border:1px solid var(--line);border-radius:.65rem;padding:1rem 1.2rem;margin:1rem 0}
.funnel h2{font-size:.95rem;margin:0 0 .2rem}.funnel .muted{display:block;margin-bottom:.7rem}
.fr{display:grid;grid-template-columns:10.5rem 1fr 4.2rem;gap:1rem;align-items:center;padding:.4rem 0;font-size:.84rem}
.fr .fl{color:var(--ink-muted)}
.fr .bar{height:1.15rem;border-radius:.3rem;background:var(--accent);min-width:3px;opacity:.85}
.fr .val{font-family:var(--font-mono);font-variant-numeric:tabular-nums;text-align:right}
.retention{font-size:.82rem;color:var(--ink-muted);margin-top:.7rem;border-top:1px solid var(--line);padding-top:.7rem}
.retention b{color:var(--ink)}
@media(max-width:760px){.status-grid{grid-template-columns:repeat(2,1fr)}}
"""

_NODES = ("scout", "backtest", "policy_gate", "validate_backtest",
          "paper_trade", "reconcile", "refit", "promote")


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(str(uid))
    except Exception:  # noqa: BLE001
        return {"user_id": str(uid), "email": ""}


def pipeline_snapshot(user_id: str) -> dict:
    """Return user-scoped run status without exposing other tenants' runs."""
    with DatabasePool().get_session() as session:
        rows = session.execute(text("""
            SELECT r.run_id, r.status, r.attempt, r.claimed_by, r.heartbeat_at,
                   r.error, r.created_at, r.updated_at, r.account_id,
                   (r.heartbeat_at > NOW() - INTERVAL '90 seconds') AS heartbeat_fresh,
                   COALESCE(jsonb_object_agg(s.node, s.status)
                     FILTER (WHERE s.node IS NOT NULL), '{}'::jsonb) AS steps
            FROM alpatrade.autonomy_runs r
            LEFT JOIN alpatrade.autonomy_run_steps s ON s.run_id = r.run_id
            WHERE r.user_id = :uid OR r.user_id IS NULL
            GROUP BY r.run_id
            ORDER BY r.created_at DESC LIMIT 30
        """), {"uid": user_id}).mappings().all()
        accounts = session.execute(text("""
            SELECT account_id, account_name FROM alpatrade.user_accounts
            WHERE user_id = :uid AND is_active = TRUE ORDER BY created_at ASC
        """), {"uid": user_id}).mappings().all()
    runs = [dict(row) for row in rows]
    counts = {key: sum(r["status"] == key for r in runs)
              for key in ("queued", "running", "done", "failed")}
    fresh = any(r["status"] == "running" and r["heartbeat_fresh"] for r in runs)
    return {"runs": runs, "accounts": [dict(a) for a in accounts],
            "counts": counts, "fresh_heartbeat": fresh,
            "configured": os.getenv("AUTONOMY_ENABLED", "false").lower()
            in ("1", "true", "yes", "on")}


_FUNNEL_STEPS = (
    ("registered", "Registered"),
    ("keys_connected", "Keys connected"),
    ("first_backtest", "First backtest run"),
    ("first_paper_run", "First paper run live"),
)


def _activation_html(user: Optional[dict]) -> str:
    """The Start Here activation dial — funnel + week-1 retention.

    Every number is read from alpatrade.activation_events (written at the
    true source: registration, key save, backtest completion, paper start).
    Platform-wide counts, so it renders for admins only; failures render
    nothing.
    """
    if not (user and user.get("is_admin")):
        return ""
    try:
        from engine.web import onboarding
        counts = onboarding.funnel_counts()
        w1 = onboarding.week1_cohorts(days=30)
    except Exception:  # noqa: BLE001
        return ""
    base = max(counts.get("registered", 0), 1)
    steps = []
    for event, label in _FUNNEL_STEPS:
        n = counts.get(event, 0)
        pct = int(round(100 * n / base))
        steps.append(
            f"<div class='fr'><span class='fl'>{html.escape(label)}</span>"
            f"<div class='bar' style='width:{max(pct, 1)}%'></div>"
            f"<span class='val'>{n} · {pct}%</span></div>"
        )
    w1_line = ""
    if w1 and w1.get("total"):
        w1_pct = int(round(100 * w1["returned"] / max(w1["total"], 1)))
        w1_line = (f"<div class='retention'>Week-1 retention — <b>{w1['returned']} of "
                   f"{w1['total']}</b> users registered in the last 30 days were active "
                   f"again 1–7 days after signup ({w1_pct}%). Target ≥ 20%.</div>")
    return (
        "<section class='funnel' aria-label='Activation funnel'>"
        "<h2>Activation funnel</h2>"
        "<span class='muted'>First-occurrence events per account, all time — "
        "one step per row, percent of registered.</span>"
        f"{''.join(steps)}{w1_line}</section>"
    )


def _render(data: dict, message: str = "", activation: str = "") -> str:
    counts = data["counts"]
    account_options = "".join(
        f"<option value='{html.escape(str(a['account_id']))}'>{html.escape(a['account_name'])}</option>"
        for a in data["accounts"])
    cards = "".join(
        f"<div class='metric'><div class='metric-label'>{label}</div><div class='metric-value'>{value}</div></div>"
        for label, value in (
            ("Worker config", "Enabled" if data["configured"] else "Disabled"),
            ("Active", counts["running"]), ("Queued", counts["queued"]),
            ("Fresh heartbeat", "Yes" if data["fresh_heartbeat"] else "No"),
        ))
    runs = []
    for run in data["runs"]:
        steps = run["steps"] or {}
        pipeline = "".join(
            f"<span class='step {html.escape(str(steps.get(node, '')))}'>{html.escape(node.replace('_', ' '))}</span>"
            for node in _NODES)
        heartbeat = run["heartbeat_at"].isoformat(timespec="seconds") if run["heartbeat_at"] else "not claimed"
        retry = ""
        if run["status"] == "failed":
            retry = (
                f"<form class='retry' method='post' action='/monitoring/pipeline/retry'>"
                f"<input type='hidden' name='run_id' value='{run['run_id']}'><button>Retry</button></form>")
        error = f"<div class='error'>{html.escape(str(run['error']))}</div>" if run["error"] else ""
        runs.append(
            f"<section class='run'><div class='run-head'><strong>{str(run['run_id'])[:8]}</strong>"
            f"<span class='pill {run['status']}'>{html.escape(run['status'])}</span></div>{pipeline}"
            f"<div class='muted'>attempt {run['attempt']} · worker {html.escape(run['claimed_by'] or '—')}"
            f" · heartbeat {heartbeat}</div>{error}{retry}<div style='clear:both'></div></section>")
    message_html = f"<p>{html.escape(message)}</p>" if message else ""
    empty = "<div class='run empty'>No pipeline runs for this user yet.</div>"
    return f"""
      <div class="monitor-head"><div><h1>Autonomous agent pipeline</h1>
      <div class="muted">Scout → backtest → validate → paper → reconcile → refit → promote. Paper-only.</div></div>
      <div class="monitor-actions"><form method="post" action="/monitoring/pipeline/run">
      <select name="account_id" aria-label="Paper account">{account_options}</select>
      <button class="primary" type="submit">Run pipeline now</button></form>
      <a href="/monitoring/pipeline"><button type="button">Refresh</button></a></div></div>
      {message_html}{activation}<div class="status-grid">{cards}</div>{''.join(runs) or empty}
    """


def register(app, rt):
    entry = ("⚡ Agent Pipeline", "/monitoring/pipeline", "agent-pipeline")
    if entry not in ph_layout.MONITORING_PAGES:
        ph_layout.MONITORING_PAGES.append(entry)

    @rt("/monitoring/pipeline", methods=["GET"])
    def monitoring_get(session, msg: str = ""):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        body = Div(NotStr(_render(
            pipeline_snapshot(str(user["user_id"])), msg,
            activation=_activation_html(user))), cls="monitor")
        return page("agent-pipeline", Style(_CSS), body, user=user,
                    title="Agent Pipeline · AlpaTrade", right_news=False)

    @rt("/monitoring/pipeline/run", methods=["POST"])
    async def monitoring_run(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        account_id = str(form.get("account_id") or "")
        owned = {str(a["account_id"]) for a in pipeline_snapshot(str(user["user_id"]))["accounts"]}
        if account_id not in owned:
            return RedirectResponse("/monitoring/pipeline?msg=Choose+an+owned+paper+account", status_code=303)
        from engine.autonomy import scout
        run_id = scout.enqueue_run(user_id=str(user["user_id"]), account_id=account_id)
        msg = f"Queued run {run_id[:8]}" if run_id else "Scout found no candidates"
        return RedirectResponse(f"/monitoring/pipeline?msg={msg.replace(' ', '+')}", status_code=303)

    @rt("/monitoring/pipeline/retry", methods=["POST"])
    async def monitoring_retry(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.autonomy import queue
        changed = queue.retry(str(form.get("run_id") or ""), str(user["user_id"]))
        msg = "Run queued for retry" if changed else "Run could not be retried"
        return RedirectResponse(f"/monitoring/pipeline?msg={msg.replace(' ', '+')}", status_code=303)

    return ["/monitoring/pipeline"]
