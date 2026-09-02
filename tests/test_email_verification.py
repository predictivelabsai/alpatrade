"""Email verification: token lifecycle (create/verify/consume-once), the
shell banner, and the dev-mode fallback that logs the link when Postmark is
unconfigured. DB access is faked at the pool boundary."""

import logging
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastcore.xml import to_xml

import engine.web.ph_auth as ph_auth
from engine.web.ph_layout import page, _verify_banner

FAKE_USER = {"user_id": "u-1", "email": "user@example.com"}


# --- fake DB plumbing ---------------------------------------------------------

class FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.rowcount = 1  # UPDATEs report success; SELECTs use fetchone()

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self):
        self.queries = []
        self.select_user_id_rows = []

    def execute(self, sql, params=None):
        self.queries.append((str(sql), params))
        if "SELECT t.user_id" in str(sql):
            return FakeResult(self.select_user_id_rows)
        return FakeResult([])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    def __init__(self):
        self.session = FakeSession()

    def get_session(self):
        return self.session


@pytest.fixture()
def fake_db(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr("utils.db.db_pool.DatabasePool", lambda: pool)
    return pool.session


# --- token lifecycle ----------------------------------------------------------

def test_create_token_inserts_with_24h_expiry(fake_db):
    from engine.auth import create_email_verification_token

    token = create_email_verification_token("u-1")

    assert token and len(token) > 32
    insert = next(q for q in fake_db.queries if "INSERT INTO" in q[0])
    assert insert[1]["user_id"] == "u-1"
    assert insert[1]["expires_at"] - datetime.now(timezone.utc) > timedelta(hours=23)


def test_verify_consumes_token_and_marks_user_verified(fake_db):
    from engine.auth import verify_and_consume_email_token

    fake_db.select_user_id_rows = [("u-1",)]
    user_id = verify_and_consume_email_token("tok")

    assert user_id == "u-1"
    updates = [q for q in fake_db.queries if "UPDATE" in q[0]]
    assert len(updates) == 2  # token consumed + email_verified_at stamped


def test_verify_rejects_invalid_token_without_writes(fake_db):
    from engine.auth import verify_and_consume_email_token

    fake_db.select_user_id_rows = []
    assert verify_and_consume_email_token("bad") is None
    assert not [q for q in fake_db.queries if "UPDATE" in q[0]]


def test_mark_email_verified_is_idempotent(fake_db):
    from engine.auth import mark_email_verified

    assert mark_email_verified("u-1") is True
    update = fake_db.queries[-1]
    assert "COALESCE(email_verified_at" in update[0]


# --- shell banner -------------------------------------------------------------

def test_banner_renders_resend_action():
    html = to_xml(_verify_banner(FAKE_USER))

    assert "Verify your email" in html
    assert "/verify/resend" in html


def test_page_shows_banner_only_for_unverified_user():
    unverified = dict(FAKE_USER, email_verified_at=None)
    verified = dict(FAKE_USER, email_verified_at=datetime(2026, 1, 1,
                                                          tzinfo=timezone.utc))

    assert "verify-banner" in to_xml(page("guide", mock.Mock(), user=unverified))
    assert "verify-banner" not in to_xml(page("guide", mock.Mock(), user=verified))
    assert "verify-banner" not in to_xml(page("guide", mock.Mock(), user=None))


# --- dev-mode send ------------------------------------------------------------

class _FakeURL:
    scheme = "http"
    netloc = "testserver"


class _FakeRequest:
    headers = {}
    url = _FakeURL()


def test_send_verification_email_logs_link_when_postmark_down(fake_db, caplog):
    with mock.patch("engine.web.ph_auth.create_email_verification_token",
                    return_value="tok123"), \
            mock.patch("utils.email_util.send_email_to", return_value=False):
        with caplog.at_level(logging.WARNING):
            ph_auth._send_verification_email(FAKE_USER, _FakeRequest())

    assert any("/verify?token=tok123" in r.message for r in caplog.records)


def test_send_verification_email_calls_postmark_when_configured(fake_db):
    with mock.patch("engine.web.ph_auth.create_email_verification_token",
                    return_value="tok123"), \
            mock.patch("utils.email_util.send_email_to", return_value=True) as send:
        ph_auth._send_verification_email(FAKE_USER, _FakeRequest())

    send.assert_called_once()
    assert send.call_args.args[0] == "user@example.com"
    assert "/verify?token=tok123" in send.call_args.args[2]