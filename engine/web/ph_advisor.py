"""Daily advisor digest — the post-close advisor report, in-product (``/advisor``).

The advisor engine (:mod:`engine.reporting.advisor`) already generates one
severity-classified report per linked paper account per NYSE session and
emails a consolidated digest; this page is the in-product surface for the
same stored ``advisor_reports`` rows. Read-only: one section per account for
the selected session, a session-history rail, and "Test in chat" deep links
built from a recommendation's ``test_config``. The page never mutates a
report, enqueues a run, or bypasses the explicit-approval gate.
"""
from __future__ import annotations

import html
from datetime import date as _date

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web import onboarding
from engine.web.ph_layout import page

_CSS = """
.advisor{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}
.advisor-head{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin:.4rem 0 1rem}
.advisor h1{font-size:1.35rem;margin:0}
.advisor-head .muted{display:block;color:var(--ink-muted);font-size:.8rem}
.advisor-dates{display:flex;margin-left:auto;flex-wrap:wrap;gap:0}
.advisor-dates a{border:1px solid var(--line);border-left:none;background:var(--bg-elev);
 color:var(--ink-muted);text-decoration:none;padding:.48rem .7rem;font-size:.76rem;
 font-family:var(--font-mono)}
.advisor-dates a:first-child{border-radius:.45rem 0 0 .45rem;border-left:1px solid var(--line)}
.advisor-dates a:last-child{border-radius:0 .45rem .45rem 0}
.advisor-dates a.active{background:var(--accent);color:var(--bg-elev);border-color:var(--accent)}
.advisor-grid{display:grid;grid-template-columns:minmax(0,1fr) 15rem;gap:1.2rem;align-items:start}
@media(max-width:900px){.advisor-grid{grid-template-columns:minmax(0,1fr)}}
.advisor-section{background:var(--bg-elev);border:1px solid var(--line);border-left:4px solid
 #6f7b74;border-radius:.65rem;padding:1rem 1.1rem;margin-bottom:1rem}
.advisor-section.review,.advisor-section.urgent{border-left-color:#b43b35}
.advisor-section.monitor{border-left-color:#c4902f}
.advisor-section.insufficient_data{border-left-color:var(--line-br)}
.advisor-meta{color:var(--ink-muted);font-size:.75rem;display:flex;gap:.5rem;
 align-items:center;flex-wrap:wrap}
.advisor h2{font-size:1.02rem;margin:.45rem 0 .3rem}
.advisor .ai-copy{color:var(--ink);font-size:.86rem;margin:.3rem 0 .7rem}
.advisor .sev{font-family:var(--font-mono);font-size:.64rem;text-transform:uppercase;
 letter-spacing:.08em;border:1px solid var(--line-br);border-radius:.9rem;
 padding:.1rem .5rem;color:var(--ink-muted)}
.advisor .sev.urgent,.advisor .sev.review{border-color:#b43b35;color:#b43b35}
.advisor .sev.monitor{border-color:#c4902f;color:#c4902f}
.advisor .sev.completed{border-color:var(--accent);color:var(--accent)}
.advisor .sev.partial,.advisor .sev.failed{border-color:#b43b35;color:#b43b35}
.advisor h3{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;
 color:var(--ink-dim);margin:.9rem 0 .3rem}
.advisor ul{padding-left:1.1rem;margin:.3rem 0}
.advisor li{font-size:.82rem;margin:.3rem 0}
.advisor-rec{border:1px solid var(--line);border-radius:.5rem;padding:.6rem .75rem;
 margin:.45rem 0;background:var(--bg)}
.advisor-rec .rec-title{font-weight:650;font-size:.84rem}
.advisor-rec .rec-kind{font-family:var(--font-mono);font-size:.64rem;text-transform:uppercase;
 letter-spacing:.08em;border:1px solid var(--line-br);border-radius:.9rem;
 padding:.1rem .5rem;color:var(--ink-muted);margin-right:.45rem}
.advisor-rec p{margin:.35rem 0 0;font-size:.8rem;color:var(--ink-muted)}
.advisor-params{font-family:var(--font-mono);font-size:.72rem;color:var(--ink);
 margin-top:.4rem;overflow-wrap:anywhere}
.advisor-cta{display:inline-block;background:var(--accent);color:var(--bg-elev);
 text-decoration:none;border-radius:.4rem;padding:.38rem .65rem;font-size:.72rem;
 font-weight:650;margin-top:.5rem}
.advisor-cta:hover{background:var(--accent-deep);text-decoration:none}
.advisor .warn{color:#c4902f;font-size:.78rem}
.advisor .note{color:var(--ink-muted);font-size:.72rem;margin:.5rem 0 0}
.advisor .disclaimer{color:var(--ink-dim);font-size:.7rem;margin-top:.8rem;
 border-top:1px solid var(--line);padding-top:.5rem}
.advisor .metrics{display:flex;gap:1.2rem;flex-wrap:wrap;margin:.4rem 0 .2rem}
.advisor .metrics span{font-size:.72rem;color:var(--ink-muted)}
.advisor .metrics b{font-family:var(--font-mono);font-size:.78rem;color:var(--ink);
 font-variant-numeric:tabular-nums;margin-left:.3rem}
.advisor .ret-pos{color:#147a4b;font-weight:650}.advisor .ret-neg{color:#b43b35;font-weight:650}
.rail{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;
 padding:.7rem .8rem;font-size:.76rem}
.rail h3{margin-top:.1rem}
.rail ul{list-style:none;padding:0;margin:0}
.rail li{display:flex;align-items:center;gap:.45rem;margin:.3rem 0}
.rail a{color:var(--ink-muted);text-decoration:none;font-family:var(--font-mono);
 font-size:.74rem}
.rail a:hover,.rail a.active{color:var(--accent)}
.rail .dot{width:.5rem;height:.5rem;border-radius:50%;background:var(--line-br);flex:none}
.rail .dot.review,.rail .dot.urgent{background:#b43b35}
.rail .dot.monitor{background:#c4902f}
.advisor .empty{background:var(--bg-elev);border:1px solid var(--line);
 border-radius:.65rem;padding:2.2rem 1.4rem;text-align:center}
.advisor .empty p{color:var(--ink-muted);font-size:.88rem}
"""

_RAIL_LIMIT = 30
_SECTION_CAP = 4

_RAIL_SQL = """
    SELECT report_id, account_id, session_date, status, severity
    FROM alpatrade.advisor_reports
    WHERE user_id = CAST(:uid AS UUID)
    ORDER BY session_date DESC, created_at DESC
    LIMIT :limit
"""

_FALLBACK_DISCLAIMER = (
    "Paper trading is simulated; every action requires approval."
)

_EMPTY = (
    "<p>No post-close daily advisor report has been generated for your paper "
    "accounts yet.</p><p>Reports appear after the NYSE session close plus 15 "
    "minutes once a paper run exists — see the <a href='/dashboard'>Start "
    "Here</a> card or the <a href='/backtests'>backtests list</a>.</p>"
)


def _rail(user_id: str) -> list[dict]:
    """Light session list — scalar columns only, never the JSONB payloads."""
    from sqlalchemy import text

    from engine.db.pool import DatabasePool
    try:
        with DatabasePool().get_session() as session:
            rows = session.execute(
                text(_RAIL_SQL),
                {"uid": user_id, "limit": _RAIL_LIMIT},
            ).mappings().all()
            out = []
            for r in rows:
                row = dict(r)
                for key in ("report_id", "account_id"):
                    row[key] = str(row[key])
                row["session_date"] = str(row["session_date"])
                out.append(row)
        return out
    except Exception:  # noqa: BLE001
        return []


def _report(report_id: str, user_id: str) -> dict | None:
    """One full report, tenant-scoped; None for unknown/foreign ids."""
    try:
        from engine.reporting.advisor import get_report_for_user
        return get_report_for_user(report_id, user_id) or None
    except Exception:  # noqa: BLE001
        return None


def _resolve(
    rail: list[dict], report_id: str, date_str: str, user_id: str
) -> tuple[list[dict], str | None]:
    """Pick the session to show: explicit ?report=, then ?date=, then latest."""
    if report_id:
        single = _report(report_id, user_id)
        if single:
            return [single], str(single.get("session_date") or "")
    if date_str:
        try:
            _date.fromisoformat(date_str)
        except ValueError:
            date_str = ""
    day = date_str or (rail[0]["session_date"] if rail else "")
    rows = [r for r in rail if r["session_date"] == day][:_SECTION_CAP]
    reports = [rep for rep in (_report(r["report_id"], user_id) for r in rows) if rep]
    return reports, (day or None)


def _test_command(test_config: dict | None) -> str | None:
    """Best-effort chat command for a recommendation's backtest config.

    The chat surface (``agent:backtest strategy:… symbols:… lookback:…``)
    cannot express the advisor's full ``variations`` grid, so this is a
    starting point — the exact proposed parameters stay displayed on the page.
    """
    cfg = test_config if isinstance(test_config, dict) else {}
    strategy = str(cfg.get("strategy") or "").strip()
    if not strategy:
        return None
    cmd = f"agent:backtest strategy:{strategy}"
    symbols = ",".join(
        str(s).upper().strip() for s in (cfg.get("symbols") or [])[:25] if s
    )
    if symbols:
        cmd += f" symbols:{symbols}"
    lookback = str(cfg.get("lookback") or "").strip()
    if lookback:
        cmd += f" lookback:{lookback}"
    return cmd


def _metrics_html(evidence: dict) -> str:
    broker = evidence.get("broker") or {}
    paper = evidence.get("paper") or {}
    cells = []

    def cell(label, value):
        if value is None:
            return
        cells.append(f"<span>{label}<b>{value}</b></span>")

    equity = broker.get("equity")
    cell("Equity", f"${float(equity):,.0f}" if isinstance(equity, (int, float)) else None)
    daily = broker.get("daily_pct")
    if isinstance(daily, (int, float)):
        cls = "ret-pos" if daily >= 0 else "ret-neg"
        cells.append(
            f"<span>Day<b class='{cls}' style='margin-left:.3rem'>{daily:+.2f}%</b></span>")
    sharpe = paper.get("sharpe")
    cell("Paper Sharpe", f"{float(sharpe):.2f}" if isinstance(sharpe, (int, float)) else None)
    closed = paper.get("closed_trades")
    cell("Closed trades", str(closed) if closed is not None else None)
    return f"<div class='metrics'>{''.join(cells)}</div>" if cells else ""


def _rec_html(rec: dict) -> str:
    kind = str(rec.get("kind") or "review")
    title = html.escape(str(rec.get("title") or "Review"))
    body = rec.get("explanation") or rec.get("rationale") or ""
    params = rec.get("proposed_parameters_display")
    params_html = (
        f"<div class='advisor-params'>{html.escape(str(params))}</div>" if params else ""
    )
    cta = ""
    if kind == "backtest":
        cmd = _test_command(rec.get("test_config"))
        if cmd:
            cta = (
                f"<a class='advisor-cta' href='{onboarding.autorun_url(cmd)}'"
                " title='Opens a chat backtest with the same strategy, symbols "
                "and lookback; the exact parameter grid is shown above.'>"
                "Test in chat →</a>"
            )
    return (
        f"<div class='advisor-rec'>"
        f"<span class='rec-title'><span class='rec-kind'>{html.escape(kind)}</span>{title}</span>"
        f"<p>{html.escape(str(body))} <em>(explicit approval required)</em></p>"
        f"{params_html}{cta}</div>"
    )


def _report_section(report: dict) -> str:
    advisory = report.get("advisory") or {}
    evidence = report.get("evidence") or {}
    account = evidence.get("account") or {}
    severity = str(report.get("severity") or "insufficient_data")
    status = str(report.get("status") or "unknown")
    headline = str(advisory.get("headline") or severity.replace("_", " ").title())
    summary = str(advisory.get("summary") or report.get("narrative") or "")

    meta = [
        html.escape(str(account.get("account_name") or "Paper account")),
        f"session {html.escape(str(report.get('session_date') or ''))}",
        f"<span class='sev {html.escape(severity)}'>{html.escape(severity.replace('_', ' '))}</span>",
        f"<span class='sev {html.escape(status)}'>{html.escape(status)}</span>",
    ]
    model = " · ".join(
        str(report.get(k)) for k in ("model_provider", "model_name") if report.get(k)
    )
    if model:
        meta.append(html.escape(model))

    parts = [
        f"<article class='advisor-section {html.escape(severity)}'>",
        f"<div class='advisor-meta'>{' · '.join(meta)}</div>",
        f"<h2>{html.escape(headline)}</h2>",
        _metrics_html(evidence),
        f"<p class='ai-copy'>{html.escape(summary)}</p>" if summary else "",
    ]

    if status == "generating":
        parts.append(
            "<p class='note'>This report is still generating — it appears after "
            "the NYSE session close plus 15 minutes. Reload in a few minutes.</p>"
        )
        return "".join(parts) + "</article>"

    drivers = "".join(
        f"<li><b>{html.escape(str(item.get('title') or 'Evidence'))}:</b> "
        f"{html.escape(str(item.get('detail') or ''))}</li>"
        for item in (advisory.get("drivers") or [])
    )
    parts.append(
        "<h3>Performance drivers and evidence</h3><ul>"
        + (drivers or "<li>No detailed drivers were available.</li>")
        + "</ul>"
    )

    recs = (advisory.get("recommendations") or [])
    if recs:
        parts.append(
            "<h3>Recommended next steps</h3>"
            + "".join(_rec_html(rec) for rec in recs)
        )
        if advisory.get("why_no_change"):
            parts.append(
                "<p class='note'><b>Parameter-change guard:</b> "
                f"{html.escape(str(advisory.get('why_no_change')))}</p>"
            )
    elif advisory.get("why_no_change"):
        parts.append(
            "<h3>Recommended next step</h3><ul><li>"
            f"{html.escape(str(advisory.get('why_no_change')))}</li></ul>"
        )

    warnings = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in (advisory.get("data_warnings") or [])
    )
    if warnings:
        parts.append(f"<h3>Data-quality notes</h3><ul class='warn'>{warnings}</ul>")

    if status in {"failed", "partial"}:
        code = str(report.get("error_code") or "generation_failed")
        parts.append(
            f"<p class='warn'>Report {html.escape(status)} (error: "
            f"{html.escape(code)}) — the advisory above may be incomplete.</p>"
        )
    note_bits = []
    if advisory.get("ai_status") and advisory.get("ai_status") != "available":
        note_bits.append("AI commentary unavailable; deterministic drivers only.")
    if advisory.get("generation_note"):
        note_bits.append(str(advisory.get("generation_note")))
    if note_bits:
        parts.append(f"<p class='note'>{html.escape(' '.join(note_bits))}</p>")

    parts.append(
        f"<p class='disclaimer'>{html.escape(str(advisory.get('disclaimer') or _FALLBACK_DISCLAIMER))}</p>"
    )
    return "".join(parts) + "</article>"


def _rail_html(rail: list[dict], selected_date: str | None) -> str:
    """Session-history rail: one row per stored report, newest first."""
    items = []
    for r in rail:
        day = r["session_date"]
        active = " class='active'" if day == selected_date else ""
        dot = f"<span class='dot {html.escape(str(r.get('severity') or ''))}'></span>"
        items.append(
            f"<li>{dot}<a{active} href='/advisor?date={day}' "
            f"title='{html.escape(str(r.get('status') or ''))}'>{day}</a></li>"
        )
    return (
        "<aside class='rail'><h3>Sessions</h3><ul>"
        + "".join(items)
        + "</ul></aside>"
    )


def _date_pills(rail: list[dict], selected_date: str | None) -> str:
    days: list[str] = []
    for r in rail:
        if r["session_date"] not in days:
            days.append(r["session_date"])
    pills = "".join(
        f"<a class='{'active' if day == selected_date else ''}' "
        f"href='/advisor?date={day}'>{day}</a>"
        for day in days[:14]
    )
    return f"<div class='advisor-dates'>{pills}</div>" if pills else ""


def _render(rail: list[dict], reports: list[dict], selected_date: str | None) -> str:
    head = (
        "<div class='advisor-head'><div><h1>Daily advisor</h1>"
        "<span class='muted'>Post-close review of your paper accounts — "
        "generated after the NYSE close plus 15 minutes.</span></div>"
        f"{_date_pills(rail, selected_date)}</div>"
    )
    if not rail and not reports:
        body = f"<div class='empty'>{_EMPTY}</div>"
    else:
        sections = "".join(_report_section(r) for r in reports)
        body = f"<div class='advisor-grid'><div class='advisor-main'>{sections}</div>{_rail_html(rail, selected_date)}</div>"
    return f"<div class='advisor'>{head}{body}</div>"


def register(app, rt):
    from engine.web import ph_layout

    entry = ("Daily advisor", "/advisor", "advisor")
    if entry not in ph_layout.TRADE_PAGES:
        ph_layout.TRADE_PAGES.append(entry)

    @rt("/advisor", methods=["GET"])
    def advisor_get(session, report: str = "", date: str = ""):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        user_id = str(user_id)
        rail = _rail(user_id)
        reports, selected_date = _resolve(rail, report, date, user_id)
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(user_id)
        except Exception:  # noqa: BLE001
            user = None
        body = Div(NotStr(_render(rail, reports, selected_date)))
        return page("advisor", Style(_CSS), body, user=user,
                    title="Daily advisor · AlpaTrade", right_news=False)

    return ["/advisor"]