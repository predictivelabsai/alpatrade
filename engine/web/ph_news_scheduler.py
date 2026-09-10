"""Read-only News Scheduler operations dashboard."""
from __future__ import annotations

from fasthtml.common import A, Div, H1, H2, P, Span, Strong, Style, Table, Tbody, Td, Th, Thead, Tr
from sqlalchemy import text
from starlette.responses import RedirectResponse

from engine.db.pool import DatabasePool
from engine.web.ph_auth import current_user
from engine.web.ph_layout import page

_CSS = """
.ns{padding:1.5rem;max-width:1450px;margin:auto}.ns h1{margin:0}.sub{color:var(--ink-muted);
font-size:.84rem}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:.7rem;
margin:1rem 0}.card,.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px;
padding:1rem}.card strong{display:block;font-size:1.12rem;margin-top:.3rem}.grid{display:grid;
grid-template-columns:1fr 1fr;gap:1rem}.panel{margin-bottom:1rem;overflow:auto}.ns table{width:100%;
border-collapse:collapse;font-size:.78rem}.ns th,.ns td{padding:.48rem;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}.ns th{text-transform:uppercase;font-size:.66rem;letter-spacing:.05em}
.badge{font:650 .68rem var(--font-mono);padding:.15rem .4rem;border-radius:999px;background:var(--bg-raise)}
.bar{display:flex;align-items:center;gap:.5rem;margin:.38rem 0}.bar-track{height:.55rem;background:var(--bg-raise);
border-radius:5px;flex:1;overflow:hidden}.bar-fill{height:100%;background:var(--accent)}.reason{min-width:260px;
max-width:430px}.ok{color:var(--accent)}.bad{color:#b4472f}@media(max-width:800px){.grid{grid-template-columns:1fr}.ns{padding:.8rem}}
"""


def _load_dashboard() -> dict:
    with DatabasePool().engine.connect() as conn:
        jobs = [dict(row) for row in conn.execute(text(
            "SELECT * FROM alpatrade.news_worker_jobs ORDER BY updated_at DESC LIMIT 8"
        )).mappings()]
        latest = [dict(row) for row in conn.execute(text("""
            SELECT id, published_date, company, COALESCE(ticker,yf_ticker) ticker,
                   publisher, event, predicted_side, predicted_move, reason, title_en, link
            FROM public.news
            WHERE title_en IS NOT NULL AND company IS NOT NULL
              AND predicted_side IN ('UP','DOWN','NEUTRAL') AND predicted_move IS NOT NULL
            ORDER BY id DESC LIMIT 5
        """)).mappings()]
        sides = [dict(row) for row in conn.execute(text("""
            SELECT predicted_side label, count(*) count FROM public.news
            WHERE predicted_side IN ('UP','DOWN','NEUTRAL')
            GROUP BY predicted_side ORDER BY count(*) DESC
        """)).mappings()]
        events = [dict(row) for row in conn.execute(text("""
            SELECT COALESCE(event,'Unknown') label, count(*) count FROM public.news
            WHERE predicted_side IN ('UP','DOWN','NEUTRAL')
            GROUP BY event ORDER BY count(*) DESC LIMIT 8
        """)).mappings()]
        try:
            activity = [dict(row) for row in conn.execute(text("""
                SELECT created_at, event_name, status, news_id, publisher, details
                FROM alpatrade.news_worker_events ORDER BY created_at DESC LIMIT 40
            """)).mappings()]
        except Exception:
            activity = []
    return {"jobs": jobs, "latest": latest, "sides": sides, "events": events,
            "activity": activity}


def _bars(items: list[dict]):
    maximum = max([int(item["count"]) for item in items] or [1])
    return Div(*[Div(Span(str(item["label"]), style="width:9rem"),
                         Div(Div(cls="bar-fill", style=f"width:{100 * int(item['count']) / maximum:.1f}%"),
                             cls="bar-track"), Span(str(item["count"])), cls="bar") for item in items])


def _dashboard(user: dict):
    try:
        data = _load_dashboard()
        error = None
    except Exception as exc:  # DB/schema rollout should produce a useful page, not a 500
        data = {"jobs": [], "latest": [], "sides": [], "events": [], "activity": []}
        error = type(exc).__name__
    jobs = data["jobs"]
    current = jobs[0] if jobs else {}
    status = current.get("status") or "not configured"
    latest_id = current.get("last_inserted_news_id") or "—"
    cards = Div(
        Div(Span("Worker status", cls="sub"), Span(status, cls=f"badge {'ok' if status == 'running' else 'bad'}"), cls="card"),
        Div(Span("Mode", cls="sub"), Strong(current.get("job_name") or "—"), cls="card"),
        Div(Span("Last inserted news ID", cls="sub"), Strong(str(latest_id)), cls="card"),
        Div(Span("Processed / failed", cls="sub"), Strong(f"{current.get('processed_count', 0)} / {current.get('failed_count', 0)}"), cls="card"),
        Div(Span("Last successful cycle", cls="sub"), Strong(str(current.get("last_successful_cycle") or "—")[:19]), cls="card"),
        cls="cards",
    )
    latest_rows = [Tr(Td(row.get("id")), Td(str(row.get("published_date") or "")[:19]),
                      Td(row.get("company") or "—"), Td(row.get("ticker") or "—"),
                      Td(row.get("publisher") or "—"), Td(row.get("event") or "—"),
                      Td(row.get("title_en") or "—"),
                      Td(Span(row.get("predicted_side") or "—", cls="badge")),
                      Td(f"{float(row['predicted_move']):+.2f}%"),
                      Td(row.get("reason") or "—", cls="reason"),
                      Td(A("Open", href=row.get("link"), target="_blank") if row.get("link") else "—"))
                   for row in data["latest"]]
    activity_rows = [Tr(Td(str(row.get("created_at") or "")[:19]), Td(row.get("event_name")),
                        Td(Span(row.get("status"), cls="badge")), Td(row.get("news_id") or "—"),
                        Td(row.get("publisher") or "—"), Td(str(row.get("details") or {})))
                     for row in data["activity"]]
    body = Div(H1("News Scheduler"),
        P("Realtime Finespresso ingestion, event-specific ML prediction and XAI reasoning. This page is read-only.", cls="sub"),
        P(f"Dashboard unavailable ({error}). Apply sql/31_news_worker_jobs.sql and sql/32_news_worker_events.sql." if error else "", cls="bad"),
        cards,
        Div(Div(H2("Prediction sides"), _bars(data["sides"]), cls="panel"),
            Div(H2("Top events"), _bars(data["events"]), cls="panel"), cls="grid"),
        Div(H2("Latest 5 fully enriched articles"), Table(Thead(Tr(*[Th(x) for x in
            ("ID", "Published", "Company", "Ticker", "Publisher", "Event", "English headline", "Side", "Move", "XAI reason", "Source")])),
            Tbody(*(latest_rows or [Tr(Td("No fully enriched news rows found.", colspan="11"))]))), cls="panel"),
        Div(H2("Worker activity"), P("Durable sanitized events; article content and credentials are never logged.", cls="sub"),
            Table(Thead(Tr(*[Th(x) for x in ("Time", "Event", "Status", "News ID", "Publisher", "Details")])),
                  Tbody(*(activity_rows or [Tr(Td("No events yet. Run migration 32, then allow one worker cycle.", colspan="6"))]))), cls="panel"), cls="ns")
    return page("news-scheduler", Style(_CSS), body, user=user, title="News Scheduler · AlpaTrade", right_news=False)


def register(app, rt):
    from engine.web import ph_layout
    entry = ("News Scheduler", "/research/news-scheduler", "news-scheduler")
    if entry not in ph_layout.RESEARCH_PAGES:
        ph_layout.RESEARCH_PAGES.append(entry)

    @rt("/research/news-scheduler", methods=["GET"])
    def news_scheduler_get(session):
        user = current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        return _dashboard(user)

    return ["/research/news-scheduler"]
