"""Owner/admin activity history at ``/admin/logging``."""
from __future__ import annotations

import html
import json
import re

from fasthtml.common import (
    A, Div, Form, H1, H2, Input, P, Span, Style, Table, Tbody, Td, Th,
    Thead, Tr, NotStr,
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
text-transform:uppercase;letter-spacing:.05em}.log-text{max-width:520px;white-space:pre-wrap;
overflow-wrap:anywhere}.log-response{min-width:360px;max-width:620px}.response-table{width:100%;
border-collapse:collapse;margin:.35rem 0;font-size:.74rem}.response-table th,.response-table td{
padding:.38rem .48rem;border:1px solid var(--line);white-space:normal}.response-table th{
background:var(--bg-raise);font-size:.68rem}.response-copy{white-space:normal;line-height:1.45}
.log-status{font:650 .68rem var(--font-mono);padding:.16rem .4rem;
border-radius:999px;background:var(--bg-raise)}.log-error{color:#b4472f}
@media(max-width:760px){.logging{padding:.8rem}.log-card{padding:.5rem}}
"""


def _time(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(value, "strftime") else "—"


def _short(value, limit: int = 500) -> str:
    text = str(value or "—")
    return text if len(text) <= limit else text[:limit] + "…"


_TABLE_DIVIDER = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_response(value, limit: int = 2000):
    """Render Markdown tables while escaping all user- and model-provided text."""
    lines = str(value or "—")[:limit].splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if index + 1 < len(lines) and "|" in lines[index] and _TABLE_DIVIDER.match(lines[index + 1]):
            headers = _cells(lines[index])
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_cells(lines[index]))
                index += 1
            head = "".join(f"<th>{html.escape(cell)}</th>" for cell in headers)
            body = "".join("<tr>" + "".join(
                f"<td>{html.escape(row[pos] if pos < len(row) else '')}</td>"
                for pos in range(len(headers))) + "</tr>" for row in rows)
            output.append(f'<table class="response-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')
            continue
        output.append(html.escape(lines[index]))
        index += 1
    return NotStr('<div class="response-copy">' + "<br>".join(output) + "</div>")


def _user_table(items: list[dict]):
    rows = []
    for item in items:
        rows.append(Tr(
            Td(_time(item.get("created_at"))),
            Td(item.get("email") or "—"),
            Td(item.get("agent_framework") or "pending"),
            Td(Span(item.get("status") or "—", cls="log-status")),
            Td(_short(item.get("request_text")), cls="log-text"),
            Td(_render_response(item.get("response_text")), cls="log-text log-response"),
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


def _usage_summary_table(items: list[dict]):
    rows = [Tr(
        Td(item.get("email") or "—"), Td(item.get("agent_framework") or "—"),
        Td(item.get("funding_source") or "—"), Td(str(item.get("calls") or 0)),
        Td(f"{int(item.get('total_tokens') or 0):,}"),
        Td(f"${float(item.get('estimated_cost_usd') or 0):.4f}"),
    ) for item in items]
    if not rows:
        rows.append(Tr(Td("No LLM usage has been recorded today.", colspan="6")))
    return Table(Thead(Tr(*[Th(x) for x in (
        "User", "Agent", "Key source", "Calls", "Tokens", "Est. cost today",
    )])), Tbody(*rows), cls="log-table")


def _usage_table(items: list[dict]):
    rows = [Tr(
        Td(_time(item.get("created_at"))), Td(item.get("email") or "—"),
        Td(item.get("agent_framework") or "—"), Td(item.get("provider") or "—"),
        Td(item.get("model_name") or "—"), Td(item.get("funding_source") or "—"),
        Td(f"{int(item.get('input_tokens') or 0):,}"),
        Td(f"{int(item.get('output_tokens') or 0):,}"),
        Td(f"${float(item.get('estimated_cost_usd') or 0):.4f}"),
        Td(item.get("usage_quality") or "—"),
    ) for item in items]
    if not rows:
        rows.append(Tr(Td("No LLM calls have been recorded yet.", colspan="10")))
    return Table(Thead(Tr(*[Th(x) for x in (
        "Time", "User", "Agent", "Provider", "Model", "Key source",
        "Input", "Output", "Est. cost", "Quality",
    )])), Tbody(*rows), cls="log-table")


def _logging_page(user: dict, *, email: str = ""):
    from engine.ai.activity_logging import list_agent_logs, list_user_logs
    from engine.ai.llm_usage import list_usage, usage_summary

    is_admin = bool(user.get("is_admin"))
    user_logs = list_user_logs(
        str(user["user_id"]), is_admin=is_admin, email=email, limit=100,
    )
    agent_logs = list_agent_logs(
        str(user["user_id"]), is_admin=is_admin, email=email, limit=100,
    )
    usage_logs = list_usage(str(user["user_id"]), is_admin=is_admin, email=email)
    usage_totals = usage_summary(str(user["user_id"]), is_admin=is_admin, email=email)
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
        Div(H2("LLM usage today"),
            P("Cost uses configured per-token estimates; Quality identifies measured provider tokens versus estimates.", cls="muted"),
            _usage_summary_table(usage_totals), cls="log-card"),
        Div(H2(f"LLM calls ({len(usage_logs)})"),
            P("Key source reports platform or user BYOK; credential values are never logged.", cls="muted"),
            _usage_table(usage_logs), cls="log-card"),
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
