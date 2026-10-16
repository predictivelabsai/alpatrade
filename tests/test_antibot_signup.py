"""Anti-bot signup guard: honeypot, min time-to-submit, Turnstile flag, per-IP
rate limit, verify-before-login and the stale-account purge SQL. No real DB."""
import time
from unittest import mock

import pytest
from fastcore.xml import to_xml
from starlette.testclient import TestClient

from engine.web import antibot
import engine.web.ph_auth as ph_auth


def _ok_form(**kw):
    f = {"website": "", "ft": antibot.form_token(time.time() - 10)}
    f.update(kw)
    return f


@pytest.fixture(autouse=True)
def _no_turnstile(monkeypatch):
    for k in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "TURNSTILE_ENABLED"):
        monkeypatch.delenv(k, raising=False)


def test_check_form_passes_and_rejects():
    assert antibot.check_form(_ok_form()) == ""
    assert antibot.check_form(_ok_form(website="http://spam")) == "honeypot"
    assert antibot.check_form(_ok_form(ft=antibot.form_token())) == "too_fast"
    assert antibot.check_form(_ok_form(ft="123.bad")) == "invalid"
    assert antibot.check_form({"website": ""}) == "invalid"
    assert antibot.check_form(_ok_form(ft=antibot.form_token(time.time() - 3 * 3600))) == "expired"


def test_turnstile_flag(monkeypatch):
    assert not antibot.turnstile_enabled()
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "sec")
    assert antibot.turnstile_enabled()
    from fasthtml.common import Form
    html = to_xml(Form(*antibot.guard_fields()))
    assert "cf-turnstile" in html and 'data-sitekey="site"' in html
    assert antibot.check_form(_ok_form()) == "captcha"  # no token
    with mock.patch.object(antibot, "verify_turnstile", return_value=True):
        assert antibot.check_form(_ok_form(**{"cf-turnstile-response": "t"})) == ""
    monkeypatch.setenv("TURNSTILE_ENABLED", "0")
    assert not antibot.turnstile_enabled()


def test_forms_render_guard_fields():
    for page in (ph_auth._register_page(), ph_auth._signin_page(), ph_auth._forgot_page()):
        html = to_xml(page)
        assert 'name="website"' in html and 'name="ft"' in html


def test_is_test_email():
    assert antibot.is_test_email("a@alpatrade-test.invalid")
    assert antibot.is_test_email("x@example.com")
    assert not antibot.is_test_email("someone@gmail.com")


def test_needs_verification():
    assert ph_auth._needs_verification({"email_verified_at": None, "google_id": None})
    assert not ph_auth._needs_verification({"email_verified_at": "2026-01-01", "google_id": None})
    assert not ph_auth._needs_verification({"email_verified_at": None, "google_id": "g"})


def test_create_user_refuses_non_test_domain_under_pytest():
    import engine.auth as auth
    with pytest.raises(RuntimeError):
        auth.create_user("real.person@gmail.com", "x" * 10)


@pytest.fixture()
def client():
    from app import app
    return TestClient(app, raise_server_exceptions=False)


def test_register_does_not_log_in_and_shows_check_inbox(client, monkeypatch):
    user = {"user_id": "11111111-1111-1111-1111-111111111111", "email": "new@alpatrade-test.invalid",
            "email_verified_at": None}
    monkeypatch.setattr(ph_auth, "get_user_by_email", lambda e: None)
    monkeypatch.setattr(ph_auth, "create_user", lambda **kw: user)
    monkeypatch.setattr(ph_auth, "_send_verification_email", lambda u, r: None)
    monkeypatch.setattr(ph_auth, "_attribute_referral", lambda s, u: None)
    monkeypatch.setattr(antibot, "rate_limited", lambda ip: False)
    monkeypatch.setattr(antibot, "log_attempt", lambda *a, **k: None)
    monkeypatch.setattr(antibot, "maybe_alert_admin", lambda: False)
    r = client.post("/register", data=_ok_form(email=user["email"], password="longenough1"),
                    follow_redirects=False)
    assert r.status_code == 200 and "Check your inbox" in r.text
    assert client.get("/profile", follow_redirects=False).status_code in (302, 303)


def test_register_honeypot_and_rate_limit(client, monkeypatch):
    seen = []
    monkeypatch.setattr(antibot, "log_attempt", lambda ip, e, ua, o, *a: seen.append(o))
    create = mock.Mock()
    monkeypatch.setattr(ph_auth, "create_user", create)
    r = client.post("/register", data=_ok_form(email="b@x.io", password="longenough1", website="x"))
    assert "try again" in r.text and seen[-1] == "honeypot"
    monkeypatch.setattr(antibot, "rate_limited", lambda ip: True)
    r = client.post("/register", data=_ok_form(email="b@x.io", password="longenough1"),
                    headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"})
    assert "Too many signups" in r.text and seen[-1] == "rate_limited"
    create.assert_not_called()


def test_signin_blocks_unverified_password_user(client, monkeypatch):
    u = {"user_id": "u-2", "email": "p@alpatrade-test.invalid", "email_verified_at": None, "google_id": None}
    monkeypatch.setattr(ph_auth, "authenticate", lambda e, p: u)
    login = mock.Mock()
    monkeypatch.setattr(ph_auth, "_session_login", login)
    r = client.post("/signin", data=_ok_form(email=u["email"], password="pw"), follow_redirects=False)
    assert r.status_code == 200 and "verify your email" in r.text
    login.assert_not_called()
    u2 = dict(u, email_verified_at="2026-10-01")
    monkeypatch.setattr(ph_auth, "authenticate", lambda e, p: u2)
    r = client.post("/signin", data=_ok_form(email=u["email"], password="pw"), follow_redirects=False)
    assert r.status_code == 303 and login.called


def test_signin_too_fast_rejected(client, monkeypatch):
    auth = mock.Mock()
    monkeypatch.setattr(ph_auth, "authenticate", auth)
    r = client.post("/signin", data={"email": "a@b.c", "password": "x", "ft": antibot.form_token()})
    assert "try again" in r.text
    auth.assert_not_called()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


def test_purge_sql_guards():
    w = antibot._STALE_WHERE
    for frag in ("user_accounts", "user_strategy_activations", "user_live_broker_accounts",
                 "alpatrade.runs", "alpatrade.trades", "google_id IS NULL", "is_admin IS NOT TRUE"):
        assert frag in w
