"""In-memory event scheduler + broker-side exits for the live BTD runner (pure / simulated).

No network, no DB: the calendar, runner and lease are fakes. Covers event times (normal day,
early close, roles), due/missed/grace logic, holiday skip, heartbeat cadence, the failover
catch-up of the open event, config caching/reload, broker-exit eligibility (never on the buy
date) and order construction, and a simulated lease takeover with the real decide() policy.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.live_btd_config import ConfigResult, DEFAULT_EXECUTION, DEFAULT_PARAMS  # noqa: E402
from utils.live_btd_exits import (exit_eligible, exit_prices, order_fill, own_open_exits,  # noqa: E402
                                  plan_broker_exits, split_qty)
from utils.live_btd_scheduler import (ConfigCache, Event, Scheduler, due_events, heartbeat_due,  # noqa: E402
                                      needs_open_catchup, session_events)
from utils.live_btd_state import LeaseResult, decide  # noqa: E402

ET = ZoneInfo("America/New_York")
THU = date(2026, 10, 1)


def sess(day=THU, close=(16, 0)):
    return {"date": day, "open": datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET),
            "close": datetime(day.year, day.month, day.day, *close, tzinfo=ET)}


def at(h, m, s=0, day=THU):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=ET)


def cfg(version=1, db_ok=True, **p):
    return ConfigResult({**DEFAULT_PARAMS, "pos_frac": 0.142857, **p}, DEFAULT_EXECUTION, {}, "test",
                        db_ok, 1 if db_ok else None, version if db_ok else None, "x")


def times(evs):
    return {e.key: e.at.astimezone(ET).strftime("%H:%M:%S") for e in evs}


# ------------------------------------------------------------------ event times
def test_regular_session_event_times():
    assert times(session_events(sess())) == {
        "open": "09:31:00", "entry-15": "15:45:45", "entry-10": "15:50:00", "entry-5": "15:54:15",
        "close": "15:57:15", "post": "16:03:00"}


def test_early_close_shifts_with_the_calendar_close():
    t = times(session_events(sess(close=(13, 0))))
    assert t["entry-15"] == "12:45:45" and t["close"] == "12:57:15" and t["post"] == "13:03:00"
    assert t["open"] == "09:31:00"


@pytest.mark.parametrize("role", ["primary", "backup", "tertiary"])
def test_every_role_fires_inside_the_runner_windows(role):
    s = sess()
    for e in session_events(s, role=role):
        mins = (s["close"] - e.at).total_seconds() / 60
        if e.kind == "entry": assert 5 <= mins <= 15, (role, e)
        if e.kind == "close": assert 2 <= mins <= 15, (role, e)
    off = {e.key: e.at for e in session_events(s, role=role)}
    base = {e.key: e.at for e in session_events(s)}
    assert all(off[k] >= base[k] for k in base)  # backups never ahead of the primary


# ------------------------------------------------------------------ due / missed / grace
def test_due_missed_and_done():
    s = sess(); evs = session_events(s)
    assert due_events(evs, set(), at(9, 30, 59), s) == ([], [])
    due, missed = due_events(evs, set(), at(9, 31, 2), s)
    assert [e.key for e in due] == ["open"] and missed == []
    assert due_events(evs, {"open"}, at(9, 31, 2), s) == ([], [])
    due, _ = due_events(evs, set(), at(14, 0), s)        # open may catch up until close - 30 min
    assert [e.key for e in due] == ["open"]
    due, missed = due_events(evs, {"open"}, at(15, 49), s)
    assert [e.key for e in due] == ["entry-15"] and missed == []
    due, missed = due_events(evs, {"open", "entry-10"}, at(15, 52), s)
    assert due == [] and [e.key for e in missed] == ["entry-15"]   # 4-min grace
    due, missed = due_events(evs, {"open", "entry-15", "entry-10", "entry-5"}, at(15, 58, 5), s)
    assert due == [] and [e.key for e in missed] == ["close"]        # never after close - 2 min


def test_heartbeat_window_and_cadence():
    s = sess()
    assert not heartbeat_due(s, at(8, 59), None)
    assert heartbeat_due(s, at(9, 0), None)
    assert not heartbeat_due(s, at(9, 2), at(9, 0))
    assert heartbeat_due(s, at(9, 3), at(9, 0))
    assert heartbeat_due(s, at(16, 5), None) and not heartbeat_due(s, at(16, 6), None)


def test_open_catchup_only_for_holder_without_open_today():
    s = sess(); ev = Event(at(9, 31), "open", "open")
    held = {"positions": {"AAPL": {}}, "last_open_event": "2026-09-30"}
    assert needs_open_catchup(held, THU, at(11, 0), s, ev)
    assert not needs_open_catchup({**held, "last_open_event": "2026-10-01"}, THU, at(11, 0), s, ev)
    assert not needs_open_catchup({"positions": {}}, THU, at(11, 0), s, ev)
    assert not needs_open_catchup(held, THU, at(15, 40), s, ev)
    assert not needs_open_catchup(held, THU, at(9, 20), s, ev)


# ------------------------------------------------------------------ simulated day
class FakeRunner:
    def __init__(self, role="primary", act=True, execute=True, state=None):
        self.role, self.instance, self.execute = role, role, execute
        self.a = SimpleNamespace(lease_ttl_min=8.0, takeover_min=12.0)
        self.calls, self.hb, self._act, self._state = [], [], act, state or {"positions": {}}

    def run(self, events, c):
        self.calls.append((tuple(events), c.version))
        return SimpleNamespace(acted=True, reason="", code=0, orders=[],
                               lease=LeaseResult(ok=True, act=self._act))

    def heartbeat(self):
        self.hb.append(1)
        return LeaseResult(ok=True, act=self._act, reason="renew", state=self._state)


class FakeCal:
    def __init__(self, cal): self.cal, self.n = cal, 0

    def get_calendar(self, start, end):
        self.n += 1
        return [c for c in self.cal if start <= c["date"] <= end]


def make(cal, **kw):
    r = FakeRunner(**kw)
    cache = ConfigCache(lambda: cfg(), lambda: 1, log_fn=lambda c, w: None)
    return r, Scheduler(r, cache, FakeCal(cal), heartbeat_min=3, poll_s=5, event_timeout_s=30)


def walk(sch, start, end, step=5):
    t, ran = start, []
    while t <= end:
        ran += [(t.strftime("%H:%M:%S"), k) for k in sch.tick(t)]
        t += timedelta(seconds=step)
    return ran


def test_full_day_runs_each_event_once_and_heartbeats_every_3_min():
    r, sch = make([{"date": "2026-10-01", "open": "09:30", "close": "16:00"}])
    ran = walk(sch, at(8, 55), at(16, 10))
    events = [(t, k) for t, k in ran if k != "heartbeat"]
    assert [k for _, k in events] == ["open", "entry-15", "entry-10", "entry-5", "close", "post"]
    assert [t for _, t in [(k, t) for t, k in events]] == [
        "09:31:00", "15:45:45", "15:50:00", "15:54:15", "15:57:15", "16:03:00"]
    assert [c[0] for c in r.calls] == [("open",), ("entry",), ("entry",), ("entry",), ("close",), ("post",)]
    hb = [t for t, k in ran if k == "heartbeat"]
    assert hb[0] == "09:00:00" and hb[-1] >= "16:00:00"
    assert 120 <= len(hb) <= 145                     # ~every 3 min for 7 h, no market scans
    assert sch.calendar.n == 1                       # one calendar call per day (cached)


def test_holiday_and_weekend_skip_everything():
    r, sch = make([])                                # Alpaca calendar: no session that day
    assert walk(sch, at(9, 0), at(16, 30), step=60) == []
    assert r.calls == [] and r.hb == [] and sch.calendar.n == 1


def test_standby_backup_never_catches_up_open():
    r, sch = make([{"date": "2026-10-01", "open": "09:30", "close": "16:00"}], role="backup", act=False,
                  state={"positions": {"AAPL": {}}})
    walk(sch, at(10, 0), at(10, 10))
    assert ("open",) in [c[0] for c in r.calls]      # the regular open event still runs (lease decides)
    assert [c for c in r.calls if c[0] == ("open",)].__len__() == 1


def test_takeover_holder_catches_up_missed_open_once():
    r, sch = make([{"date": "2026-10-01", "open": "09:30", "close": "16:00"}], role="backup", act=True,
                  state={"positions": {"AAPL": {}}, "last_open_event": "2026-09-30"})
    sch._done.add((THU, "open"))                     # the open event ran while standing by
    ran = walk(sch, at(11, 0), at(11, 4))
    assert [k for _, k in ran].count("open-catchup") == 1
    assert [k for _, k in walk(sch, at(11, 5), at(11, 10))].count("open-catchup") == 0


def test_dry_run_never_catches_up():
    r, sch = make([{"date": "2026-10-01", "open": "09:30", "close": "16:00"}], execute=False,
                  state={"positions": {"AAPL": {}}, "last_open_event": "2026-09-30"})
    sch._done.add((THU, "open"))
    assert "open-catchup" not in [k for _, k in walk(sch, at(11, 0), at(11, 4))]


# ------------------------------------------------------------------ config cache
def test_config_loaded_once_and_reloaded_only_on_version_change_or_sighup():
    loads, version = [], {"v": 1}
    cache = ConfigCache(lambda: loads.append(1) or cfg(version["v"]), lambda: version["v"],
                        log_fn=lambda c, w: None)
    t0 = at(9, 0)
    assert cache.get(t0).version == 1 and len(loads) == 1
    for m in range(1, 14):
        cache.get(t0 + timedelta(minutes=m))
    assert len(loads) == 1                            # no re-reads between checks
    version["v"] = 2
    assert cache.get(t0 + timedelta(minutes=14)).version == 1    # next check not due yet
    assert cache.get(t0 + timedelta(minutes=15)).version == 2 and len(loads) == 2
    version["v"] = 3
    assert cache.get(t0 + timedelta(minutes=16), at_event=True).version == 3   # events check now
    cache.force = True
    cache.get(t0 + timedelta(minutes=17)); assert len(loads) == 4 and not cache.force


def test_config_check_failure_keeps_cache_and_defaults_retry():
    def boom(): raise OSError("db down")
    cache = ConfigCache(lambda: cfg(1), boom, log_fn=lambda c, w: None)
    assert cache.get(at(9, 0)).version == 1
    assert cache.get(at(9, 30), at_event=True).version == 1
    loads = []
    c2 = ConfigCache(lambda: loads.append(1) or cfg(db_ok=False), lambda: None, log_fn=lambda c, w: None)
    c2.get(at(9, 0)); c2.get(at(9, 1)); c2.get(at(9, 2))
    assert len(loads) == 3                            # not from the DB -> retried every tick


# ------------------------------------------------------------------ broker-side exits
def test_exit_eligibility_never_on_buy_date():
    d = date(2026, 9, 28)
    assert not exit_eligible(d, d, 0)                 # same day, even with min-hold 0
    assert not exit_eligible(d, d + timedelta(days=2), 3)
    assert exit_eligible(d, d + timedelta(days=3), 3)
    assert exit_eligible(d, d + timedelta(days=1), 1)
    assert not exit_eligible(d, d - timedelta(days=1), 0)


def test_split_and_prices():
    assert split_qty("1.184190558") == (1, 0.184190558)
    assert split_qty("2") == (2, 0.0) and split_qty("0.543220683") == (0, 0.543220683)
    assert exit_prices(329.474, 8, 1.5) == (355.84, 324.53)   # TP rounded up, stop down


def test_plan_whole_plus_fraction_is_oco_plus_stop():
    p = plan_broker_exits("AAPL", "1.184190558", 329.474, 8, 1.5, THU, plpc_pct=1.0)
    assert p["action"] == "orders"
    oco, stop = p["orders"]
    assert oco["order_class"] == "oco" and oco["qty"] == "1" and oco["type"] == "limit"
    assert oco["take_profit"] == {"limit_price": "355.84"} and oco["stop_loss"] == {"stop_price": "324.53"}
    assert oco["client_order_id"] == "btdtp-AAPL-20261001" and oco["time_in_force"] == "day"
    assert stop == {"symbol": "AAPL", "qty": "0.184190558", "side": "sell", "type": "stop",
                    "stop_price": "324.53", "time_in_force": "day", "client_order_id": "btdsl-AAPL-20261001"}


def test_plan_fraction_only_is_stop_and_hits_are_market():
    p = plan_broker_exits("META", "0.543220683", 717.388, 8, 1.5, THU, plpc_pct=0.0)
    assert [o["type"] for o in p["orders"]] == ["stop"] and p["orders"][0]["qty"] == "0.543220683"
    assert plan_broker_exits("X", "2", 100, 8, 1.5, THU, plpc_pct=8.0)["action"] == "market"
    m = plan_broker_exits("X", "2", 100, 8, 1.5, THU, plpc_pct=-1.5)
    assert m["action"] == "market" and m["orders"][0]["client_order_id"] == "btdx-X-20261001"


def test_own_exits_and_oco_leg_fill():
    oo = [{"symbol": "A", "side": "sell", "client_order_id": "btdtp-A-20261001"},
          {"symbol": "A", "side": "sell", "client_order_id": "manual-1"},
          {"symbol": "B", "side": "sell", "client_order_id": "btdsl-B-20261001"}]
    assert [o["client_order_id"] for o in own_open_exits(oo, "A")] == ["btdtp-A-20261001"]
    o = {"status": "canceled", "filled_qty": "0", "legs": [
        {"status": "filled", "filled_qty": "1", "filled_avg_price": "98.4"}]}
    assert order_fill(o) == (1.0, 98.4, True)
    assert order_fill({"status": "new", "filled_qty": "0", "legs": []})[2] is False


# ------------------------------------------------------------------ simulated lease takeover
def test_backup_takes_over_within_takeover_after_primary_dies_with_3min_heartbeats():
    """Primary heartbeats every 3 min then dies at 11:00; backup heartbeats every 3 min too.
    With the real decide() policy (8-min TTL, 12-min takeover) the backup acts at the first
    heartbeat after 11:12 and never before."""
    ttl, takeover = timedelta(minutes=8), 720
    holder, expires, primary_last = "hp", None, None
    first_backup_act = None
    t = at(9, 0)
    while t <= at(12, 0):
        if t < at(11, 0) and (t - at(9, 0)).seconds % 180 == 0:
            r = decide(me="hp", role="primary", now=t, lease_holder=holder, lease_expires_at=expires,
                       higher_heartbeats={}, takeover_s=takeover, holdoff=False)
            assert r.act
            holder, expires, primary_last = "hp", t + ttl, t
        if (t - at(9, 0, 10)).seconds % 180 == 0 and t >= at(9, 0, 10):
            r = decide(me="mac", role="backup", now=t, lease_holder=holder, lease_expires_at=expires,
                       higher_heartbeats={"primary": primary_last}, takeover_s=takeover,
                       holdoff=t < at(9, 12))
            if r.act:
                holder, expires = "mac", t + ttl
                first_backup_act = first_backup_act or t
        t += timedelta(seconds=10)
    assert first_backup_act is not None
    assert at(11, 9) < first_backup_act <= at(11, 15, 10)
