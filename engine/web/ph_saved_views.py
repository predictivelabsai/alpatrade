"""Authenticated saved public-market views and in-app alert inbox."""
from __future__ import annotations

import html
import hmac
import secrets

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page

_CSS = """
.saved{max-width:960px;width:100%;margin:auto;padding:0 1rem 3rem}.saved h1{font-size:1.35rem;margin:.4rem 0}.saved .sub{font-size:.84rem;color:var(--ink-muted);margin:0 0 1rem}
.saved-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1rem}.saved-panel{border:1px solid var(--line);border-radius:.65rem;padding:1rem;background:var(--bg-elev)}.saved h2{font-size:1rem;margin:0 0 .65rem}.saved form{display:flex;gap:.55rem;flex-wrap:wrap}.saved input,.saved select{font:inherit;font-size:.84rem;border:1px solid var(--line-br);border-radius:.45rem;padding:.52rem .6rem;background:var(--bg);color:var(--ink)}.saved input[name=name]{flex:1;min-width:12rem}.saved button{border:0;border-radius:.45rem;background:var(--accent);color:#fff;padding:.55rem .85rem;cursor:pointer;min-height:38px}.saved .delete{background:transparent;color:#9b302b;border:1px solid #e5c5c1;padding:.3rem .55rem;min-height:0}.saved-list,.alert-list{list-style:none;padding:0;margin:.7rem 0 0}.saved-list li,.alert-list li{border-top:1px solid var(--line);padding:.7rem 0}.view-top{display:flex;justify-content:space-between;gap:.5rem;align-items:start}.view-top a{color:var(--accent);font-weight:650;text-decoration:none}.meta{font-size:.75rem;color:var(--ink-muted);margin-top:.25rem}.digest{display:inline-block;font-size:.67rem;border:1px solid var(--line-br);border-radius:999px;padding:.12rem .4rem;margin-top:.3rem}.alert-list a{color:var(--accent);font-weight:650;text-decoration:none}.alert-list p{font-size:.8rem;color:var(--ink-muted);margin:.25rem 0}.unread{border-left:3px solid var(--accent);padding-left:.55rem}.empty{font-size:.84rem;color:var(--ink-muted);padding:.8rem 0}@media(max-width:700px){.saved{padding-left:.75rem;padding-right:.75rem}.saved-grid{grid-template-columns:1fr}.saved input[name=name]{width:100%;min-width:0}.saved button{min-height:44px}}
"""


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None


def _csrf_token(session) -> str:
    """Create a session-bound CSRF token for all state-changing view actions."""
    token = session.get("saved_views_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["saved_views_csrf"] = token
    return token


def _valid_csrf(session, token) -> bool:
    expected = session.get("saved_views_csrf")
    return bool(expected and token and hmac.compare_digest(str(expected), str(token)))
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(str(uid))
    except Exception:  # noqa: BLE001
        return None


def _render(views: list[dict], alerts: list[dict], csrf_token: str, message: str = "") -> str:
    from engine.publicmarkets.saved_views import available_pages
    options = "".join(f"<option value='{key}'>{html.escape(label)}</option>"
                      for key, (label, _path) in available_pages().items())
    def view_item(view: dict) -> str:
        digest = "<span class='digest'>Daily in-app digest</span>" if view["daily_digest"] else ""
        return (
            f"<li><div class='view-top'><div><a href='{html.escape(view['path'], quote=True)}'>{html.escape(view['name'])}</a>"
            f"<div class='meta'>{html.escape(available_pages()[view['page_key']][0])}</div>{digest}</div>"
            f"<form method='post' action='/saved-views/{view['view_id']}/delete'><input type='hidden' name='csrf_token' value='{csrf_token}'><button class='delete' type='submit'>Delete</button></form></div></li>"
        )

    view_items = "".join(view_item(view) for view in views) or \
        "<li class='empty'>No saved views yet. Save a filter set you revisit often.</li>"
    alert_items = "".join(
        f"<li class='{'unread' if alert['read_at'] is None else ''}'><a href='{html.escape(alert['target_path'], quote=True)}'>{html.escape(alert['title'])}</a>"
        f"<p>{html.escape(alert['body'])}</p><div class='meta'>{html.escape(str(alert['created_at'])[:16])}</div></li>"
        for alert in alerts) or "<li class='empty'>No alerts yet. Enable a daily digest when saving a view.</li>"
    notice = f"<p class='sub'>{html.escape(message)}</p>" if message else ""
    return f"""
      <h1>Saved views & alerts</h1><p class='sub'>Save a public-markets filter set and optionally receive one in-app digest each day. No external messages are sent.</p>{notice}
      <div class='saved-grid'><section class='saved-panel'><h2>Save a view</h2><form method='post' action='/saved-views'>
      <input type='hidden' name='csrf_token' value='{csrf_token}'>
      <input name='name' required maxlength='100' placeholder='Name this view'><select name='page_key'>{options}</select>
      <input name='q' placeholder='Keyword (optional)'><input name='ticker' placeholder='Ticker (optional)' autocapitalize='characters'>
      <select name='form'><option value=''>Any filing form</option><option>8-K</option><option>10-Q</option><option>10-K</option><option>13F-HR</option></select>
      <label class='meta'><input type='checkbox' name='daily_digest'> Daily in-app digest</label><button type='submit'>Save view</button></form></section>
      <section class='saved-panel'><h2>Your views</h2><ul class='saved-list'>{view_items}</ul></section></div>
      <section class='saved-panel' style='margin-top:1rem'><div class='view-top'><h2>Alert inbox</h2><form method='post' action='/saved-views/alerts/read'><input type='hidden' name='csrf_token' value='{csrf_token}'><button class='delete' type='submit'>Mark all read</button></form></div><ul class='alert-list'>{alert_items}</ul></section>
    """


def register(app, rt):
    @rt("/saved-views", methods=["GET"])
    def saved_views_get(session, msg: str = ""):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        from engine.publicmarkets.saved_views import list_alerts, list_views
        return page("saved-views", Style(_CSS), Div(NotStr(_render(list_views(str(user['user_id'])), list_alerts(str(user['user_id'])), _csrf_token(session), msg)), cls="saved"), user=user, title="Saved Views · AlpaTrade", right_news=False)

    @rt("/saved-views", methods=["POST"])
    async def saved_views_post(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        if not _valid_csrf(session, form.get("csrf_token")):
            return RedirectResponse("/saved-views?msg=Your+form+expired.+Please+try+again", status_code=303)
        if form.get("daily_digest") and not user.get("email_verified_at"):
            return RedirectResponse("/saved-views?msg=Verify+your+email+before+enabling+daily+alerts", status_code=303)
        from engine.publicmarkets.saved_views import save_view
        view_id = save_view(str(user["user_id"]), str(form.get("name") or ""), str(form.get("page_key") or ""), dict(form), bool(form.get("daily_digest")))
        return RedirectResponse("/saved-views?msg=" + ("View+saved" if view_id else "Unable+to+save+view"), status_code=303)

    @rt("/saved-views/{view_id}/delete", methods=["POST"])
    async def saved_views_delete(session, request, view_id: str):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        if not _valid_csrf(session, form.get("csrf_token")):
            return RedirectResponse("/saved-views?msg=Your+form+expired.+Please+try+again", status_code=303)
        from engine.publicmarkets.saved_views import delete_view
        delete_view(str(user["user_id"]), view_id)
        return RedirectResponse("/saved-views?msg=View+deleted", status_code=303)

    @rt("/saved-views/alerts/read", methods=["POST"])
    async def alerts_read(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        if not _valid_csrf(session, form.get("csrf_token")):
            return RedirectResponse("/saved-views?msg=Your+form+expired.+Please+try+again", status_code=303)
        from engine.publicmarkets.saved_views import mark_alerts_read
        mark_alerts_read(str(user["user_id"]))
        return RedirectResponse("/saved-views?msg=Alerts+marked+read", status_code=303)

    return ["/saved-views"]
