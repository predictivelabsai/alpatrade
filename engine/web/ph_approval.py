"""Sign-up approval: the app-wide gate, the /pending page and the admin review panel.

* :func:`approval_gate` is FastHTML beforeware (installed in ``app.py``). A signed-in user
  whose ``approval_status`` is ``pending`` / ``rejected`` (:mod:`engine.approval`) can only
  reach the auth pages, static assets and ``/pending``; every other request is redirected
  there (GET), told to redirect (htmx) or refused with 403.
* ``/admin/running#approvals`` (rendered by :func:`render_approvals`, mounted in
  :mod:`engine.web.ph_admin`) lists sign-ups with Approve / Reject and a status filter.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fasthtml.common import A, Div, H2, NotStr, P, Span
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

from engine import approval

# Paths a pending/rejected (signed-in) user may still reach.
ALLOWED = [re.compile(p) for p in (
    r"/pending", r"/logout", r"/signin", r"/register", r"/login", r"/auth/callback",
    r"/verify(/.*)?", r"/forgot", r"/reset", r"/healthz", r"/health", r"/favicon\..*",
    r"/static/.*", r"/robots\.txt", r".*\.(css|js|map|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|pdf)",
)]

CSS = """
.apv{margin:1rem 0 1.6rem}.apv h2{margin-bottom:.3rem}
.apv-tabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:.4rem 0 .8rem}
.apv-tabs a{padding:.3rem .7rem;border:1px solid var(--line);border-radius:999px;font-size:.8rem;text-decoration:none;background:#fff;color:inherit}
.apv-tabs a.on{background:#1F5D43;color:#fff;border-color:#1F5D43}
.apv-list{display:grid;gap:.6rem}
.apv-card{background:#fff;border:1px solid var(--line);border-radius:.6rem;padding:.7rem .8rem;display:flex;flex-wrap:wrap;gap:.6rem 1.2rem;align-items:flex-start;min-width:0}
.apv-who{flex:1 1 240px;min-width:0}.apv-who b{font-size:.95rem}.apv-who small{display:block;color:var(--ink-muted);overflow-wrap:anywhere}
.apv-meta{flex:2 1 320px;min-width:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.25rem .9rem;font-size:.78rem}
.apv-meta span{color:var(--ink-muted);display:block;font-size:.7rem}.apv-meta div{overflow-wrap:anywhere;min-width:0}
.apv-act{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;flex:0 0 auto}
.apv-act form{display:inline-flex;gap:.3rem;align-items:center;margin:0}
.apv-act button{padding:.4rem .8rem;border-radius:.4rem;font-size:.82rem;cursor:pointer;border:1px solid var(--line);background:#fff}
.apv-act button.ok{background:#1F5D43;color:#fff;border-color:#1F5D43}.apv-act button.no{color:#b43b35;border-color:#e3b3b0}
.apv-act label{font-size:.75rem;color:var(--ink-muted);display:inline-flex;gap:.25rem;align-items:center}
.apv .pill.pending{background:#fff6e0;color:#8a6410}.apv .pill.approved{background:#e3f4ea;color:#147a4b}.apv .pill.rejected{background:#fdeceb;color:#b43b35}
.apv-appr{font-size:.8rem;margin:.6rem 0 0}.apv-appr form{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.3rem}
.apv-appr input{flex:1 1 260px;min-width:0;padding:.35rem .5rem;border:1px solid var(--line);border-radius:.4rem;font-size:.82rem}
.apv-appr button{padding:.35rem .7rem;border:1px solid var(--line);border-radius:.4rem;background:#fff;cursor:pointer;font-size:.8rem}
@media(max-width:600px){.apv-act{flex:1 1 100%}.apv-act form{flex:1 1 auto}.apv-act button{flex:1 1 auto;padding:.55rem .8rem}}
"""


def _allowed(path: str) -> bool:
    return any(p.fullmatch(path or "/") for p in ALLOWED)


def approval_gate(req, sess):
    """Beforeware: keep pending / rejected users on /pending. Returns None to continue."""
    uid = sess.get("user_id") if sess else None
    if not uid or _allowed(req.url.path):
        return None
    st = approval.status_of(uid)
    if st not in approval.BLOCKED:
        return None
    msg = approval.block_message(uid) or approval.NOT_APPROVED_MSG
    if req.headers.get("hx-request"):
        return Response(status_code=200, headers={"HX-Redirect": "/pending"})
    if req.method in ("GET", "HEAD") and "application/json" not in req.headers.get("accept", ""):
        return RedirectResponse("/pending", status_code=303)
    if "application/json" in req.headers.get("accept", "") or req.url.path.startswith("/api"):
        return JSONResponse({"error": "not_approved", "status": st, "message": msg}, status_code=403)
    return PlainTextResponse(msg, status_code=403)


def _ts(x) -> str:
    if not x:
        return "—"
    try:
        return x.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    except Exception:  # noqa: BLE001
        return html.escape(str(x)[:16])


def _ua(ua: Optional[str]) -> str:
    ua = (ua or "").strip()
    return (ua[:90] + "…") if len(ua) > 90 else (ua or "—")


def render_approvals(rows: Optional[list[dict]], cnt: dict, flt: str, approver_list: list[str],
                     me: Optional[dict] = None, msg: str = "", can_edit_approvers: bool = True) -> str:
    e = lambda x: html.escape(str(x if x is not None else "—"))  # noqa: E731
    tabs = []
    for key, label in (("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("all", "All")):
        n = sum(cnt.values()) if key == "all" else cnt.get(key)
        tabs.append(f"<a class='{'on' if key == flt else ''}' href='/admin/running?approvals={key}#approvals'>"
                    f"{label}{f' ({n})' if n is not None else ''}</a>")
    me_id = str((me or {}).get("user_id") or "")
    if rows is None:
        body = "<p class='sub'>Unavailable (approval data could not be loaded).</p>"
    elif not rows:
        body = f"<p class='sub'>No {'' if flt == 'all' else e(flt) + ' '}users.</p>"
    else:
        cards = []
        for r in rows:
            st = r.get("approval_status") or "approved"
            uid = e(r["user_id"])
            ip = r.get("signup_ip") or r.get("last_ip")
            ua = r.get("signup_user_agent") or r.get("last_ua")
            meta = [
                ("Signed up", _ts(r.get("created_at"))), ("Method", approval.method_label(r)),
                ("Email verified", "yes" if r.get("email_verified_at") else "no"),
                ("IP", ip or "—"), ("User agent", _ua(ua)),
                ("Last login", _ts(r.get("last_login_at"))), ("Logins", r.get("logins") or 0),
                ("Referred by", r.get("referred_by") or "—"), ("Role", r.get("role") or "user"),
            ]
            if r.get("approval_decided_at"):
                meta.append(("Decided", f"{_ts(r.get('approval_decided_at'))} by {r.get('decided_by') or '—'}"))
            meta_html = "".join(f"<div><span>{e(k)}</span>{e(v)}</div>" for k, v in meta)
            acts = []
            if str(r["user_id"]) != me_id:
                if st != "approved":
                    acts.append(
                        "<form method='post' action='/admin/approvals/decide'>"
                        f"<input type='hidden' name='user_id' value='{uid}'><input type='hidden' name='status' value='approved'>"
                        f"<input type='hidden' name='filter' value='{e(flt)}'>"
                        "<label><input type='checkbox' name='notify' value='1' checked> email user</label>"
                        "<button class='ok' type='submit'>Approve</button></form>")
                if st != "rejected":
                    acts.append(
                        "<form method='post' action='/admin/approvals/decide' "
                        f"onsubmit=\"return confirm('Reject {e(r.get('email'))}? They will lose access to the app.')\">"
                        f"<input type='hidden' name='user_id' value='{uid}'><input type='hidden' name='status' value='rejected'>"
                        f"<input type='hidden' name='filter' value='{e(flt)}'>"
                        "<button class='no' type='submit'>Reject</button></form>")
            cards.append(
                f"<div class='apv-card' data-user='{uid}'><div class='apv-who'><b>{e(r.get('display_name') or r.get('email'))}</b>"
                f" <span class='pill {e(st)}'>{e(st)}</span><small>{e(r.get('email'))}</small></div>"
                f"<div class='apv-meta'>{meta_html}</div><div class='apv-act'>{''.join(acts)}</div></div>")
        body = f"<div class='apv-list'>{''.join(cards)}</div>"
    flash = f"<p class='sub'><b>{e(msg)}</b></p>" if msg else ""
    appr = ", ".join(approver_list)
    appr_form = (
        "<form method='post' action='/admin/approvals/approvers'>"
        f"<input name='emails' value='{e(appr)}' aria-label='Approver emails (comma-separated)'>"
        "<button type='submit'>Save approvers</button></form>") if can_edit_approvers else ""
    return (f"<div class='apv' id='approvals'><h2>Sign-up approvals</h2>{flash}"
            "<p class='sub'>New accounts start <b>pending</b>: they can sign in but see an \"awaiting approval\" "
            "page and cannot connect keys, activate strategies or trade until approved.</p>"
            f"<div class='apv-tabs'>{''.join(tabs)}</div>{body}"
            f"<div class='apv-appr'>Approvers emailed on each sign-up (and allowed to review): <b>{e(appr)}</b>"
            f"{appr_form}</div></div>")


def _pending_page(user: dict, status: str):
    from engine.web.ph_layout import auth_shell
    email = user.get("email") or ""
    if status == "rejected":
        blocks = [H2("Account not approved"),
                  P("Your AlpaTrade account (", Span(email, style="font-weight:600"),
                    ") was not approved, so the app is not available to it.", cls="signin-sub"),
                  P("If you think this is a mistake, reply to any AlpaTrade email and we will take another look.",
                    cls="signin-sub", style="font-size:13px")]
    else:
        blocks = [H2("Your account is awaiting approval"),
                  P("Thanks for signing up, ", Span(email, style="font-weight:600"), ". Every new AlpaTrade "
                    "account is reviewed by an admin before it can use the app.", cls="signin-sub"),
                  P("We'll email you as soon as it is approved. Until then you can't connect broker keys, "
                    "activate strategies or trade.", cls="signin-sub", style="font-size:13px")]
    blocks += [A("Check again", href="/pending", cls="auth-primary-btn",
                 style="display:block;text-align:center;text-decoration:none;margin-top:12px"),
               A("Log out", href="/logout", cls="forgot-link")]
    return auth_shell(*blocks, title="AlpaTrade · Awaiting approval")


def register(app, rt):
    @rt("/pending", methods=["GET"])
    def pending_get(session):
        uid = session.get("user_id")
        if not uid:
            return RedirectResponse("/signin", status_code=303)
        from engine.auth import get_user_by_id
        try:
            user = get_user_by_id(str(uid))
        except Exception:  # noqa: BLE001
            user = None
        if not user:
            return RedirectResponse("/signin", status_code=303)
        st = approval.status_of(uid, fresh=True)
        if st not in approval.BLOCKED:
            return RedirectResponse("/dashboard", status_code=303)
        return _pending_page(user, st)

    def _reviewer(session):
        uid = session.get("user_id")
        if not uid:
            return None
        from engine.auth import get_user_by_id
        try:
            user = get_user_by_id(str(uid))
        except Exception:  # noqa: BLE001
            return None
        return user if approval.can_review(user) else None

    @rt("/admin/approvals/decide", methods=["POST"])
    async def approvals_decide(session, request):
        me = _reviewer(session)
        if not me:
            return PlainTextResponse("Forbidden: admin only", status_code=403)
        form = dict(await request.form())
        flt = str(form.get("filter") or "pending")
        flt = flt if flt in (*approval.STATUSES, "all") else "pending"
        try:
            res = approval.decide(str(form.get("user_id") or ""), str(form.get("status") or ""), me,
                                  notify_user=str(form.get("notify") or "") == "1")
            session["apv_msg"] = res.get("message") or ""
        except Exception as exc:  # noqa: BLE001
            session["apv_msg"] = f"Could not update ({type(exc).__name__})."
        return RedirectResponse(f"/admin/running?approvals={flt}#approvals", status_code=303)

    @rt("/admin/approvals/approvers", methods=["POST"])
    async def approvals_approvers(session, request):
        me = _reviewer(session)
        from engine.rbac import is_admin
        if not me or not is_admin(me):
            return PlainTextResponse("Forbidden: admin only", status_code=403)
        form = dict(await request.form())
        raw = re.split(r"[,;\s]+", str(form.get("emails") or ""))
        try:
            got = approval.set_approvers(raw, me.get("user_id"))
            session["apv_msg"] = "Approvers saved: " + ", ".join(got)
        except Exception as exc:  # noqa: BLE001
            session["apv_msg"] = f"Could not save approvers ({exc})."
        return RedirectResponse("/admin/running#approvals", status_code=303)

    return ["/pending", "/admin/approvals/decide", "/admin/approvals/approvers"]
