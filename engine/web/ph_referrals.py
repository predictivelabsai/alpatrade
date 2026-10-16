"""/invite — invite up to 5 friends with your referral link (engine.referrals)."""
from __future__ import annotations

import html
import time
from zoneinfo import ZoneInfo

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web import ph_layout
from engine.web.ph_layout import page

_CSS = """
.inv{max-width:760px;width:100%;margin:auto;padding:0 1rem 3rem}.inv h1{font-size:1.35rem;margin:.4rem 0}
.inv .sub{color:var(--ink-muted);font-size:.86rem;margin:0 0 1rem}
.inv-card{background:#fff;border:1px solid var(--line);border-radius:.7rem;padding:1rem;margin:0 0 1rem}
.inv-link{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}.inv-link input{flex:1;min-width:0;padding:.55rem;border:1px solid var(--line);border-radius:.45rem;font-size:.85rem}
.inv-link button,.inv form button{padding:.55rem .9rem;border:0;border-radius:.45rem;background:#1F5D43;color:#fff;font-weight:600;cursor:pointer;min-height:40px}
.inv form .em{display:block;width:100%;box-sizing:border-box;padding:.55rem;border:1px solid var(--line);border-radius:.45rem;margin:0 0 .45rem;font-size:.9rem}
.inv .code{font-weight:700;letter-spacing:.06em}.inv table{width:100%;border-collapse:collapse;font-size:.84rem}
.inv th,.inv td{padding:.45rem .4rem;border-bottom:1px solid var(--line);text-align:left}
.inv .pill{border-radius:999px;padding:.15rem .5rem;font-size:.72rem}.pill.sent{background:#fff0c8;color:#775a00}
.pill.accepted{background:#dcefe5;color:#176441}.pill.failed{background:#f8dedb;color:#9b302b}
.inv .note{font-size:.84rem;margin:.3rem 0}.inv .ok{color:#176441}.inv .warn{color:#9b302b}
@media(max-width:600px){.inv{padding:0 .7rem 2rem}.inv td:nth-child(3),.inv th:nth-child(3){display:none}}
"""
_RATE: dict[str, list[float]] = {}
RATE_MAX, RATE_WINDOW_S = 3, 600  # max 3 form submissions per user per 10 min


def rate_ok(uid: str, now: float | None = None) -> bool:
    now = now or time.time()
    hits = [t for t in _RATE.get(uid, []) if now - t < RATE_WINDOW_S]
    ok = len(hits) < RATE_MAX
    if ok:
        hits.append(now)
    _RATE[uid] = hits
    return ok


def _user(session):
    from engine.web.ph_auth import current_user
    return current_user(session)


def _fmt(ts):
    if not ts:
        return "—"
    return " · ".join(f"{ts.astimezone(ZoneInfo(z)):%b %d %H:%M} {l}"
                      for z, l in (("America/New_York", "ET"), ("Europe/London", "UK"), ("Europe/Tallinn", "Tallinn")))


def render(code: str, link: str, invites: list[dict], result: dict | None = None, remaining: int = 5) -> str:
    from engine.referrals import MAX_INVITES
    notes = ""
    if result:
        if result.get("error"):
            notes += f"<p class='note warn'>{html.escape(result['error'])}</p>"
        if result.get("sent"):
            notes += f"<p class='note ok'>Sent to {html.escape(', '.join(result['sent']))}.</p>"
        for e, why in result.get("skipped", []):
            notes += f"<p class='note warn'>Skipped {html.escape(e)}: {html.escape(why)}.</p>"
        for e in result.get("failed", []):
            notes += f"<p class='note warn'>Could not send to {html.escape(e)}; try again later.</p>"
        for e in result.get("invalid", []):
            notes += f"<p class='note warn'>Not an email address: {html.escape(e)}</p>"
    inputs = "".join(f"<input class='em' type='email' name='email' placeholder='friend{i + 1}@example.com' "
                     f"autocomplete='off'>" for i in range(max(0, min(remaining, MAX_INVITES))))
    form = (f"<form method='post' action='/invite'>{inputs}<button type='submit'>Send invites</button></form>"
            if remaining > 0 else "<p class='note'>You've used all your invites. Thank you!</p>")
    rows = "".join(f"<tr><td>{html.escape(i['email'])}</td><td><span class='pill {i['status']}'>{i['status']}</span></td>"
                   f"<td>{_fmt(i['sent_at'])}</td></tr>" for i in invites) or "<tr><td colspan='3'>No invites yet.</td></tr>"
    accepted = sum(1 for i in invites if i["status"] == "accepted")
    return f"""<h1>Invite friends</h1>
<p class='sub'>Invite up to {MAX_INVITES} friends. They get a short intro to AlpaTrade, a video and the user guide (PDF), with your referral link.</p>
<div class='inv-card'><b>Your referral link</b> · code <span class='code'>{html.escape(code)}</span>
<div class='inv-link' style='margin-top:.5rem'><input id='ref-link' readonly value='{html.escape(link)}'>
<button type='button' onclick="navigator.clipboard.writeText(document.getElementById('ref-link').value);this.textContent='Copied'">Copy</button></div></div>
<div class='inv-card'><b>Send invites</b> <span class='sub'>({remaining} of {MAX_INVITES} left)</span>{notes}<div style='margin-top:.5rem'>{form}</div></div>
<div class='inv-card'><b>Your invites</b> <span class='sub'>· {len(invites)} sent · {accepted} joined</span>
<table><thead><tr><th>Email</th><th>Status</th><th>Sent</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def _view(user, result=None):
    from engine import referrals as rf
    code = rf.get_or_create_code(str(user["user_id"]))
    invites = rf.list_invites(str(user["user_id"]))
    used = sum(1 for i in invites if i["status"] != "failed")
    return page("invite", Style(_CSS), Div(NotStr(render(code, rf.referral_link(code), invites, result,
                                                         rf.MAX_INVITES - used)), cls="inv"),
                user=user, title="Invite friends · AlpaTrade", right_news=False)


def register(app, rt):
    entry = ("Invite friends", "/invite", "invite")
    if entry not in ph_layout.MONITORING_PAGES:
        ph_layout.MONITORING_PAGES.insert(0, entry)

    @rt("/invite", methods=["GET"])
    def invite_get(session):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin?next=/invite", status_code=303)
        return _view(user)

    @app.post("/invite")
    async def invite_post(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin?next=/invite", status_code=303)
        if not rate_ok(str(user["user_id"])):
            return _view(user, {"error": "Too many attempts. Please wait a few minutes."})
        form = await request.form()
        from engine import referrals as rf
        result = rf.invite(user, [v for v in form.getlist("email") if v])
        return _view(user, result)

    return ["/invite"]
