"""Failover for the live BTD runner: DB lease/heartbeat protocol (HP primary, Mac backup).

Pure policy tests always run. The PostgreSQL tests run against an isolated, freshly
created database when LIVE_BTD_TEST_DATABASE_URL (or PREMARKET_TEST_DATABASE_URL) names a
loopback server (CI provides one); the database is dropped afterwards.
"""
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.live_btd_state import (  # noqa: E402
    RunnerStateStore, adopt_runner_position, alpaca_symbol_busy, decide, degraded_policy,
    empty_state, in_backup_holdoff, in_session_gate, merge_dirty_cache)

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 9, 28, 19, 0, tzinfo=timezone.utc)  # Mon 15:00 ET
M = timedelta(minutes=1)


# ------------------------------------------------------------------ pure policy
def d(**kw):
    base = dict(me="mac", role="backup", now=T0, lease_holder=None, lease_expires_at=None,
                primary_last_pass=None, takeover_s=720, holdoff=False)
    base.update(kw)
    return decide(**base)


def test_foreign_live_lease_always_blocks():
    for role in ("primary", "backup"):
        r = d(me="x", role=role, lease_holder="other", lease_expires_at=T0 + M)
        assert not r.act and "lease held by other" in r.reason


def test_primary_takes_free_or_expired_lease_and_renews_own():
    assert d(me="hp", role="primary").act
    assert d(me="hp", role="primary", lease_holder="mac", lease_expires_at=T0 - M).act
    r = d(me="hp", role="primary", lease_holder="hp", lease_expires_at=T0 + M)
    assert r.act and r.code == "renew"


def test_backup_stands_by_while_primary_heartbeat_fresh():
    r = d(primary_last_pass=T0 - 11 * M)
    assert not r.act and not r.release


def test_backup_takes_over_when_primary_stale_or_never_seen():
    assert d(primary_last_pass=T0 - 13 * M).code == "takeover"
    assert d(primary_last_pass=None).act


def test_backup_renews_own_lease_while_primary_stale_and_hands_back_when_primary_returns():
    assert d(lease_holder="mac", lease_expires_at=T0 + M, primary_last_pass=T0 - 30 * M).code == "renew"
    r = d(lease_holder="mac", lease_expires_at=T0 + M, primary_last_pass=T0 - M)
    assert not r.act and r.release and r.code == "handback"


def test_backup_holdoff_at_session_start():
    assert d(primary_last_pass=T0 - 20 * 60 * M, holdoff=True).code == "holdoff"
    at = lambda h, m: datetime(2026, 9, 28, h, m, tzinfo=ET)  # noqa: E731
    assert in_backup_holdoff(at(9, 5)) and not in_backup_holdoff(at(9, 13)) and not in_backup_holdoff(at(8, 55))


def test_session_gate():
    at = lambda day, h, m: datetime(2026, 9, day, h, m, tzinfo=ET)  # noqa: E731
    assert in_session_gate(at(28, 9, 0)) and in_session_gate(at(28, 16, 4))
    assert not in_session_gate(at(28, 8, 59)) and not in_session_gate(at(28, 16, 5))
    assert not in_session_gate(at(26, 12, 0))  # Saturday


def test_degraded_policy_never_buys_and_only_last_leader_exits():
    assert degraded_policy({"acted_last": True}) == {**degraded_policy({"acted_last": True}), "entries": False, "exits": True}
    p = degraded_policy({"acted_last": False})
    assert p["entries"] is False and p["exits"] is False
    assert degraded_policy({})["exits"] is False


def test_merge_dirty_cache_unions_positions_pending_last_entry():
    db = empty_state("r1"); db["positions"]["AAPL"] = {"entry_date": "2026-09-21"}
    db["rec"]["pending"] = [{"cid": "a"}]; db["last_entry"] = {"AAPL": "2026-09-21"}
    cache = empty_state("r1"); cache["positions"]["NVDA"] = {"entry_date": "2026-09-24"}
    cache["rec"]["pending"] = [{"cid": "a"}, {"cid": "btdx-AAPL-20260925"}]
    cache["last_entry"] = {"AAPL": "2026-09-20", "NVDA": "2026-09-24"}
    m = merge_dirty_cache(db, cache)
    assert set(m["positions"]) == {"AAPL", "NVDA"}
    assert [x["cid"] for x in m["rec"]["pending"]] == ["a", "btdx-AAPL-20260925"]
    assert m["last_entry"] == {"AAPL": "2026-09-21", "NVDA": "2026-09-24"}
    assert db["rec"]["pending"] == [{"cid": "a"}]  # input not mutated


class _HTTPErr(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.response = type("R", (), {"status_code": code})()


def fake_get(routes):
    def get(url, **params):
        key = url.rsplit("/v2/", 1)[1]
        v = routes.get(key)
        if callable(v):
            v = v(params)
        if isinstance(v, Exception):
            raise v
        return v
    return get


def test_prebuy_check_blocks_position_open_order_and_used_client_id():
    free = {"positions/NVDA": _HTTPErr(404), "orders": [], "orders:by_client_order_id": _HTTPErr(404)}
    assert alpaca_symbol_busy(fake_get(free), "B", "NVDA", "btd-NVDA-20260928") is None
    assert "position" in alpaca_symbol_busy(fake_get({**free, "positions/NVDA": {"symbol": "NVDA"}}), "B", "NVDA", "c")
    assert "open order" in alpaca_symbol_busy(fake_get({**free, "orders": [{"symbol": "NVDA"}]}), "B", "NVDA", "c")
    assert "already exists" in alpaca_symbol_busy(
        fake_get({**free, "orders:by_client_order_id": {"status": "filled"}}), "B", "NVDA", "c")


def test_prebuy_check_fails_closed_on_errors():
    assert "fail closed" in alpaca_symbol_busy(fake_get({"positions/NVDA": _HTTPErr(500)}), "B", "NVDA", "c")
    assert "fail closed" in alpaca_symbol_busy(
        fake_get({"positions/NVDA": _HTTPErr(404), "orders": RuntimeError("timeout")}), "B", "NVDA", "c")


def test_adopt_only_runner_entries():
    runner = [{"symbol": "NVDA", "side": "buy", "filled_qty": "1.7", "client_order_id": "btd-NVDA-20260925",
               "notional": "389.39"}]
    m = adopt_runner_position(fake_get({"orders": runner}), "B", "NVDA")
    assert m == {"entry_date": "2026-09-25", "client_id": "btd-NVDA-20260925", "notional": 389.39, "adopted": True}
    manual = [{"symbol": "NVDA", "side": "buy", "filled_qty": "2", "client_order_id": "web-123"}] + runner
    assert adopt_runner_position(fake_get({"orders": manual}), "B", "NVDA") is None
    assert adopt_runner_position(fake_get({"orders": RuntimeError("x")}), "B", "NVDA") is None


def test_unreachable_db_is_reported_not_raised():
    s = RunnerStateStore("postgresql://u:p@127.0.0.1:1/x", "k", instance="mac", role="backup")
    r = s.acquire()
    assert not r.ok and not r.act and "DB unreachable" in r.reason
    assert not s.peek().ok and s.save({"positions": {}}) is False


# ------------------------------------------------------------- PostgreSQL protocol
@pytest.fixture(scope="module")
def pg_url():
    value = os.getenv("LIVE_BTD_TEST_DATABASE_URL") or os.getenv("PREMARKET_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set LIVE_BTD_TEST_DATABASE_URL for isolated PostgreSQL failover tests.")
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("The failover integration tests only accept a loopback database server.")
    name = "live_btd_failover_" + uuid.uuid4().hex[:12]
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


def stores(url, key=None):
    key = key or "test:" + uuid.uuid4().hex[:8]
    hp = RunnerStateStore(url, key, instance="hp", role="primary", host="julian-HP")
    mac = RunnerStateStore(url, key, instance="mac", role="backup", host="Mac.home")
    return hp, mac


def db_now(store):
    from sqlalchemy import text
    with store._engine.connect() as c:
        return c.execute(text("SELECT now()")).scalar()


def test_pg_missing_row_never_acts_then_seed(pg_url):
    hp, mac = stores(pg_url)
    r = hp.acquire()
    assert r.ok and r.missing and not r.act
    assert hp.seed(empty_state("abced9a9"), "abced9a9")
    assert not hp.seed(empty_state("other"), "other")  # no silent overwrite
    p = mac.peek()
    assert p.ok and p.run_id == "abced9a9" and p.state["positions"] == {} and p.state["rec"]["pending"] == []


def test_pg_full_failover_cycle(pg_url):
    hp, mac = stores(pg_url)
    hp.seed(empty_state("run-1"), "run-1")
    t = db_now(hp)
    et = lambda x: x.astimezone(ET).replace(hour=15)  # noqa: E731 - mid-session, no hold-off
    assert hp.acquire(t, et(t)).act                                   # primary acts
    assert not mac.acquire(t + M, et(t)).act                          # lease held by hp
    r = mac.acquire(t + 13 * M, et(t))                                # hp silent 13 min, lease expired
    assert r.act and r.info["decision"] == "takeover"
    s = r.state; s["positions"]["NVDA"] = {"entry_date": "2026-09-28", "client_id": "btd-NVDA-20260928"}
    assert mac.save(s)
    assert not hp.save(s)                                             # non-holder can't write state
    r = hp.acquire(t + 14 * M, et(t))                                 # hp back: stands by, heartbeat
    assert not r.act and "lease held by mac" in r.reason
    r = mac.acquire(t + 15 * M, et(t))                                # mac sees hp fresh -> hands back
    assert not r.act and r.info["decision"] == "handback"
    r = hp.acquire(t + 16 * M, et(t))
    assert r.act and "NVDA" in r.state["positions"]                   # hp resumes with mac's positions
    assert not mac.acquire(t + 17 * M, et(t)).act
    hbs = {h["instance"]: h for h in mac.peek(t + 17 * M).info["heartbeats"]}
    assert hbs["hp"]["role"] == "primary" and hbs["mac"]["last_decision"] == "standby"


def test_pg_backup_holdoff_and_dry_run_peek_writes_nothing(pg_url):
    hp, mac = stores(pg_url)
    hp.seed(empty_state("r"), "r")
    t = db_now(mac)
    p = mac.peek(t)
    assert p.act and p.info["heartbeats"] == []                       # would take over, but wrote nothing
    assert mac.peek(t).info["heartbeats"] == []
    open_ = t.astimezone(ET).replace(hour=9, minute=5)
    r = mac.acquire(t, open_)
    assert not r.act and r.info["decision"] == "holdoff"


def test_pg_concurrent_acquire_exactly_one_acts(pg_url):
    for _ in range(8):
        hp, mac = stores(pg_url)
        hp.seed(empty_state("r"), "r")
        t = db_now(hp); mid = t.astimezone(ET).replace(hour=15)
        res, barrier = {}, threading.Barrier(2)

        def go(s):
            barrier.wait()
            res[s.instance] = s.acquire(t, mid)
        th = [threading.Thread(target=go, args=(s,)) for s in (hp, mac)]
        [x.start() for x in th]; [x.join() for x in th]
        assert all(r.ok for r in res.values())
        assert sum(r.act for r in res.values()) == 1, {k: v.reason for k, v in res.items()}
