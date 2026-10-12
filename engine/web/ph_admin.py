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
@media(max-width:600px){.adm{padding:0 .7rem 2rem}.adm-kpis{grid-template-columns:repeat(2,1fr)}}
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
        return page("admin", Style(_CSS), Div(NotStr(render(snapshot())), cls="adm"),
                    user=user, title="Admin · AlpaTrade", right_news=False)

    return ["/admin"]
