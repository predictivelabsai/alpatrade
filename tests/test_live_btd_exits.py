"""Live runner exits (scripts/live_btd_minhold.py -> utils/live_btd_runner.py), network/DB-free dry runs.

Asserts the PDT-safe contract: a position is never sold on the day it was bought (not even on
an intraday TP/SL hit, and not even with --min-hold 0), and TP/SL/max-hold exits are allowed
once the calendar min-hold (ET dates) is reached. Alpaca is faked; requests.post must never run.

Event model (--event auto picks by the clock): outside the windows a pass is the "open" event,
which sells at market if TP/SL is already hit and otherwise places broker-side TP/SL exit orders
(OCO for whole shares + stop for the fraction); in the close window it is the "close" event
(max-hold market sells).
"""
import json
import runpy
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_btd_minhold.py"
ET = ZoneInfo("America/New_York")


class _Resp:
    def __init__(self, data):
        self._d = data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _run(tmp_path, monkeypatch, positions, *, mins_to_close=200.0, extra=(), open_orders=None):
    """positions: {sym: (entry_age_days, unrealized_plpc_pct)} -> list of dry-run sell bodies."""
    now = datetime.now(ET)
    today = now.date()
    state = {"positions": {s: {"entry_date": (today - timedelta(days=age)).isoformat(),
                               "client_id": f"btd-{s}-x"} for s, (age, _) in positions.items()}}
    (tmp_path / "state.json").write_text(json.dumps(state))
    broker = [{"symbol": s, "qty": "1.5", "qty_available": "1.5", "unrealized_plpc": str(pl / 100),
               "avg_entry_price": "100", "current_price": str(100 * (1 + pl / 100)),
               "market_value": "100", "unrealized_pl": "1"} for s, (_, pl) in positions.items()]
    by_sym = {b["symbol"]: b for b in broker}
    clock = {"is_open": True, "next_close": (now + timedelta(minutes=mins_to_close)).isoformat()}
    acct = {"account_number": "TEST", "equity": "1000", "cash": "500", "buying_power": "500",
            "non_marginable_buying_power": "500"}

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/v2/clock"): return _Resp(clock)
        if url.endswith("/v2/account"): return _Resp(acct)
        if url.endswith("/v2/positions"): return _Resp(broker)
        if "/v2/positions/" in url: return _Resp(by_sym[url.rsplit("/", 1)[1]])
        if url.endswith("/v2/orders"):
            return _Resp([o for o in (open_orders or []) if not params or not params.get("symbols")
                          or o["symbol"] == params["symbols"]])
        if url.endswith("/v2/stocks/snapshots"): return _Resp({})
        if url.endswith("/v2/stocks/bars"): return _Resp({"bars": {}})
        raise AssertionError(f"unexpected GET {url}")

    def no_post(*a, **k):
        raise AssertionError("dry run must never POST")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", no_post)
    import dotenv
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a, **k: {})  # never read the repo .env / real DB
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BTD_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ALPACA_LIVE_API_KEY", "k")
    monkeypatch.setenv("ALPACA_LIVE_SECRET_KEY", "s")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--any-time", "--symbols", "ZZZZ", *extra])
    sells = []
    import logging
    class H(logging.Handler):
        def emit(self, rec):
            msg = rec.getMessage()
            if msg.startswith("DRY-RUN would POST /v2/orders"):
                sells.append(json.loads(msg.split(" ", 4)[4]))
            if msg.startswith("DRY-RUN would DELETE"):
                sells.append({"cancel": msg.split()[3]})
            if "PDT guard" in msg:
                sells.append({"pdt_guard": rec.getMessage().split(":")[0]})
    h = H(); lg = logging.getLogger("btd"); lg.addHandler(h); old = lg.level; lg.setLevel(logging.INFO)
    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    except SystemExit as e:
        assert not e.code, e.code
    finally:
        lg.removeHandler(h); lg.setLevel(old)
        for x in list(logging.getLogger().handlers):
            if isinstance(x, logging.FileHandler) and str(tmp_path) in x.baseFilename:
                logging.getLogger().removeHandler(x); x.close()
    return sells


def _sold(sells):
    """Symbols sold at market now (broker-side TP/SL exit orders are not a sale yet)."""
    return {b["symbol"] for b in sells if b.get("type") == "market" and b.get("side") == "sell"}


def _broker_exits(sells):
    return {b["symbol"] for b in sells if b.get("type") in ("limit", "stop") and b.get("side") == "sell"}


def test_same_day_tp_or_sl_never_sells(tmp_path, monkeypatch):
    for mins in (5, 200):  # close window and the open event
        sells = _run(tmp_path, monkeypatch, {"UPX": (0, 25.0), "DNX": (0, -10.0)}, mins_to_close=mins)
        assert _sold(sells) == set() and _broker_exits(sells) == set()


def test_pdt_guard_blocks_same_day_even_with_min_hold_zero(tmp_path, monkeypatch):
    sells = _run(tmp_path, monkeypatch, {"UPX": (0, 25.0)}, mins_to_close=5,
                 extra=("--min-hold", "0", "--max-hold", "0"))
    assert _sold(sells) == set()
    assert {"pdt_guard": "UPX"} in sells


def test_before_min_hold_tp_sl_ignored(tmp_path, monkeypatch):
    sells = _run(tmp_path, monkeypatch, {"A": (1, 25.0), "B": (2, -10.0)})
    assert _sold(sells) == set() and _broker_exits(sells) == set()


def test_after_min_hold_tp_and_sl_sell_any_time_in_session(tmp_path, monkeypatch):
    sells = _run(tmp_path, monkeypatch, {"TPX": (3, 8.5), "SLX": (3, -1.6), "FLAT": (3, 1.0)})
    assert _sold(sells) == {"TPX", "SLX"}          # already beyond TP/SL at the open event
    for b in sells:
        if b.get("type") == "market":
            assert b["side"] == "sell" and b["time_in_force"] == "day"
            assert b["qty"] == "1.5"               # full fractional qty_available
    # FLAT gets broker-side exits instead: OCO on the whole share + stop on the 0.5 fraction
    flat = [b for b in sells if b.get("symbol") == "FLAT"]
    assert [b.get("order_class") or b["type"] for b in flat] == ["oco", "stop"]
    assert flat[0]["qty"] == "1" and flat[0]["take_profit"]["limit_price"] == "108.00"
    assert flat[0]["stop_loss"]["stop_price"] == "98.50" and flat[1]["qty"] == "0.5"
    assert all(b["time_in_force"] == "day" for b in flat)


def test_max_hold_exits_in_close_window(tmp_path, monkeypatch):
    sells = _run(tmp_path, monkeypatch, {"FLAT": (3, 1.0), "YOUNG": (2, 1.0)}, mins_to_close=10)
    assert _sold(sells) == {"FLAT"}


@pytest.mark.parametrize("mins", [15.5, 1.5])
def test_max_hold_waits_outside_close_window(tmp_path, monkeypatch, mins):
    assert _sold(_run(tmp_path, monkeypatch, {"FLAT": (3, 1.0)}, mins_to_close=mins)) == set()


def test_close_event_cancels_own_broker_exits_first(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append(a) or _Resp({}))
    sells = _run(tmp_path, monkeypatch, {"FLAT": (3, 1.0)}, mins_to_close=10,
                 open_orders=[{"id": "o1", "symbol": "FLAT", "side": "sell", "type": "limit",
                               "client_order_id": "btdtp-FLAT-20990101", "status": "new"}])
    assert _sold(sells) == {"FLAT"}
    kinds = ["cancel" if "cancel" in b else b.get("type") for b in sells]
    assert kinds == ["cancel", "market"]               # OCO cancelled before the max-hold sell
    assert sells[0]["cancel"] == "/v2/orders/o1"
    assert calls == []                                 # dry run never calls the broker


def test_min_hold_one_allows_next_day_exit_but_not_same_day(tmp_path, monkeypatch):
    sells = _run(tmp_path, monkeypatch, {"OLD": (1, 9.0), "NEW": (0, 9.0)},
                 extra=("--min-hold", "1"))
    assert _sold(sells) == {"OLD"}                 # next ET date is not a day trade
