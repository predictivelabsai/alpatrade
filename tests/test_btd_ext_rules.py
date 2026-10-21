"""v0.55.0 unit tests: the shared 24/5 rules in utils/btd_rules (pure functions)."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import utils.btd_rules as R  # noqa: E402
from btd_fixtures import DEFAULT_EXECUTION  # noqa: E402

ET = ZoneInfo("America/New_York")
E = {**DEFAULT_EXECUTION["extended_hours_exit"], "enabled": True}


def t(d, hh, mm=0):
    return datetime.fromisoformat(d).replace(hour=hh, minute=mm, tzinfo=ET)


def test_session_of_and_trade_day():
    assert [R.session_of(t("2026-10-20", h, m)) for h, m in ((3, 55), (4, 0), (9, 29), (9, 30), (15, 59), (16, 0), (19, 55), (20, 0))] == \
        ["overnight", "pre", "pre", "regular", "regular", "post", "post", "overnight"]
    nd = date(2026, 10, 21)
    assert R.trade_day_of(t("2026-10-20", 17), nd) == date(2026, 10, 20)       # post -> today (PDT: no sale of a same-day buy)
    assert R.trade_day_of(t("2026-10-20", 21), nd) == nd                       # overnight -> next session
    assert R.trade_day_of(t("2026-10-21", 2), nd) == nd and R.trade_day_of(t("2026-10-21", 8), nd) == nd


def test_breach_tp_and_quote_guard():
    assert R.ext_stop_breach(98.5, 98.5) and not R.ext_stop_breach(98.51, 98.5)
    assert not R.ext_stop_breach(None, 98.5) and not R.ext_stop_breach(0, 98.5)
    assert R.ext_tp_hit(108.0, 108.0) and not R.ext_tp_hit(107.99, 108.0)
    assert R.ext_usable_bid(100.0, 100.2, 50) == 100.0
    assert R.ext_usable_bid(308.88, 366.64, 50) is None                        # indicative overnight quote
    assert R.ext_usable_bid(100.0, 99.0, 50) is None and R.ext_usable_bid(0, 1, 50) is None


def test_limit_prices():
    assert R.ext_limit_price(100.00, 15) == 99.85
    assert R.ext_limit_price(0.5, 15) == 0.4992
    assert R.ext_buy_limit(100.00, 15) == 100.15
    with pytest.raises(ValueError):
        R.ext_limit_price(0, 15)


def test_exit_action_reprice_and_fallback():
    x = {"extended_hours_exit": E}; t0 = t("2026-10-20", 17)
    kw = dict(submitted_at=t0, market_open=False, execution=x)
    assert R.ext_exit_action(now=t0 + timedelta(minutes=4), reprices=0, **kw) == "wait"
    assert R.ext_exit_action(now=t0 + timedelta(minutes=5), reprices=0, **kw) == "reprice"
    assert R.ext_exit_action(now=t0 + timedelta(minutes=50), reprices=2, **kw) == "wait"     # max 2
    assert R.ext_exit_action(now=t0, reprices=0, submitted_at=t0, market_open=True, execution=x) == "fallback"


def test_ext_exit_fill_paths():
    b = [(t("2026-10-20", 17, 5 * i), 98.0 - 0.1 * i, None) for i in range(6)]
    # never trades back up to the limit -> two reprices, then market at the open
    assert R.ext_exit_fill(b, E, open_px=96.0) == (None, 96.0, "open_market")
    # fills at the first limit
    ok = [(b[0][0], 98.0, 98.0)]
    assert R.ext_exit_fill(ok, E, None) == (b[0][0], R.ext_limit_price(98.0, 15), "ext_limit_r0")
    # post-session order expires at 20:00 and is re-placed off the overnight bid
    late = [(t("2026-10-20", 19, 55), 98.0, 90.0), (t("2026-10-20", 20, 0), 97.0, 97.0)]
    assert R.ext_exit_fill(late, E, None) == (late[1][0], R.ext_limit_price(97.0, 15), "ext_limit_r0")


def test_order_expiry_and_check_calendar():
    assert R.ext_order_expired(t("2026-10-20", 17), t("2026-10-20", 20))
    assert not R.ext_order_expired(t("2026-10-20", 17), t("2026-10-20", 19, 55))
    assert not R.ext_order_expired(t("2026-10-21", 1), t("2026-10-21", 9, 0))  # overnight order lives on
    days = {"2026-10-22", "2026-10-23", "2026-10-26"}
    assert R.ext_check_allowed(t("2026-10-22", 21), days)                      # Thu night -> Fri session
    assert not R.ext_check_allowed(t("2026-10-23", 21), days)                  # Fri night: no overnight session
    assert not R.ext_check_allowed(t("2026-10-25", 21), days)                  # Sunday date: scheduler idle
    assert R.ext_check_allowed(t("2026-10-26", 1), days)                       # Mon 00:00-04:00


def test_session_mode_is_db_only():
    with pytest.raises(KeyError):
        R.session_mode({})                                                     # no code default
    assert not R.ext_stops_on({"session_mode": "regular"})
    assert R.ext_stops_on({"session_mode": "stops_24_5"}) and not R.ext_trading_on({"session_mode": "stops_24_5"})
    assert R.ext_trading_on({"session_mode": "full_24_5"})


def test_stop_exempt_from_params():
    P = {"stop_exempt": {"AMD": "2026-10-19", "intc": "2026-12-31"}}
    assert R.stop_exempt_map(P, date(2026, 10, 20)) == {"INTC": date(2026, 12, 31)}
    assert R.stop_exempt_map({"stop_exempt": "AMD:2026-10-30"}, date(2026, 10, 20)) == {"AMD": date(2026, 10, 30)}


def test_scheduler_ext_events_windows():
    from utils.live_btd_scheduler import ext_events
    s = {"open": t("2026-10-22", 9, 30), "close": t("2026-10-22", 16)}
    ev = ext_events(s, overnight_tonight=True)
    hhmm = [e.at.strftime("%H:%M") for e in ev]
    assert hhmm[0] == "00:00" and "09:25" in hhmm and "09:30" not in hhmm
    assert "16:00" not in hhmm and "16:05" in hhmm and "23:55" in hhmm
    assert len(ev) == len(set(e.key for e in ev))
    assert "20:00" not in [e.at.strftime("%H:%M") for e in ext_events(s, overnight_tonight=False)]
