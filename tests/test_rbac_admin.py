"""RBAC role resolution, admin gate, analytics snapshot and admin page render."""
from datetime import datetime, timezone

from starlette.testclient import TestClient

from engine import admin_analytics, rbac
from engine.web import ph_admin


def test_normalize_role():
    assert rbac.normalize_role("user", is_admin=True) == "admin"
    assert rbac.normalize_role("user", team_id=3) == "member"
    assert rbac.normalize_role("bogus") == "user"
    assert rbac.normalize_role("member") == "member"


def test_role_of_falls_back_without_db(monkeypatch):
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(rbac, "ensure_schema", boom)
    assert rbac.role_of({"user_id": "u", "is_admin": True}) == "admin"
    assert rbac.role_of({"user_id": "u"}) == "user"
    assert rbac.role_of(None) == "user"


def test_migration_seeds_julian_admin():
    sql = rbac._SQL.read_text()
    assert "kaljuvee@gmail.com" in sql and "CREATE TABLE IF NOT EXISTS alpatrade.teams" in sql
    assert "role IN ('admin', 'member', 'user')" in sql and "user_logins" in sql


def test_snapshot_isolates_failures():
    def execute(sql):
        if "user_logins" in sql:
            raise RuntimeError("missing table")
        if "GROUP BY" in sql:
            return [("x", 1)]
        return [(7,)]
    m = admin_analytics.snapshot(execute)
    assert m["total_users"] == 7 and m["logins_7d"] is None and m["roles"] == [("x", 1)]


def test_render_stamp_three_zones():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    html = ph_admin.render({"total_users": 12, "activations": [("paper", 4, 3), ("live", 1, 1)],
                            "referrals": [(5, 2, 2)]}, now=now)
    assert "08:00 ET" in html and "13:00 UK" in html and "15:00 Tallinn" in html
    assert "<b>12</b><span>Total users" in html and "<b>4</b><span>Paper activations" in html


def _client(monkeypatch, user, admin):
    from fasthtml.common import fast_app
    app, rt = fast_app(secret_key="t")
    monkeypatch.setattr(ph_admin, "_user", lambda s: user)
    monkeypatch.setattr(rbac, "is_admin", lambda u: admin)
    monkeypatch.setattr(admin_analytics, "snapshot", lambda: {"total_users": 1})
    ph_admin.register(app, rt)
    return TestClient(app, follow_redirects=False)


def test_admin_route_gates(monkeypatch):
    assert _client(monkeypatch, None, False).get("/admin").headers["location"].startswith("/signin")
    assert _client(monkeypatch, {"user_id": "u", "email": "a@b"}, False).get("/admin").headers["location"] == "/dashboard"
    r = _client(monkeypatch, {"user_id": "u", "email": "a@b", "is_admin": True}, True).get("/admin")
    assert r.status_code == 200 and "user analytics" in r.text
