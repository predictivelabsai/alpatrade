"""Admin-only public-market ingestion freshness and completeness monitor."""
from __future__ import annotations

import html

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web import ph_layout
from engine.web.ph_layout import page

_CSS = """
.data-health{max-width:1120px;width:100%;margin:auto;padding:0 1rem 3rem}.data-health h1{font-size:1.35rem;margin:.4rem 0}
.data-health .sub{color:var(--ink-muted);font-size:.85rem;margin:0 0 1rem}.health-summary{display:flex;gap:.55rem;flex-wrap:wrap;margin:1rem 0}
.health-chip{border-radius:999px;padding:.35rem .6rem;font-size:.78rem;background:var(--bg-raise);border:1px solid var(--line)}
.health-chip.healthy{color:#176441}.health-chip.warning{color:#775a00}.health-chip.critical{color:#9b302b}
.health-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:.65rem;background:#fff}
.data-health table{border-collapse:collapse;width:100%;font-size:.83rem}.data-health th,.data-health td{padding:.7rem;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
.data-health thead{background:var(--bg-raise)}.status{font-size:.72rem;border-radius:999px;padding:.25rem .5rem;white-space:nowrap}.status.healthy{background:#dcefe5;color:#176441}.status.warning{background:#fff0c8;color:#775a00}.status.critical{background:#f8dedb;color:#9b302b}.gaps{margin:0;padding-left:1rem}.muted{color:var(--ink-muted)}
@media(max-width:600px){.data-health{padding-left:.75rem;padding-right:.75rem}.health-scroll table{min-width:44rem}.data-health th,.data-health td{padding:.55rem}.health-chip{min-height:28px}}
"""


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(str(uid))
    except Exception:  # noqa: BLE001
        return None


def _age(value):
    if value is None:
        return "No timestamp"
    if value < 1:
        return f"{max(1, round(value * 60))}m ago"
    return f"{value:.1f}h ago"


def _render(rows: list[dict], workers: list[dict] | None = None) -> str:
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("healthy", "warning", "critical")}
    summary = "".join(f"<span class='health-chip {status}'>{count} {status}</span>"
                      for status, count in counts.items())
    body = []
    for row in rows:
        gaps = row.get("gaps", [])
        gap_html = "<br>".join(
            f"{html.escape(gap['label'])}: {gap['count']:,} missing" for gap in gaps) or "—"
        updated = row.get("last_updated")
        updated_text = updated.isoformat(timespec="minutes") if updated else "—"
        error = f"<br><span class='muted'>{html.escape(row['error'])}</span>" if row.get("error") else ""
        body.append(
            f"<tr><td><strong>{html.escape(row['label'])}</strong>{error}</td>"
            f"<td><span class='status {row['status']}'>{row['status']}</span></td>"
            f"<td>{row['total']:,}</td><td>{html.escape(updated_text)}<br><span class='muted'>{_age(row.get('age_hours'))}</span></td>"
            f"<td>{row['max_age_hours']}h</td><td>{gap_html}</td></tr>")
    worker_rows = []
    for worker in workers or []:
        cycle = worker.get("last_successful_cycle")
        cycle = cycle.isoformat(timespec="minutes") if cycle else "â€”"
        pct = worker.get("completion_percentage")
        worker_rows.append(
            f"<tr><td>{html.escape(str(worker.get('mode','â€”')))}</td><td>{html.escape(str(worker.get('status','â€”')))}</td>"
            f"<td>{worker.get('last_processed_news_id') or 'â€”'}</td><td>{worker.get('last_inserted_news_id') or 'â€”'}</td>"
            f"<td>{worker.get('processed_count',0)}</td><td>{worker.get('failed_count',0)}</td>"
            f"<td>{worker.get('remaining_incomplete_rows','â€”')}</td><td>{pct if pct is not None else 'â€”'}%</td>"
            f"<td>{cycle}</td><td>{html.escape(str(worker.get('last_error') or 'â€”'))}</td></tr>")
    worker_table = ("<h2>News worker</h2><div class='health-scroll'><table><thead><tr><th>Mode</th><th>Status</th>"
                    "<th>Last processed</th><th>Last inserted</th><th>Processed</th><th>Failed</th><th>Remaining</th>"
                    "<th>Complete</th><th>Last cycle</th><th>Latest error</th></tr></thead><tbody>" +
                    ("".join(worker_rows) or "<tr><td colspan='10'>No worker checkpoint yet.</td></tr>") + "</tbody></table></div>")
    return f"""
      <h1>Data health</h1><p class='sub'>Read-only ingestion signals from the source tables. Freshness uses the feed’s own update timestamp; gaps count required fields before UI enrichment.</p>
      <div class='health-summary'>{summary}</div><div class='health-scroll'><table><thead><tr><th>Source</th><th>Status</th><th>Rows</th><th>Last source update</th><th>SLO</th><th>Field gaps</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>{worker_table}
    """


def register(app, rt):
    entry = ("Data health", "/monitoring/data-health", "data-health")
    if entry not in ph_layout.MONITORING_PAGES:
        ph_layout.MONITORING_PAGES.append(entry)

    @rt("/monitoring/data-health", methods=["GET"])
    def data_health_get(session):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        if not user.get("is_admin"):
            return RedirectResponse("/dashboard", status_code=303)
        from engine.publicmarkets.observability import data_health_snapshot, news_worker_snapshot
        return page("data-health", Style(_CSS), Div(NotStr(_render(data_health_snapshot(), news_worker_snapshot())), cls="data-health"),
                    user=user, title="Data Health · AlpaTrade", right_news=False)

    return ["/monitoring/data-health"]
