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
                    "protect-1430", "protect-1530", "protect-post"]
    assert not [e for e in session_events(s) if e.kind == "protect"]


def test_stop_exemptions_expire_after_until():
    from utils.live_btd_exits import stop_exemptions
    spec = "AMD:2026-10-19, INTC:2026-10-19,bad,X:notadate"
    assert set(stop_exemptions(spec, FRI)) == {"AMD", "INTC"}
    assert set(stop_exemptions(spec, date(2026, 10, 19))) == {"AMD", "INTC"}
    assert stop_exemptions(spec, date(2026, 10, 20)) == {}
    assert stop_exemptions(None, FRI) == {}


# ---------------------------------------------------------------- v0.49.0
from utils.live_btd_exits import protective_stop_bodies, uncovered_qty, below_stop, tif_rejected  # noqa: E402


def test_whole_shares_get_gtc_stop_and_fraction_day_stop():
    b = protective_stop_bodies("NVDA", "1.720669928", 214.19, FRI)
    assert [x["time_in_force"] for x in b] == ["gtc", "day"]
    assert b[0]["qty"] == "1" and b[0]["client_order_id"] == "btdps-NVDA-20261016g"
    assert b[1]["qty"] == "0.720669928" and b[1]["client_order_id"] == "btdps-NVDA-20261016"
    assert all(x["type"] == "stop" and x["stop_price"] == "214.19" and x["side"] == "sell" for x in b)
    assert [x["client_order_id"] for x in protective_stop_bodies("NVDA", "3", 1.0, FRI, "s7btd", 2)] == \
        ["s7btdps-NVDA-20261016g-2"]
    only_frac = protective_stop_bodies("AMD", "0.4", 1.0, FRI)
    assert len(only_frac) == 1 and only_frac[0]["time_in_force"] == "day"


def test_gtc_whole_stop_open_fraction_expired_plans_only_the_fraction():
    tracked = {"NVDA": {"entry_date": "2026-10-14"}}
    p = pos("NVDA", "1.72", "200", avail="0.72")
    oo = [{"symbol": "NVDA", "side": "sell", "type": "stop", "qty": "1", "time_in_force": "gtc",
           "client_order_id": "btdps-NVDA-20261015g"}]
    plans = plan_protective_stops(tracked, {"NVDA": p}, oo, today=FRI, session_day=FRI, market_open=True, sl_pct=1.5)
    assert len(plans) == 1 and plans[0]["body"]["qty"] == "0.72"
    assert [x["time_in_force"] for x in plans[0]["bodies"]] == ["day"]


def test_uncovered_qty_conservative():
    assert uncovered_qty({"qty": "2.5", "qty_available": "2.5"}, []) == 2.5
    assert uncovered_qty({"qty": "2.5", "qty_available": "2.5"}, [{"qty": "2"}]) == 0.5
    assert uncovered_qty({"qty": "2.5", "qty_available": "0.5"}, [{"qty": "2"}]) == 0.5
    assert uncovered_qty({"qty": "2.5", "qty_available": "2.5"}, [{"side": "sell"}]) == 0.0   # unknown qty
    assert uncovered_qty({"qty": "1", "qty_available": "0"}, []) == 0.0


def test_below_stop_and_tif_reject():
    assert below_stop({"current_price": "98.0"}, 98.5) and below_stop({"current_price": "98.5"}, 98.5)
    assert not below_stop({"current_price": "99"}, 98.5) and not below_stop({}, 98.5)
    assert tif_rejected('{"message":"fractional orders must be DAY orders","code":42210000} time_in_force')
    assert not tif_rejected("stop price must be less than current price")


def test_sell_below_stop_cancels_own_stop_then_market_sells_full_qty():
    import logging
    from utils.live_btd_runner import Runner
    calls, subs, tracked = [], [], []
    st = {"open": True}
    me = SimpleNamespace(log=logging.getLogger("t"), broker_call=lambda m, u, *a: (calls.append((m, u)), st.update(open=False)))
    oo = [{"id": "o1", "symbol": "MU", "side": "sell", "qty": "2", "client_order_id": "s7btdps-MU-20261016g"}]
    fresh = lambda s: ({"qty": "2.3", "qty_available": "2.3"}, oo if st["open"] else [])
    out = Runner._sell_below_stop(me, "MU", 98.5, {"entry_date": "2026-10-15"}, FRI, "s7btd", oo, fresh,
                                  subs.append, lambda *a: tracked.append(a), "open")
    assert calls == [("DELETE", "/v2/orders/o1")]
    assert subs == [{"symbol": "MU", "qty": "2.3", "side": "sell", "type": "market", "time_in_force": "day",
                     "client_order_id": "s7btdx-MU-20261016"}]
    assert "market sell submitted" in out[0] and tracked


def test_sell_below_stop_never_doubles_when_position_gone():
    import logging
    from utils.live_btd_runner import Runner
    subs = []
    me = SimpleNamespace(log=logging.getLogger("t"), broker_call=lambda *a: None)
    out = Runner._sell_below_stop(me, "MU", 98.5, {}, FRI, "btd", [], lambda s: (None, []), subs.append,
                                  lambda *a: None, "open")
    assert subs == [] and "gone" in out[0]


def test_post_pass_ignores_prior_session_day_stops_still_new_and_plans_next_session():
    """2026-10-21: at the 16:03 ET post pass the prior-session DAY stops are still 'new' (Alpaca
    expires them ~16:05 ET) and hold qty_available -- they must not count as next-session cover."""
    from utils.live_btd_exits import own_stale_day_stops, uncovered_qty
    tracked = {"MSFT": {"entry_date": "2026-10-14"}, "AMD": {"entry_date": "2026-10-13"}}
    positions = {"MSFT": pos("MSFT", "2.5", avail="0"), "AMD": pos("AMD", "3", avail="0")}
    oo = [{"id": "1", "symbol": "MSFT", "side": "sell", "type": "stop", "qty": "2.5", "time_in_force": "day",
           "status": "new", "client_order_id": "btdps-MSFT-20261016"},
          {"id": "2", "symbol": "AMD", "side": "sell", "type": "stop", "qty": "3", "time_in_force": "day",
           "status": "new", "client_order_id": "manual-stop-AMD-20261016-day"},
          {"id": "3", "symbol": "AMD", "side": "sell", "type": "stop", "qty": "3", "time_in_force": "day",
           "status": "new", "client_order_id": "otherps-AMD-20261016"}]
    nxt = date(2026, 10, 19)
    post = plan_protective_stops(tracked, positions, oo, today=FRI, session_day=nxt,
                                 market_open=False, sl_pct=1.5, expect_live_stops=False)
    assert sorted(p["sym"] for p in post) == ["AMD", "MSFT"]
    assert all(p["body"]["client_order_id"].endswith("20261019") for p in post)
    assert sorted(o["id"] for o in own_stale_day_stops(oo, "btd", nxt, False)) == ["1", "2"]
    # during the session the same orders ARE cover; next-session / GTC orders always are
    assert uncovered_qty(positions["MSFT"], oo[:1], session_day=FRI, market_open=True) == 0
    new = [dict(oo[0], client_order_id="btdps-MSFT-20261019")]
    assert uncovered_qty(positions["MSFT"], new, session_day=nxt, market_open=False) == 0
    gtc = [dict(oo[0], time_in_force="gtc", client_order_id="btdps-MSFT-20261016g")]
    assert uncovered_qty(positions["MSFT"], gtc, session_day=nxt, market_open=False) == 0


def test_post_pass_judges_day_orders_by_submit_time():
    """Live Alpaca orders carry submitted_at: an order queued after yesterday's close (for today)
    dies at today's close; one queued after today's close is the next session's cover."""
    from utils.live_btd_exits import expiring_day_order
    nxt = date(2026, 10, 19)
    base = {"symbol": "MSFT", "side": "sell", "type": "stop", "qty": "1", "time_in_force": "day",
            "client_order_id": "btdps-MSFT-20261016"}
    assert expiring_day_order(dict(base, submitted_at="2026-10-15T20:03:00Z"), nxt, False, FRI)
    assert expiring_day_order(dict(base, submitted_at="2026-10-16T13:31:00Z"), nxt, False, FRI)
    assert not expiring_day_order(dict(base, submitted_at="2026-10-16T20:03:00Z"), nxt, False, FRI)
    assert not expiring_day_order(dict(base, submitted_at="2026-10-15T20:03:00Z"), FRI, True, FRI)
    oco = dict(base, type="limit", order_class="oco", client_order_id="btdtp-MSFT-20261016",
               submitted_at="2026-10-16T13:31:00Z")
    assert expiring_day_order(oco, nxt, False, FRI)


def test_second_post_check_scheduled_at_1620():
    s = {"open": datetime(2026, 10, 16, 9, 30, tzinfo=ET), "close": datetime(2026, 10, 16, 16, 0, tzinfo=ET)}
    ev = {e.key: e.at for e in session_events(s, protect=True)}
    assert ev["protect-post"].astimezone(ET).strftime("%H:%M") == "16:20"
