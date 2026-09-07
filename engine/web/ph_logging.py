"""Owner/admin activity history at ``/admin/logging``."""
from __future__ import annotations

import json

from fasthtml.common import (
    A, Div, Form, H1, H2, Input, P, Span, Style, Table, Tbody, Td, Th,
    Thead, Tr,
)
from starlette.responses import RedirectResponse

from engine.web.ph_auth import current_user
from engine.web.ph_layout import page

_CSS = """
.logging{padding:1.5rem;max-width:1500px;margin:0 auto}.logging-head{display:flex;
justify-content:space-between;gap:1rem;align-items:flex-end;flex-wrap:wrap}
.logging h1{margin:0}.logging .muted{color:var(--ink-muted);font-size:.82rem}
.log-filter{display:flex;gap:.5rem;align-items:center}.log-filter input{max-width:280px}
.log-card{background:var(--paper);border:1px solid var(--line);border-radius:12px;
padding:1rem;margin-top:1rem;overflow:auto}.log-table{width:100%;font-size:.76rem;
border-collapse:collapse}.log-table th,.log-table td{padding:.55rem;border-bottom:1px solid
var(--line);vertical-align:top;text-align:left}.log-table th{font-size:.66rem;
text-transform:uppercase;letter-spacing:.05em}.log-text{max-width:420px;white-space:pre-wrap;
overflow-wrap:anywhere}.log-status{font:650 .68rem var(--font-mono);padding:.16rem .4rem;
border-radius:999px;background:var(--bg-raise)}.log-error{color:#b4472f}
@media(max-width:760px){.logging{padding:.8rem}.log-card{padding:.5rem}}
"""


def _time(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(value, "strftime") else "—"


def _short(value, limit: int = 500) -> str:
    text = str(value or "—")
    return text if len(text) <= limit else text[:limit] + "…"


def _user_table(items: list[dict]):
    rows = []
    for item in items:
        rows.append(Tr(
            Td(_time(item.get("created_at"))),
            Td(item.get("email") or "—"),
            Td(item.get("agent_framework") or "pending"),
            Td(Span(item.get("status") or "—", cls="log-status")),
            Td(_short(item.get("request_text")), cls="log-text"),
            Td(_short(item.get("response_text")), cls="log-text"),
            Td(_short(item.get("error")), cls="log-text log-error"),
        ))
    if not rows:
        rows.append(Tr(Td("No user activity has been recorded yet.", colspan="7")))
    return Table(
        Thead(Tr(*[Th(label) for label in (
            "Time", "User", "Agent", "Status", "Question", "Response", "Error",
        )])), Tbody(*rows), cls="log-table",
    )


def _agent_table(items: list[dict]):
    rows = []
    for item in items:
        details = json.dumps(item.get("details") or {}, default=str, ensure_ascii=False)
        rows.append(Tr(
            Td(_time(item.get("updated_at"))),
            Td(item.get("email") or "Legacy/unowned"),
            Td(item.get("agent_framework") or "—"),
            Td(item.get("operation_type") or "—"),
            Td(Span(item.get("status") or "—", cls="log-status")),
            Td(_short(item.get("job_id"), 80), cls="log-text"),
            Td(_short(item.get("run_id"), 80), cls="log-text"),
            Td(_short(details), cls="log-text"),
            Td(_short(item.get("error")), cls="log-text log-error"),
        ))
    if not rows:
        rows.append(Tr(Td("No agent jobs have been recorded yet.", colspan="9")))
    return Table(
        Thead(Tr(*[Th(label) for label in (
            "Updated", "User", "Agent", "Operation", "Status", "Job", "Run",
            "Details", "Error",
        )])), Tbody(*rows), cls="log-table",
    )


def _logging_page(user: dict, *, email: str = ""):
    from engine.ai.activity_logging import list_agent_logs, list_user_logs

    is_admin = bool(user.get("is_admin"))
    user_logs = list_user_logs(
        str(user["user_id"]), is_admin=is_admin, email=email, limit=100,
    )
    agent_logs = list_agent_logs(
        str(user["user_id"]), is_admin=is_admin, email=email, limit=100,
    )
    filter_form = (
        Form(
            Input(type="search", name="email", value=email,
                  placeholder="Filter by user email", aria_label="Filter by user email"),
            Input(type="submit", value="Filter"),
            A("Clear", href="/admin/logging"),
            method="get", action="/admin/logging", cls="log-filter",
        ) if is_admin else None
    )
    scope = (
        "Administrator view: activity for all users."
        if is_admin else "Private view: only activity owned by your account."
    )
    body = Div(
        Div(
            Div(H1("Admin / Logging"), P(scope, cls="muted")),
            filter_form,
            cls="logging-head",
        ),
        Div(H2(f"User activity ({len(user_logs)})"),
            P("Questions and responses are redacted and capped in size.", cls="muted"),
            _user_table(user_logs), cls="log-card"),
        Div(H2(f"Agent activity ({len(agent_logs)})"),
            P("Backtests, paper runs, Hermes jobs, and autonomy jobs mirrored from durable state.",
              cls="muted"),
            _agent_table(agent_logs), cls="log-card"),
        cls="logging",
    )
    return page("logging", Style(_CSS), body, user=user,
                title="Admin / Logging · AlpaTrade", right_news=False)


def register(app, rt):
    @rt("/admin/logging", methods=["GET"])
    def logging_get(session, email: str = ""):
        user = current_user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        return _logging_page(user, email=email)
