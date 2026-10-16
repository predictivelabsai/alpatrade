"""Assisted Alpaca connect: state machine, secret hygiene, timeouts, key extraction (no network)."""
import logging
import time

import pytest

from engine import alpaca_connect as ac

PW, OTP = "S3cret-Passw0rd!", "123456"
KEY, SECRET = "PKABCDEFGHIJ1234567890", "aB3dEfGh1jKlMn0pQrStUvWxYz0123456789abcd"


class FakeBrowser:
    calls = []

    def __init__(self, need_otp=True, fail=None):
        self.need_otp, self.fail = need_otp, fail

    def login(self, email, password):
        FakeBrowser.calls.append(("login", email, password))
        if self.fail == "login":
            raise ac.ConnectError("Alpaca rejected that email/password.")
        return "otp" if self.need_otp else "ok"

    def submit_otp(self, code):
        FakeBrowser.calls.append(("otp", code))
        if self.fail == "otp":
            raise ac.ConnectError("Alpaca rejected the 2FA code (wrong or expired).")

    def regenerate(self, live):
        FakeBrowser.calls.append(("regen", live))
        return ("AK" + KEY[2:], SECRET) if live else (KEY, SECRET)

    def close(self):
        FakeBrowser.calls.append(("close",))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ALPACA_CONNECT_ENABLED", "1")
    ac.SESSIONS.clear()
    FakeBrowser.calls = []
    yield
    ac.SESSIONS.clear()


def _run(uid, factory, saved, live=False, code=OTP):
    saver = lambda u, k, s, lv: saved.append((u, k, s, lv)) or f"{'Live' if lv else 'Paper'} ok"  # noqa: E731
    r, f, w = ac.step(uid, "connect alpaca live" if live else "connect alpaca", factory, saver)
    assert "invalid" in r.lower() or "stop working" in r.lower()
    r, f, w = ac.step(uid, "me@example.com", factory, saver)
    assert f == "password"
    r, f, w = ac.step(uid, PW, factory, saver)
    assert w
    r, f = ac.poll(uid, 5)
    return r, f, saver


def test_flag_off_does_not_intercept(monkeypatch):
    monkeypatch.setenv("ALPACA_CONNECT_ENABLED", "0")
    assert not ac.wants("u1", "connect alpaca")


def test_trigger_and_active_session_intercept():
    assert ac.wants("u1", "connect my alpaca")
    assert ac.wants("u1", "/alpaca-connect")
    assert not ac.wants("u1", "what is alpaca?")
    ac.step("u1", "connect alpaca", FakeBrowser)
    assert ac.wants("u1", "anything at all")  # password/otp messages must be intercepted


def test_full_flow_paper_with_otp_and_wipe(caplog):
    caplog.set_level(logging.DEBUG)
    saved = []
    r, f, saver = _run("u1", lambda: FakeBrowser(), saved)
    assert f == "otp" and "2FA" in r
    s = ac.SESSIONS["u1"]
    assert s._password == ""  # wiped as soon as login was attempted
    ac.step("u1", OTP, FakeBrowser, saver)
    r, f = ac.poll("u1", 5)
    assert r.startswith("Done") and f is None
    assert saved == [("u1", KEY, SECRET, False)]
    assert ("close",) in FakeBrowser.calls
    assert s._password == "" and s.otp_q.empty()
    assert "u1" not in ac.SESSIONS
    assert PW not in caplog.text and OTP not in caplog.text and SECRET not in caplog.text
    assert PW not in repr(s)


def test_live_also_regenerated_when_asked():
    saved = []
    _, f, saver = _run("u2", lambda: FakeBrowser(), saved, live=True)
    ac.step("u2", OTP, FakeBrowser, saver)
    r, _ = ac.poll("u2", 5)
    assert [x[3] for x in saved] == [False, True] and r.startswith("Done")


def test_bad_password_is_clear_error():
    r, f, _ = _run("u3", lambda: FakeBrowser(fail="login"), [])
    assert "rejected that email/password" in r and f is None


def test_bad_otp_is_clear_error():
    saved = []
    _, _, saver = _run("u4", lambda: FakeBrowser(fail="otp"), saved)
    ac.step("u4", OTP, FakeBrowser, saver)
    r, _ = ac.poll("u4", 5)
    assert "2FA code" in r and saved == []


def test_otp_format_validated():
    _, _, saver = _run("u5", lambda: FakeBrowser(), [])
    r, f, w = ac.step("u5", "abc", FakeBrowser, saver)
    assert f == "otp" and not w


def test_otp_timeout(monkeypatch):
    monkeypatch.setattr(ac, "OTP_WAIT", 0.3)
    _run("u6", lambda: FakeBrowser(), [])
    time.sleep(0.6)
    r, _ = ac.poll("u6", 2)
    assert "Timed out waiting for the 2FA code" in r


def test_cancel_wipes():
    ac.step("u7", "connect alpaca", FakeBrowser)
    ac.step("u7", "me@example.com", FakeBrowser)
    r, _, _ = ac.step("u7", "cancel", FakeBrowser)
    assert "Cancelled" in r and "u7" not in ac.SESSIONS


def test_session_ttl(monkeypatch):
    ac.step("u8", "connect alpaca", FakeBrowser)
    monkeypatch.setattr(ac, "SESSION_TTL", -1)
    assert ac.active("u8") is None


def test_extract_pair():
    body = f"Your new keys\nKey {KEY}\nSecret {SECRET}\nThis secret will not be shown again"
    assert ac.extract_pair([body], live=False) == (KEY, SECRET)
    assert ac.extract_pair(["Key", KEY, SECRET], live=False) == (KEY, SECRET)
    assert ac.extract_pair(["nothing here"], live=False) is None
    assert ac.extract_pair([body], live=True) is None


def test_chat_route_does_not_persist_secrets(monkeypatch):
    import asyncio
    from engine.web import ph_chat
    saved = []
    monkeypatch.setattr(ph_chat, "_save_chat_message", lambda *a, **k: saved.append(a))
    ac.step("u9", "connect alpaca", FakeBrowser)
    ac.step("u9", "me@example.com", FakeBrowser)

    async def collect():
        out = []
        resp = ph_chat._alpaca_connect_stream("u9", "x")  # 'x' is a 'password' here; FakeBrowser not used
        async for chunk in resp.body_iterator:
            out.append(chunk if isinstance(chunk, str) else chunk.decode())
        return "".join(out)
    monkeypatch.setattr(ac, "AlpacaBrowser", lambda: FakeBrowser())
    body = asyncio.run(collect())
    assert "secret_prompt" in body and "otp" in body
    assert saved == []
