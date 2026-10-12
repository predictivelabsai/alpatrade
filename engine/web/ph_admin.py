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
        body = render(snapshot()) + render_exclusions(list_rules(force=True), session.pop("adm_msg", "") or "")
        return page("admin", Style(_CSS), Div(NotStr(body), cls="adm"),
                    user=user, title="Admin · AlpaTrade", right_news=False)

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
        return JSONResponse({"mismatches": mm[-50:], "count": len(mm)})

    return ["/admin", "/admin/metrics", "/admin/exclusions/add", "/admin/exclusions/delete"]
