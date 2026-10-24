"""Admin user approval (v0.56.0): the app gate, /pending, the review panel, admin emails,
domain refusals (keys / paper / live) and the API guard. No real DB (engine.approval is faked)."""
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from engine import approval
from engine.web import ph_approval

UID_P, UID_A, UID_R, ADMIN = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222",
                              "33333333-3333-3333-3333-333333333333", "44444444-4444-4444-4444-444444444444")
STATUS = {UID_P: "pending", UID_A: "approved", UID_R: "rejected", ADMIN: "approved"}
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fake_status(monkeypatch):
    monkeypatch.setattr(approval, "status_of", lambda uid, fresh=False: STATUS.get(str(uid)))
    monkeypatch.delenv("SIGNUP_APPROVER_EMAILS", raising=False)


def _gate_app(uid):
    from fasthtml.common import Beforeware, fast_app
    app, rt = fast_app(secret_key="t", before=[Beforeware(ph_approval.approval_gate)])

    @rt("/_login")
    def _login(session):
        session["user_id"] = uid
        return "ok"

    @rt("/dashboard")
    def _dash():
        return "DASH"

    @rt("/profile/keys", methods=["POST"])
    def _keys():
        return "SAVED"

    @rt("/signin")
    def _signin():
        return "SIGNIN"

    c = TestClient(app, follow_redirects=False)
    if uid:
        c.get("/_login")
    return c


def test_gate_sends_pending_and_rejected_to_pending_page():
    for uid in (UID_P, UID_R):
        c = _gate_app(uid)
        r = c.get("/dashboard")
        assert r.status_code == 303 and r.headers["location"] == "/pending"
        assert c.post("/profile/keys").status_code == 403
        r = c.get("/dashboard", headers={"HX-Request": "true"})
        assert r.headers.get("HX-Redirect") == "/pending"
        j = c.get("/dashboard", headers={"Accept": "application/json"})
        assert j.status_code == 403 and j.json()["error"] == "not_approved"
        assert c.get("/signin").text == "SIGNIN"           # auth pages stay reachable


def test_gate_lets_approved_anonymous_and_unknown_through():
    assert _gate_app(UID_A).get("/dashboard").text == "DASH"
    assert _gate_app(None).get("/dashboard").text == "DASH"
    assert _gate_app("55555555-5555-5555-5555-555555555555").get("/dashboard").text == "DASH"  # unreadable → open


def test_allowed_paths():
    for p in ("/pending", "/logout", "/verify", "/verify/resend", "/static/app.css", "/favicon.ico", "/healthz"):
        assert ph_approval._allowed(p), p
    for p in ("/", "/dashboard", "/app", "/settings/integrations", "/admin/running", "/strategies/3/activate"):
        assert not ph_approval._allowed(p), p


def test_pending_page(monkeypatch):
    from fasthtml.common import fast_app
    import engine.auth as auth
    monkeypatch.setattr(auth, "get_user_by_id", lambda uid: {"user_id": uid, "email": "bot@x.io"})
    app, rt = fast_app(secret_key="t")
    ph_approval.register(app, rt)

    @rt("/_login")
    def _login(session, uid: str):
        session["user_id"] = uid
        return "ok"
    c = TestClient(app, follow_redirects=False)
    c.get(f"/_login?uid={UID_P}")
    r = c.get("/pending")
    assert r.status_code == 200 and "awaiting approval" in r.text and "bot@x.io" in r.text
    c.get(f"/_login?uid={UID_R}")
    assert "not approved" in c.get("/pending").text
    c.get(f"/_login?uid={UID_A}")
    assert c.get("/pending").headers["location"] == "/dashboard"


def _row(**kw):
    r = {"user_id": UID_P, "email": "shastryinvest@gmail.com", "display_name": "Rupam Investment", "role": "user",
         "created_at": NOW, "approval_status": "pending", "approval_decided_at": None, "decided_by": None,
         "signup_method": None, "signup_ip": None, "signup_user_agent": None, "email_verified_at": NOW,
         "has_google": True, "has_password": False, "last_login_at": NOW, "referred_by": None,
         "last_ip": "203.0.113.9", "last_ua": "Mozilla/5.0 (X11; Linux) HeadlessChrome", "logins": 1}
    r.update(kw)
    return r


def test_render_approvals_pending_cards_and_filters():
    html = ph_approval.render_approvals([_row()], {"pending": 1, "approved": 17, "rejected": 0}, "pending",
                                        ["kaljuvee@gmail.com", "joosep.laats@gmail.com"],
                                        me={"user_id": ADMIN})
    assert "id='approvals'" in html and "Rupam Investment" in html and "shastryinvest@gmail.com" in html
    assert "Pending (1)" in html and "Approved (17)" in html and "All (18)" in html
    assert "value='approved'" in html and "value='rejected'" in html          # Approve + Reject
    assert "google" in html and "203.0.113.9" in html and "HeadlessChrome" in html
    assert "2026-10-24 05:00 ET" in html
    assert "joosep.laats@gmail.com" in html and "Save approvers" in html
    # approved row: only Reject; own row: no buttons; approver-only view: no approver editing
    a = ph_approval.render_approvals([_row(approval_status="approved")], {}, "approved", [], me={"user_id": ADMIN})
    assert ">Reject</button>" in a and ">Approve</button>" not in a
    own = ph_approval.render_approvals([_row(user_id=ADMIN)], {}, "all", [], me={"user_id": ADMIN})
    assert "<form" not in own.split("apv-appr")[0]
    assert "Save approvers" not in ph_approval.render_approvals([], {}, "pending", ["a@b.c"], can_edit_approvers=False)
    assert "Unavailable" in ph_approval.render_approvals(None, {}, "pending", [])


def test_render_escapes_user_supplied_fields():
    html = ph_approval.render_approvals([_row(display_name="<script>x</script>", last_ua="<b>")], {}, "pending", [])
    assert "<script>x" not in html and "&lt;script&gt;" in html


def test_approvers_env_override_and_cleaning(monkeypatch):
    monkeypatch.setenv("SIGNUP_APPROVER_EMAILS", " Kaljuvee@gmail.com , bad, joosep.laats@gmail.com,kaljuvee@gmail.com")
    assert approval.approvers() == ["kaljuvee@gmail.com", "joosep.laats@gmail.com"]


def test_approvers_default_when_db_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(approval, "ensure_schema", boom)
    assert approval.approvers() == list(approval.DEFAULT_APPROVERS)


def test_can_review_admin_or_listed_approver(monkeypatch):
    import engine.rbac as rbac
    monkeypatch.setattr(approval, "approvers", lambda: ["joosep.laats@gmail.com"])
    monkeypatch.setattr(rbac, "is_admin", lambda u: u.get("email") == "kaljuvee@gmail.com")
    assert approval.can_review({"user_id": "a", "email": "kaljuvee@gmail.com"})
    assert approval.can_review({"user_id": "b", "email": "Joosep.Laats@gmail.com"})
    assert not approval.can_review({"user_id": "c", "email": "someone@x.io"})
    assert not approval.can_review(None)


def test_admin_email_goes_to_every_approver(monkeypatch):
    monkeypatch.setattr(approval, "approvers", lambda: ["kaljuvee@gmail.com", "joosep.laats@gmail.com"])
    sent = []
    to = approval.notify_admins({"user_id": UID_P, "email": "new@x.io", "display_name": "New <Person>"}, "google",
                                "198.51.100.7", "curl/8", send=lambda a, s, b: sent.append((a, s, b)) or True,
                                background=False)
    assert to == ["kaljuvee@gmail.com", "joosep.laats@gmail.com"] and [s[0] for s in sent] == to
    subj, body = sent[0][1], sent[0][2]
    assert "new@x.io" in subj and "awaiting approval" in subj
    assert "google" in body and "198.51.100.7" in body and "New &lt;Person&gt;" in body
    assert "https://alpatrade.chat/admin/running#approvals" in body
    assert " ET" in body and " UK" in body and " Tallinn" in body


def test_on_signup_never_raises(monkeypatch):
    monkeypatch.setattr(approval, "record_signup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        approval.on_signup({"user_id": UID_P, "email": "a@b.c"}, "email")  # record_signup itself never raises
    calls = []
    monkeypatch.setattr(approval, "record_signup", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(approval, "notify_admins", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    approval.on_signup({"user_id": UID_P, "email": "a@b.c"}, "email", "1.2.3.4", "ua")
    assert calls == [(UID_P, "email", "1.2.3.4", "ua")]


def test_decide_refuses_self_and_unknown_status():
    assert not approval.decide(ADMIN, "rejected", {"user_id": ADMIN})["ok"]
    assert not approval.decide(UID_P, "maybe", {"user_id": ADMIN})["ok"]


def test_block_message_and_require_approved():
    assert approval.block_message(UID_A) == "" and approval.block_message(None) == ""
    assert "awaiting" in approval.block_message(UID_P) and "not approved" in approval.block_message(UID_R)
    with pytest.raises(approval.NotApprovedError):
        approval.require_approved(UID_P)
    approval.require_approved(UID_A)


def test_pending_user_cannot_store_keys_or_activate():
    from engine import auth
    from engine.leaderboard import activate as act
    with pytest.raises(approval.NotApprovedError):
        auth.store_alpaca_keys(UID_P, "PKTEST", "secret")
    r = act.activate_paper(39, UID_P, enqueue=lambda **k: pytest.fail("queued for a pending user"))
    assert not r["ok"] and r["not_approved"]
    r = act.activate_live(39, UID_R, 100.0, "LIVE")
    assert not r["ok"] and r["not_approved"]


def test_signup_routes_call_on_signup(monkeypatch):
    """Email sign-up stamps the method and emails the approvers."""
    import time
    from fasthtml.common import fast_app
    import engine.web.ph_auth as ph_auth
    from engine.web import antibot
    for k in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    user = {"user_id": UID_P, "email": "fresh@alpatrade-test.invalid", "display_name": "Fresh"}
    monkeypatch.setattr(ph_auth, "get_user_by_email", lambda e: None)
    monkeypatch.setattr(ph_auth, "create_user", lambda **kw: user)
    monkeypatch.setattr(ph_auth, "_send_verification_email", lambda u, r: None)
    monkeypatch.setattr(antibot, "rate_limited", lambda ip: False)
    monkeypatch.setattr(antibot, "log_attempt", lambda *a, **k: None)
    monkeypatch.setattr(antibot, "maybe_alert_admin", lambda: False)
    got = []
    monkeypatch.setattr(approval, "on_signup", lambda u, m, ip="", ua="": got.append((u["email"], m)))
    app, rt = fast_app(secret_key="t")
    ph_auth.register(app, rt)
    c = TestClient(app, follow_redirects=False)
    r = c.post("/register", data={"email": user["email"], "password": "x" * 10, "website": "",
                                  "ft": antibot.form_token(time.time() - 10)})
    assert r.status_code == 200 and got == [(user["email"], "email")]


def test_api_jwt_guard(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    import api_app
    with pytest.raises(HTTPException) as ei:
        asyncio.run(api_app.require_tenant_user({"user_id": UID_P, "auth_type": "jwt"}))
    assert ei.value.status_code == 403
    assert asyncio.run(api_app.require_tenant_user({"user_id": UID_A, "auth_type": "jwt"}))["user_id"] == UID_A
    # service calls (the web app acting for a user) are not re-gated here
    assert asyncio.run(api_app.require_tenant_user({"user_id": UID_P, "auth_type": "service"}))
