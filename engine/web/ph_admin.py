"""Admin-only /admin: user analytics. Role is checked server-side (engine.rbac)."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web import ph_layout
from engine.web.ph_layout import page

_CSS = """
.adm{max-width:1120px;width:100%;margin:auto;padding:0 1rem 3rem}.adm h1{font-size:1.35rem;margin:.4rem 0}
.adm h2{font-size:1rem;margin:1.4rem 0 .5rem}.adm .sub{color:var(--ink-muted);font-size:.82rem;margin:0 0 1rem}
.adm-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.6rem}
.adm-kpi{background:#fff;border:1px solid var(--line);border-radius:.6rem;padding:.7rem .8rem}
.adm-kpi b{display:block;font-size:1.35rem}.adm-kpi span{font-size:.75rem;color:var(--ink-muted)}
.adm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.adm table{border-collapse:collapse;width:100%;font-size:.83rem;background:#fff;border:1px solid var(--line)}
.adm th,.adm td{padding:.45rem .6rem;border-bottom:1px solid var(--line);text-align:left}.adm td.n{text-align:right}
.adm-ex{overflow-x:auto}.adm-ex form{display:inline}.adm-ex .add{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0}
.adm-ex .add input{padding:.35rem .5rem;border:1px solid var(--line);border-radius:.4rem;font-size:.83rem;min-width:0;flex:1 1 140px}
.adm-ex button{padding:.35rem .7rem;border:1px solid var(--line);border-radius:.4rem;background:#fff;cursor:pointer;font-size:.8rem}
.adm{min-width:0;box-sizing:border-box}.adm-tw{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}.adm-tw table{min-width:720px}
.adm .pill{display:inline-block;padding:.08rem .45rem;border-radius:999px;font-size:.72rem;font-weight:650;background:#eef0ec}
.adm .pill.running{background:#e3f4ea;color:#147a4b}.adm .pill.paused,.adm .pill.pending_runner{background:#fff6e0;color:#8a6410}
.adm .pill.live{background:#fdeceb;color:#b43b35}.adm .tog{font-size:.82rem;margin:0 0 .5rem}
.adm-nav{margin:.2rem 0 1rem;font-size:.85rem}.adm-nav a{margin-right:.8rem}
@media(max-width:600px){.adm{padding:0 .7rem 2rem}.adm-kpis{grid-template-columns:repeat(2,1fr)}.adm-ex .add input,.adm-ex .add button{flex:1 1 100%}}
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


def stamp(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    parts = [(ZoneInfo("America/New_York"), "ET"), (ZoneInfo("Europe/London"), "UK"),
             (ZoneInfo("Europe/Tallinn"), "Tallinn")]
    return " · ".join(f"{now.astimezone(z):%Y-%m-%d %H:%M} {lbl}" for z, lbl in parts)


def _v(x):
    return "—" if x is None else f"{x:,}" if isinstance(x, int) else html.escape(str(x))


def _table(title, head, rows):
    if rows is None:
        body = f"<tr><td colspan='{len(head)}'>Unavailable</td></tr>"
    elif not rows:
        body = f"<tr><td colspan='{len(head)}'>None yet</td></tr>"
    else:
        body = "".join("<tr>" + "".join(
            f"<td class='{'n' if isinstance(c, int) else ''}'>{_v(c)}</td>" for c in r) + "</tr>" for r in rows)
    th = "".join(f"<th>{h}</th>" for h in head)
    return f"<div><h2>{title}</h2><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


def render(m: dict, now: datetime | None = None) -> str:
    ref = (m.get("referrals") or [(None, None, None)])[0]
    act = {r[0]: r for r in (m.get("activations") or [])}
    kpis = [
        ("Total users", m.get("total_users")), ("New · 7d", m.get("new_users_7d")),
        ("New · 30d", m.get("new_users_30d")), ("DAU", m.get("dau")), ("WAU", m.get("wau")),
        ("MAU", m.get("mau")), ("Logins · 7d", m.get("logins_7d")), ("Logins · all", m.get("logins_total")),
        ("Paper activations", act.get("paper", (0, 0))[1] if m.get("activations") is not None else None),
        ("Live activations", act.get("live", (0, 0))[1] if m.get("activations") is not None else None),
        ("Invites sent", ref[0]), ("Invites accepted", ref[1]),
        ("Referred signups", m.get("referred_signups")), ("Backtests · all", m.get("backtests_total")),
        ("Backtests · 7d", m.get("backtests_7d")), ("Teams", m.get("teams")),
    ]
    k = "".join(f"<div class='adm-kpi'><b>{_v(v)}</b><span>{lbl}</span></div>" for lbl, v in kpis)
    grid = "".join([
        _table("New users per day (ET)", ["Day", "Users"], m.get("new_users_daily")),
        _table("New users per week (ET, Mon)", ["Week", "Users"], m.get("new_users_weekly")),
        _table("Roles", ["Role", "Users"], m.get("roles")),
        _table("Logins by method · 30d", ["Method", "Logins"], m.get("logins_by_method_30d")),
        _table("Activations", ["Mode", "Activations", "Users"], m.get("activations")),
    ])
    return (f"<h1>Admin · user analytics</h1><p class='sub'>Generated {stamp(now)}. "
            "Active = signed in or made a logged request in the window. Login tracking started with v0.41.0; "
            "older sessions are not counted.</p>"
            f"<div class='adm-kpis'>{k}</div><div class='adm-grid'>{grid}</div>")


def render_exclusions(rules: list[dict], msg: str = "") -> str:
    """Excluded-securities admin panel (engine/reporting/exclusions.py)."""
    from engine.reporting.exclusions import dust_threshold
    e = html.escape
    rows = "".join(
        f"<tr><td><b>{e(str(r.get('symbol')))}</b></td><td>{e(str(r.get('scope')))}</td>"
        f"<td>{e(str(r.get('account_ref') or '—'))}</td><td>{e(str(r.get('reason') or ''))}</td>"
        f"<td>{'auto' if r.get('auto') else 'manual'}</td>"
        f"<td>{e(str(r.get('created_at') or '')[:16])}</td><td>"
        + (f"<form method='post' action='/admin/exclusions/delete'><input type='hidden' name='id' value='{int(r['id'])}'>"
           f"<button type='submit' onclick=\"return confirm('Remove exclusion?')\">Remove</button></form>"
           if r.get("id") is not None else "")
        + "</td></tr>" for r in rules) or "<tr><td colspan='7'>None</td></tr>"
    dust = dust_threshold()
    note = (f"Auto rule: positions whose Alpaca asset is inactive or not tradable are excluded "
            f"(asset status cached, refreshed daily). Dust threshold: "
            f"{'$' + format(dust, ',.2f') if dust else 'off'} (env EXCLUSION_DUST_USD).")
    flash = f"<p class='sub'><b>{e(msg)}</b></p>" if msg else ""
    return (f"<div class='adm-ex' id='exclusions'><h2>Excluded securities</h2>{flash}"
            "<p class='sub'>Excluded positions are hidden from position tables and their market value / "
            f"unrealised P&amp;L leave equity-based P&amp;L on every page and email. {e(note)}</p>"
            "<form class='add' method='post' action='/admin/exclusions/add'>"
            "<input name='symbol' placeholder='Symbol (e.g. CDTX)' required maxlength='20'>"
            "<input name='account_ref' placeholder='Account (blank = global)' maxlength='64'>"
            "<input name='reason' placeholder='Reason' maxlength='300'>"
            "<button type='submit'>Add exclusion</button></form>"
            "<table><thead><tr><th>Symbol</th><th>Scope</th><th>Account</th><th>Reason</th><th>Type</th>"
            f"<th>Added</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>")


def _ts(x):
    if x is None:
        return "—"
    try:
        return x.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    except Exception:  # noqa: BLE001
        return html.escape(str(x)[:16])


def _money(x):
    if isinstance(x, str):
        return html.escape(x)
    try:
        return "—" if x is None else f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_running(data: dict, act: dict, show_all: bool, now: datetime | None = None) -> str:
    e = lambda x: html.escape(str(x if x is not None else "—"))  # noqa: E731
    rows = data.get("rows") or []
    if data.get("error"):
        body = "<tr><td colspan='10'>Unavailable</td></tr>"
    elif not rows:
        body = "<tr><td colspan='10'>None</td></tr>"
    else:
        body = "".join(
            f"<tr><td><b>{e(r['name'] or r['email'])}</b><br><small>{e(r['email'])}</small></td>"
            f"<td>{e(r['strategy'])}{' <small>(#' + str(r['id']) + ')</small>' if r['id'] else ''}</td>"
            f"<td><span class='pill {'live' if r['mode'] == 'live' else ''}'>{e(r['mode'])}</span></td>"
            f"<td>{e(r['account'])}<br><small>{e(r['prefix'])}</small></td><td class='n'>{_money(r['allocation'])}</td>"
            f"<td><span class='pill {e(r['status']).split(' ')[0]}'>{e(r['status'])}</span>"
            + (f"<br><small>db: {e(r['db_status'])}</small>" if r['db_status'] not in (r['status'], 'system') else "")
            + f"</td><td><small>{e(r['runner'])}</small></td>"
            f"<td>{_ts(r['last_trade'])}<br><small>{r['trades']} trades</small></td><td>{_ts(r['created'])}</td></tr>"
            for r in rows)
    tog = ("<a href='/admin/running'>Show active only</a>" if show_all
           else "<a href='/admin/running?all=1'>Show all (incl. deactivated / stopped)</a>")
    users = act.get("users")
    if users is None:
        ub = "<tr><td colspan='10'>Unavailable</td></tr>"
    else:
        ub = "".join(
            f"<tr><td><b>{e(u['display_name'] or '')}</b><br><small>{e(u['email'])}</small></td><td>{e(u['role'])}</td>"
            f"<td>{_ts(u['created_at'])}</td><td>{_ts(u['last_login_at'])}</td>"
            f"<td class='n'>{u['logins_7d']}</td><td class='n'>{u['logins_30d']}</td>"
            f"<td>{'yes' if u['has_keys'] else 'no'}</td><td class='n'>{u['strategies']} / {u['clones']}</td>"
            f"<td class='n'>{u['activations']} ({u['active_activations']} active)</td></tr>" for u in users) \
            or "<tr><td colspan='9'>None</td></tr>"
    ev = act.get("events")
    eb = ("<tr><td colspan='4'>Unavailable</td></tr>" if ev is None else "".join(
        f"<tr><td>{_ts(x['at'])}</td><td>{e(x['email'])}</td><td><span class='pill'>{e(x['kind'])}</span></td>"
        f"<td>{e(x['detail'])}</td></tr>" for x in ev) or "<tr><td colspan='4'>None</td></tr>")
    return (
        "<h1>Admin · running strategies &amp; user activity</h1>"
        "<p class='adm-nav'><a href='/admin'>&larr; Analytics</a><a href='#running'>Running</a>"
        "<a href='#users'>Users</a><a href='#events'>Events</a></p>"
        f"<p class='sub'>Generated {stamp(now)}. Status 'running' = the runner heartbeat shows the instance holding "
        "the lease and acting within the last 96h (runners idle outside market hours). 'db:' shows the stored "
        "activation status when it differs. System rows are operator runners (btd-scheduler).</p>"
        f"<h2 id='running'>Running strategies ({len(rows)})</h2><p class='tog'>{tog}</p>"
        "<div class='adm-tw'><table><thead><tr><th>User</th><th>Strategy</th><th>Mode</th><th>Account</th>"
        "<th>Allocation</th><th>Status</th><th>Runner heartbeat</th><th>Last trade</th><th>Created</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
        f"<h2 id='users'>User activity ({len(users or [])})</h2>"
        "<div class='adm-tw'><table><thead><tr><th>User</th><th>Role</th><th>Signed up</th><th>Last login</th>"
        "<th>Logins 7d</th><th>Logins 30d</th><th>Broker keys</th><th>Strategies / clones</th><th>Activations</th>"
        f"</tr></thead><tbody>{ub}</tbody></table></div>"
        "<h2 id='events'>Recent events</h2><div class='adm-tw'><table><thead><tr><th>When</th><th>User</th>"
        f"<th>Event</th><th>Detail</th></tr></thead><tbody>{eb}</tbody></table></div>")


def register(app, rt):
    entry = ("Admin", "/admin", "admin")
    if entry not in ph_layout.MONITORING_PAGES:
        ph_layout.MONITORING_PAGES.append(entry)

    @rt("/admin", methods=["GET"])
    def admin_get(session):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin?next=/admin", status_code=303)
        from engine.rbac import is_admin
        if not is_admin(user):
            return RedirectResponse("/dashboard", status_code=303)
        from engine.admin_analytics import snapshot
        from engine.reporting.exclusions import list_rules
        body = ("<p class='adm-nav'><a href='/admin/running'><b>Running strategies &amp; user activity &rarr;</b></a></p>"
                + render(snapshot()) + render_exclusions(list_rules(force=True), session.pop("adm_msg", "") or ""))
        return page("admin", Style(_CSS), Div(NotStr(body), cls="adm"),
                    user=user, title="Admin · AlpaTrade", right_news=False)

    @rt("/admin/running", methods=["GET"])
    def admin_running_get(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin?next=/admin/running", status_code=303)
        from engine.rbac import is_admin
        if not is_admin(user):
            from starlette.responses import HTMLResponse
            return HTMLResponse("Forbidden: admin only", status_code=403)
        from engine import admin_running
        show_all = request.query_params.get("all") == "1"
        body = render_running(admin_running.running(include_all=show_all), admin_running.activity(), show_all)
        return page("admin", Style(_CSS), Div(NotStr(body), cls="adm"),
                    user=user, title="Admin · Running · AlpaTrade", right_news=False)

    def _admin_or_none(session):
        user = _user(session)
        from engine.rbac import is_admin
        return user if user and is_admin(user) else None

    @rt("/admin/exclusions/add", methods=["POST"])
    async def admin_exclusion_add(session, request):
        if not _admin_or_none(session):
            return RedirectResponse("/dashboard", status_code=303)
        import re
        form = dict(await request.form())
        sym = str(form.get("symbol") or "").strip().upper()
        ref = str(form.get("account_ref") or "").strip()
        if not re.fullmatch(r"[A-Z0-9./-]{1,20}", sym) or (ref and not re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", ref)):
            session["adm_msg"] = "Invalid symbol or account."
        else:
            from engine.reporting.exclusions import add_rule
            try:
                add_rule(sym, ref or None, str(form.get("reason") or ""))
                session["adm_msg"] = f"Excluded {sym}" + (f" for {ref}" if ref else " globally") + "."
            except Exception as exc:  # noqa: BLE001
                session["adm_msg"] = f"Could not add exclusion ({type(exc).__name__})."
        return RedirectResponse("/admin#exclusions", status_code=303)

    @rt("/admin/exclusions/delete", methods=["POST"])
    async def admin_exclusion_delete(session, request):
        if not _admin_or_none(session):
            return RedirectResponse("/dashboard", status_code=303)
        form = dict(await request.form())
        try:
            from engine.reporting.exclusions import remove_rule
            remove_rule(int(form.get("id")))
            session["adm_msg"] = "Exclusion removed."
        except Exception as exc:  # noqa: BLE001
            session["adm_msg"] = f"Could not remove exclusion ({type(exc).__name__})."
        return RedirectResponse("/admin#exclusions", status_code=303)

    @rt("/admin/metrics", methods=["GET"])
    def admin_metrics_get(session):
        """Runtime metrics guard: recent METRICS_MISMATCH records in this web process."""
        from starlette.responses import JSONResponse
        user = _user(session)
        from engine.rbac import is_admin
        if not user or not is_admin(user):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        from engine.metrics import recent_mismatches
        mm = recent_mismatches()
        import os as _os
        from utils.btd_parity_daily import recent as _parity_recent
        parity = _parity_recent(_os.environ.get("DATABASE_URL"), 30)
        return JSONResponse({"mismatches": mm[-50:], "count": len(mm),
                             "btd_parity": parity, "btd_parity_divergent_days": sum(1 for r in parity if not r["ok"])},
                            )

    return ["/admin", "/admin/metrics", "/admin/exclusions/add", "/admin/exclusions/delete"]
