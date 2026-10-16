"""Protective stops (v0.47.0): every held strategy position carries a broker stop at entry x (1 - sl%)
from the session after its buy (also during the min-hold), both sleeves and user runners; the
time exit / TP plan cancels it first; hourly + pre-open checks re-place a missing one."""
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.live_btd_exits import (own_open_exits, plan_protective_stops, protective_stop_cid,  # noqa: E402
                                  stop_rejected_below, is_stop_only)
from utils.live_btd_scheduler import session_events  # noqa: E402
from utils.strategy_allocation import Sleeve  # noqa: E402

ET = ZoneInfo("America/New_York")
FRI = date(2026, 10, 16)


def pos(sym, qty="1.5", px="100", avail=None):
    return {"symbol": sym, "qty": qty, "qty_available": avail if avail is not None else qty, "avg_entry_price": px}


def test_missing_stop_planned_at_entry_minus_sl_and_flagged_overdue_in_session():
    tracked = {"NVDA": {"entry_date": "2026-10-15"}, "TSLA": {"entry_date": "2026-10-13"}}
    positions = {"NVDA": pos("NVDA", "1.720669928", "217.456"), "TSLA": pos("TSLA")}
    oo = [{"symbol": "TSLA", "side": "sell", "type": "stop", "client_order_id": "btdps-TSLA-20261016"}]
    plans = plan_protective_stops(tracked, positions, oo, today=FRI, session_day=FRI, market_open=True, sl_pct=1.5)
    assert [p["sym"] for p in plans] == ["NVDA"]
    p = plans[0]
    assert p["sl"] == 214.19 and p["overdue"] and not p["skip"]
    b = p["body"]
    assert b["type"] == "stop" and b["side"] == "sell" and b["qty"] == "1.720669928"
    assert b["time_in_force"] == "day" and b["client_order_id"] == "btdps-NVDA-20261016"


def test_same_day_entry_waits_for_close_then_gets_next_session_stop_without_alert():
    tracked = {"AMD": {"entry_date": "2026-10-16"}}
    positions = {"AMD": pos("AMD")}
    during = plan_protective_stops(tracked, positions, [], today=FRI, session_day=FRI, market_open=True, sl_pct=1.5)
    assert during[0]["skip"] and not during[0]["overdue"]
    after = plan_protective_stops(tracked, positions, [], today=FRI, session_day=date(2026, 10, 19),
                                  market_open=False, sl_pct=1.5, prefix="s7btd", expect_live_stops=False)
    assert not after[0]["skip"] and not after[0]["overdue"]
    assert after[0]["body"]["client_order_id"] == "s7btdps-AMD-20261019"


def test_after_close_expired_day_stops_are_replaced_without_alert_but_pre_open_alerts():
    tracked = {"MSFT": {"entry_date": "2026-10-14"}}
    positions = {"MSFT": pos("MSFT")}
    post = plan_protective_stops(tracked, positions, [], today=FRI, session_day=date(2026, 10, 19),
                                 market_open=False, sl_pct=1.5, expect_live_stops=False)
    assert post[0]["body"] and not post[0]["overdue"]
    pre = plan_protective_stops(tracked, positions, [], today=FRI, session_day=FRI,
                                market_open=False, sl_pct=1.5, expect_live_stops=True)
    assert pre[0]["overdue"]


def test_untracked_and_sold_positions_are_ignored():
    plans = plan_protective_stops({"META": {"entry_date": "2026-10-14"}}, {"BNBX": pos("BNBX")}, [],
                                  today=FRI, session_day=FRI, market_open=True, sl_pct=1.5)
    assert plans == []


def test_any_open_sell_counts_as_covered_no_duplicate():
    tracked = {"AAPL": {"entry_date": "2026-10-13"}}
    oo = [{"symbol": "AAPL", "side": "sell", "type": "limit", "order_class": "oco", "client_order_id": "btdtp-AAPL-x"}]
    assert plan_protective_stops(tracked, {"AAPL": pos("AAPL", avail="0")}, oo, today=FRI, session_day=FRI,
                                 market_open=True, sl_pct=1.5) == []


def test_time_exit_cancels_protective_and_manual_stops_per_sleeve():
    oo = [{"symbol": "TSLA", "side": "sell", "client_order_id": "manual-stop-TSLA-20261016-day"},
          {"symbol": "AMD", "side": "sell", "client_order_id": "s7btdps-AMD-20261016"},
          {"symbol": "NVDA", "side": "sell", "client_order_id": "btdps-NVDA-20261016"}]
    assert len(own_open_exits(oo, "TSLA")) == 1
    assert len(own_open_exits(oo, "NVDA")) == 1
    assert len(own_open_exits(oo, "AMD", "s7btd")) == 1
    assert own_open_exits(oo, "AMD") == []


def test_cids_owned_by_sleeves_and_user_prefix():
    assert Sleeve("x", "ucb3564", 100.0, False).owns_cid(protective_stop_cid("NVDA", FRI, "ucb3564"))
    assert Sleeve("x", "s7btd", 100.0, False).owns_cid(protective_stop_cid("MU", FRI, "s7btd", 2))
    assert protective_stop_cid("MU", FRI, "s7btd", 2) == "s7btdps-MU-20261016-2"


def test_helpers():
    assert stop_rejected_below('{"message":"stop price must be less than current price"}')
    assert is_stop_only({"type": "stop"}) and not is_stop_only({"type": "limit", "order_class": "oco"})


def test_scheduler_protect_events_pre_open_and_hourly():
    s = {"open": datetime(2026, 10, 16, 9, 30, tzinfo=ET), "close": datetime(2026, 10, 16, 16, 0, tzinfo=ET)}
    keys = [e.key for e in session_events(s, protect=True) if e.kind == "protect"]
    assert keys == ["protect-0845", "protect-1030", "protect-1130", "protect-1230", "protect-1330",
                    "protect-1430", "protect-1530"]
    assert not [e for e in session_events(s) if e.kind == "protect"]


def test_stop_exemptions_expire_after_until():
    from utils.live_btd_exits import stop_exemptions
    spec = "AMD:2026-10-19, INTC:2026-10-19,bad,X:notadate"
    assert set(stop_exemptions(spec, FRI)) == {"AMD", "INTC"}
    assert set(stop_exemptions(spec, date(2026, 10, 19))) == {"AMD", "INTC"}
    assert stop_exemptions(spec, date(2026, 10, 20)) == {}
    assert stop_exemptions(None, FRI) == {}
