"""sql/58_user_approval.sql + engine.approval against a throwaway Postgres.
Runs when APPROVAL_TEST_DATABASE_URL points at one (CI postgres service)."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL = os.getenv("APPROVAL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="APPROVAL_TEST_DATABASE_URL not set")

BOOT = """
DROP SCHEMA IF EXISTS alpatrade CASCADE; CREATE SCHEMA alpatrade;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE alpatrade.users (
    id SERIAL PRIMARY KEY, user_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255), google_id VARCHAR(255) UNIQUE,
    display_name VARCHAR(255), is_admin BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    email_verified_at TIMESTAMPTZ, role VARCHAR(16) NOT NULL DEFAULT 'user', last_login_at TIMESTAMPTZ,
    referred_by UUID);
CREATE TABLE alpatrade.user_logins (id BIGSERIAL PRIMARY KEY, user_id UUID NOT NULL, method VARCHAR(16),
    ip VARCHAR(64), user_agent VARCHAR(300), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
INSERT INTO alpatrade.users (email, display_name, google_id, role, is_admin) VALUES
    ('kaljuvee@gmail.com', 'Julian', 'g1', 'admin', TRUE),
    ('joosep.laats@gmail.com', 'Joosep', 'g2', 'admin', TRUE),
    ('trader@x.io', 'Trader', NULL, 'user', FALSE),
    ('ShastryInvest@gmail.com', 'Rupam Investment', 'g3', 'user', FALSE);
"""


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    eng = create_engine(URL)
    with eng.begin() as c:
        c.execute(text(BOOT))
    Session = sessionmaker(bind=eng)

    class Pool:
        @contextmanager
        def get_session(self):
            s = Session()
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()
    from engine import approval
    monkeypatch.setattr(approval, "_pool", lambda: Pool())
    monkeypatch.setattr(approval, "_ready", False)
    monkeypatch.setattr(approval, "_cache", {})
    monkeypatch.delenv("SIGNUP_APPROVER_EMAILS", raising=False)
    return eng, approval


def _status(eng):
    from sqlalchemy import text
    with eng.connect() as c:
        return dict(c.execute(text("SELECT lower(email), approval_status FROM alpatrade.users")).fetchall())


def test_migration_backfill_default_and_replay(db):
    from sqlalchemy import text
    eng, approval = db
    approval.ensure_schema()
    st = _status(eng)
    assert st == {"kaljuvee@gmail.com": "approved", "joosep.laats@gmail.com": "approved",
                  "trader@x.io": "approved", "shastryinvest@gmail.com": "pending"}
    with eng.begin() as c:
        assert c.execute(text("INSERT INTO alpatrade.users (email) VALUES ('new@x.io') "
                              "RETURNING approval_status")).scalar() == "pending"
        c.execute(text("UPDATE alpatrade.users SET approval_status = 'approved' "
                       "WHERE lower(email) = 'shastryinvest@gmail.com'"))
    approval._ready = False
    approval.ensure_schema()                      # replay: no data change, decisions kept
    assert _status(eng)["shastryinvest@gmail.com"] == "approved"
    with pytest.raises(Exception):
        with eng.begin() as c:
            c.execute(text("UPDATE alpatrade.users SET approval_status = 'bogus'"))


def test_review_flow(db):
    from sqlalchemy import text
    eng, approval = db
    approval.ensure_schema()
    assert approval.approvers() == ["kaljuvee@gmail.com", "joosep.laats@gmail.com"]
    assert approval.counts() == {"pending": 1, "approved": 3, "rejected": 0}
    with eng.connect() as c:
        admin = str(c.execute(text("SELECT user_id FROM alpatrade.users WHERE email = 'kaljuvee@gmail.com'")).scalar())
        rupam = str(c.execute(text("SELECT user_id FROM alpatrade.users WHERE email ILIKE 'shastry%'")).scalar())
    rows = approval.list_users("pending")
    assert [r["email"] for r in rows] == ["ShastryInvest@gmail.com"] and approval.method_label(rows[0]) == "google"
    approval.record_signup(rupam, "google", "203.0.113.9", "HeadlessChrome")
    assert approval.list_users("pending")[0]["signup_ip"] == "203.0.113.9"
    assert approval.status_of(rupam) == "pending" and approval.is_blocked(rupam)
    sent = []
    res = approval.decide(rupam, "approved", {"user_id": admin, "email": "kaljuvee@gmail.com"},
                          notify_user=True, send=lambda *a: sent.append(a) or True)
    assert res["ok"] and "Approval email sent" in res["message"] and sent[0][0] == "ShastryInvest@gmail.com"
    assert approval.status_of(rupam) == "approved"           # cache cleared by decide()
    r = approval.list_users("approved")
    assert next(x for x in r if x["user_id"] and str(x["user_id"]) == rupam)["decided_by"] == "kaljuvee@gmail.com"
    assert approval.decide(rupam, "rejected", {"user_id": admin})["ok"]
    assert approval.counts()["rejected"] == 1 and approval.block_message(rupam) == approval.REJECTED_MSG
    assert approval.set_approvers(["A@x.io", "b@y.io"], admin) == ["a@x.io", "b@y.io"]
    assert approval.approvers() == ["a@x.io", "b@y.io"]
