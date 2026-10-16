"""Admin running-strategies + user-activity view (/admin/running)."""
from datetime import datetime, timedelta, timezone

from starlette.testclient import TestClient

from engine import admin_running as ar, rbac
from engine.web import ph_admin

_REAL_RUNNING = ar.running
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


def hb(decision="renew", ago=timedelta(hours=14), instance="server"):
    return {"runner_key": "k", "instance": instance, "last_decision": decision,
            "last_acted_at": NOW - ago, "last_pass_at": NOW - ago}


def test_runner_key():
    assert ar.runner_key("live", "822120655", "ua43796") == "user-btd:822120655:ua43796"
    assert ar.runner_key("paper", "acc", "ua1") == "user-btd:acc:ua1:paper"
    assert ar.runner_key("live", None, "x") is None


def test_pending_runner_with_heartbeat_reads_running():
    assert ar.effective_status("pending_runner", hb(), NOW) == "running"
    assert ar.effective_status("pending_runner", hb(ago=timedelta(days=6)), NOW) == "pending_runner"
    assert ar.effective_status("pending_runner", hb("standby"), NOW) == "pending_runner"
    assert ar.effective_status("pending_runner", None, NOW) == "pending_runner"
    assert ar.effective_status("paused", hb(), NOW) == "paused"
    assert ar.effective_status("deactivated", hb(), NOW) == "deactivated"


def test_best_heartbeat_prefers_acting_instance():
    standby = {"instance": "mac", "last_decision": "standby", "last_acted_at": None, "last_pass_at": NOW}
    best = ar.best_heartbeat([standby, hb()])
    assert best["instance"] == "server"
    assert "idle" in ar.runner_note(best, NOW)


def _fake_execute(sql, params=None):
    if "FROM alpatrade.user_strategy_activations a\nJOIN" in sql:
        return [{"id": 4, "email": "k@x", "display_name": "Kairi", "user_strategy_id": 39, "strategy": "Mag-7 clone",
                 "mode": "live", "account_ref": "822120655", "cid_prefix": "ua43796", "allocation_usd": 670,
                 "cash_only": True, "status": "pending_runner", "job_id": None, "confirmed_at": None,
                 "created_at": NOW, "updated_at": NOW},
                {"id": 6, "email": "j@x", "display_name": "J", "user_strategy_id": 37, "strategy": "Old",
                 "mode": "paper", "account_ref": "a", "cid_prefix": "ucb", "allocation_usd": 1, "cash_only": True,
                 "status": "deactivated", "job_id": None, "confirmed_at": None, "created_at": NOW, "updated_at": NOW}]
    if "live_runner_heartbeats" in sql:
        return [{**hb(), "runner_key": "user-btd:822120655:ua43796"},
                {**hb(), "runner_key": "buy_the_dip_mag7_minhold_live:885504372"}]
    if "live_runner_state" in sql:
        return [{"runner_key": "buy_the_dip_mag7_minhold_live:885504372", "run_id": "r1", "lease_holder": "server",
                 "lease_expires_at": NOW, "created_at": NOW, "strategy": "Mag-7 BTD min-hold 3d",
                 "config": {"position_size": 0.142857}, "email": "kaljuvee@gmail.com", "display_name": "Julian"}]
    if "FROM alpatrade.trades" in sql:
        return [{"run_id": "r1", "last_trade": NOW - timedelta(days=6), "n": 15}]
    raise RuntimeError("unexpected")


def test_running_rows_active_filter_and_system():
    rows = ar.running(_fake_execute, NOW)["rows"]
    assert [r["kind"] for r in rows] == ["user", "system"]
    assert rows[0]["status"] == "running" and rows[0]["db_status"] == "pending_runner"
    assert rows[1]["account"] == "885504372" and rows[1]["trades"] == 15 and rows[1]["status"] == "running"
    assert len(ar.running(_fake_execute, NOW, include_all=True)["rows"]) == 3


def test_activity_isolates_failures():
    def ex(sql, params=None):
        if "UNION ALL" in sql:
            raise RuntimeError("boom")
        return []
    a = ar.activity(ex)
    assert a["users"] == [] and a["events"] is None


def _client(monkeypatch, user, admin):
    from fasthtml.common import fast_app
    app, rt = fast_app(secret_key="t")
    monkeypatch.setattr(ph_admin, "_user", lambda s: user)
    monkeypatch.setattr(rbac, "is_admin", lambda u: admin)
    monkeypatch.setattr(ar, "running", lambda include_all=False: _REAL_RUNNING(_fake_execute, NOW, include_all))
    monkeypatch.setattr(ar, "activity", lambda: {"users": [{
        "display_name": "Kairi", "email": "k@x", "role": "user", "created_at": NOW, "last_login_at": NOW,
        "logins_7d": 2, "logins_30d": 5, "has_keys": True, "strategies": 1, "clones": 1, "activations": 2,
        "active_activations": 2}], "events": [{"at": NOW, "email": "k@x", "kind": "login", "detail": "google"}]})
    ph_admin.register(app, rt)
    return TestClient(app, follow_redirects=False)


def test_admin_running_gates_and_renders(monkeypatch):
    assert _client(monkeypatch, None, False).get("/admin/running").headers["location"].startswith("/signin")
    assert _client(monkeypatch, {"user_id": "u", "email": "a@b"}, False).get("/admin/running").status_code == 403
    c = _client(monkeypatch, {"user_id": "u", "email": "kaljuvee@gmail.com"}, True)
    r = c.get("/admin/running")
    assert r.status_code == 200 and "Running strategies (2)" in r.text and "Kairi" in r.text
    assert "db: pending_runner" in r.text and "885504372" in r.text and "Recent events" in r.text
    assert "Running strategies (3)" in c.get("/admin/running?all=1").text


def test_last_trade_uses_runner_state_when_trades_lag():
    from datetime import datetime, timezone
    from engine.admin_running import state_last_entry, _latest
    st = {"last_entry": {"TSLA": "2026-10-13"}, "positions": {"NVDA": {"entry_date": "2026-10-15"}},
          "sleeves": {"semi": {"last_entry": {"MU": "2026-10-15"}, "positions": {}}}}
    d = state_last_entry(st)
    assert d == datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert _latest(datetime(2026, 10, 9, 19, 57, tzinfo=timezone.utc), d) == d
    assert state_last_entry(None) is None and state_last_entry("not json") is None
