"""Multi-strategy sleeves on one Alpaca account (utils/strategy_allocation.py + the runner).

Offline: Alpaca, the DB lease and the strategy configs are faked. Covers the pure
allocation math/validation, per-strategy client_order_id tagging, buying power capped at
the sleeve, the backward-compatible single-strategy path (Mag-7 = whole account, pos_frac
1/7 of equity, ``btd-`` ids), the per-strategy held/open-order skip and the Semi 7 universe.
"""
import argparse
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import live_btd_runner as lr  # noqa: E402
from utils.live_btd_config import DEFAULT_EXECUTION, DEFAULT_PARAMS, ConfigResult  # noqa: E402
from utils.live_btd_exits import cids, own_open_exits, plan_broker_exits  # noqa: E402
from utils.live_btd_state import LeaseResult, adopt_runner_position  # noqa: E402
from utils.strategy_allocation import (PRIMARY, Sleeve, buying_power, sleeve_value,  # noqa: E402
                                       validate_allocations)

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
SEMI7 = ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"]
ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ pure
def test_sleeve_value_null_is_rest_of_account():
    semi = Sleeve("semi7", "s7btd", 20000.0)
    prim = Sleeve("mag7", "btd", None, True)
    assert sleeve_value(prim, 100000, [prim]) == 100000          # alone: whole account
    assert sleeve_value(prim, 100000, [prim, semi]) == 80000
    assert sleeve_value(semi, 100000, [prim, semi]) == 20000
    assert sleeve_value(prim, 10000, [prim, semi]) == 0          # never negative


def test_buying_power_capped_by_sleeve_and_cash():
    assert buying_power(sleeve_val=20000, own_exposure=15000, own_pending=1000, account_avail=50000) == 4000
    assert buying_power(sleeve_val=20000, own_exposure=0, own_pending=0, account_avail=3000) == 3000
    assert buying_power(sleeve_val=20000, own_exposure=25000, own_pending=0, account_avail=9e9) == 0


def test_client_ids_are_per_strategy_and_never_collide():
    s7 = Sleeve("semi7", "s7btd", 1.0)
    assert s7.entry_cid("AMD", date(2026, 10, 9)) == "s7btd-AMD-20261009"
    assert cids("AMD", date(2026, 10, 9), "s7btd")["oco"] == "s7btdtp-AMD-20261009"
    assert cids("AAPL", date(2026, 10, 9)) == {"oco": "btdtp-AAPL-20261009", "stop": "btdsl-AAPL-20261009",
                                               "market": "btdx-AAPL-20261009"}
    assert s7.owns_cid("s7btdsl-AMD-20261009") and not s7.owns_cid("btdsl-AMD-20261009")
    assert not PRIMARY.owns_cid("s7btd-AMD-20261009") and PRIMARY.owns_cid("btd-AAPL-20261009")
    oo = [{"symbol": "AMD", "side": "sell", "client_order_id": "s7btdtp-AMD-20261009"},
          {"symbol": "AMD", "side": "sell", "client_order_id": "btdtp-AMD-20261009"}]
    assert [o["client_order_id"] for o in own_open_exits(oo, "AMD", "s7btd")] == ["s7btdtp-AMD-20261009"]
    assert [o["client_order_id"] for o in own_open_exits(oo, "AMD")] == ["btdtp-AMD-20261009"]
    plan = plan_broker_exits("AMD", "2.5", 100, 8, 1.5, date(2026, 10, 9), prefix="s7btd")
    assert all(o["client_order_id"].startswith("s7btd") for o in plan["orders"])


def test_adopt_uses_strategy_prefix():
    orders = [{"symbol": "AMD", "side": "buy", "filled_qty": "1", "client_order_id": "s7btd-AMD-20261006"}]
    get = lambda url, **k: orders  # noqa: E731
    assert adopt_runner_position(get, "x", "AMD") is None
    assert adopt_runner_position(get, "x", "AMD", "s7btd")["entry_date"] == "2026-10-06"


def test_validate_allocations():
    rows = [{"strategy_name": "mag7", "cid_prefix": "btd", "allocation_usd": None, "is_primary": True},
            {"strategy_name": "semi7", "cid_prefix": "s7btd", "allocation_usd": 20000}]
    assert validate_allocations(rows, equity=100000, universes={"mag7": MAG7, "semi7": SEMI7}) == []
    assert any("exceed" in e for e in validate_allocations(rows, equity=10000))
    bad = rows + [{"strategy_name": "x", "cid_prefix": "btd", "allocation_usd": 1}]
    assert any("reserved" in e for e in validate_allocations(bad, equity=1e6))
    neg = [{"strategy_name": "semi7", "cid_prefix": "s7btd", "allocation_usd": -1}]
    assert any(">= 0" in e for e in validate_allocations(neg, equity=1e6))
    ov = validate_allocations(rows, equity=1e6, universes={"mag7": MAG7, "semi7": SEMI7 + ["NVDA"]})
    assert any("NVDA" in e for e in ov)


def test_semi7_universe_excludes_mag7():
    sql = (ROOT / "sql" / "46_strategy_allocations.sql").read_text()
    for s in SEMI7:
        assert f'"{s}"' in sql
    assert not set(SEMI7) & set(MAG7 + ["GOOG"])
    assert "buy_the_dip_semi7_minhold_live" in sql


# ------------------------------------------------------------------ runner (fake Alpaca)
class _Resp404(Exception):
    def __init__(self):
        super().__init__("404"); self.response = type("R", (), {"status_code": 404})()


def _cfg(name, symbols, pos_frac=1 / 7):
    return ConfigResult({**DEFAULT_PARAMS, "symbols": symbols, "pos_frac": pos_frac}, DEFAULT_EXECUTION, {},
                        "test", True, 1, 2, name)


class FakeStore:
    def __init__(self, state=None):
        self.state = state or {"positions": {}, "last_entry": {}, "rec": {"pending": []}}
        self.saved = None

    def acquire(self):
        return LeaseResult(ok=True, act=True, reason="test", state=self.state, version=1, deadline_mono=math.inf)

    def save(self, state):
        self.saved = state; return True


def _runner(tmp_path, monkeypatch, *, equity=100000.0, cash=100000.0, positions=None, open_orders=None,
            sleeves=(), primary_alloc=None, store=None):
    r = object.__new__(lr.Runner)
    r.a = argparse.Namespace(ignore_hours=False, live=True, lease_ttl_min=8, takeover_min=12)
    import logging
    r.log = logging.getLogger("test-alloc"); r.execute = True
    r.here = str(tmp_path); r.state_path = str(tmp_path / "state.json")
    r.db_url = None; r.user_email = "x@y"; r.account_no = "A1"; r.base = "https://t"
    r.role = "primary"; r.instance = "test"; r.strategy = "buy_the_dip_mag7_minhold_live"
    r.headers = {}
    r._store = store or FakeStore(); r._store_acct = "A1"
    r.store = lambda acct: r._store
    r.load_sleeves = lambda acct, name: (primary_alloc, list(sleeves))
    now = datetime.now(lr.ET)
    syms = MAG7 + SEMI7
    posted = []

    def get(url, **p):
        path = url.split("https://t")[-1].split("https://data.alpaca.markets")[-1]
        if path == "/v2/clock":
            return {"is_open": True, "next_close": (now + timedelta(minutes=10)).isoformat(),
                    "next_open": (now + timedelta(days=1)).isoformat()}
        if path == "/v2/account":
            return {"account_number": "A1", "equity": str(equity), "cash": str(cash),
                    "non_marginable_buying_power": str(cash), "buying_power": str(cash)}
        if path == "/v2/positions":
            return list((positions or {}).values())
        if path.startswith("/v2/positions/"):
            if path.split("/")[-1] in (positions or {}): return positions[path.split("/")[-1]]
            raise _Resp404()
        if path == "/v2/orders":
            oo = list(open_orders or [])
            return [o for o in oo if not p.get("symbols") or o["symbol"] == p["symbols"]]
        if path.startswith("/v2/orders:by_client_order_id"):
            raise _Resp404()
        if path == "/v2/stocks/snapshots":
            return {s: {"latestTrade": {"p": 95.0}, "dailyBar": {"t": "1999-01-01", "c": 100.0}} for s in syms}
        if path == "/v2/stocks/bars":
            return {"bars": {s: [{"h": 100.0}] * 20 for s in syms}}
        if path.startswith("/v2/assets/"):
            return {"tradable": True, "fractionable": True}
        raise AssertionError(path)
    r.get = get
    r.post_order = lambda body: posted.append(body) or {}
    return r, posted


def test_single_strategy_is_unchanged_whole_account(tmp_path, monkeypatch):
    r, posted = _runner(tmp_path, monkeypatch)
    res = r._run(["entry"], _cfg("buy_the_dip_mag7_minhold_live", MAG7))
    assert res.acted
    assert sorted(o["symbol"] for o in posted) == sorted(MAG7)
    assert all(o["client_order_id"].startswith("btd-") for o in posted)
    assert {o["notional"] for o in posted} == {f"{100000 / 7:.2f}"}   # pos_frac 1/7 of equity


def test_two_sleeves_sized_and_tagged_per_strategy(tmp_path, monkeypatch):
    semi = Sleeve("buy_the_dip_semi7_minhold_live", "s7btd", 20000.0)
    r, posted = _runner(tmp_path, monkeypatch, sleeves=[(semi, _cfg(semi.strategy_name, SEMI7))])
    r._run(["entry"], _cfg("buy_the_dip_mag7_minhold_live", MAG7))
    mag = [o for o in posted if o["symbol"] in MAG7]; s7 = [o for o in posted if o["symbol"] in SEMI7]
    assert len(mag) == 7 and len(s7) == 7
    assert {o["notional"] for o in mag} == {f"{80000 / 7:.2f}"}
    assert {o["notional"] for o in s7} == {f"{20000 / 7:.2f}"}
    assert all(o["client_order_id"].startswith("btd-") for o in mag)
    assert all(o["client_order_id"].startswith("s7btd-") for o in s7)
    saved = r._store.saved
    assert set(saved["positions"]) == set(MAG7)
    assert set(saved["sleeves"][semi.strategy_name]["positions"]) == set(SEMI7)


def test_sleeve_buying_power_capped_at_allocation(tmp_path, monkeypatch):
    semi = Sleeve("buy_the_dip_semi7_minhold_live", "s7btd", 20000.0)
    held = {s: {"symbol": s, "market_value": "4000", "qty": "40", "unrealized_plpc": "0"} for s in SEMI7[:4]}
    st = {"positions": {}, "last_entry": {}, "rec": {"pending": []},
          "sleeves": {semi.strategy_name: {"positions": {s: {"entry_date": "2026-10-08", "client_id": f"s7btd-{s}-20261008"}
                                                         for s in held}, "last_entry": {}, "rec": {"pending": []}}}}
    r, posted = _runner(tmp_path, monkeypatch, positions=held, store=FakeStore(st),
                        sleeves=[(semi, _cfg(semi.strategy_name, SEMI7))])
    r._run(["entry"], _cfg("buy_the_dip_mag7_minhold_live", MAG7))
    s7 = [o for o in posted if o["symbol"] in SEMI7]
    # $16k of $20k used -> $4k headroom -> one $2,857 buy only, never beyond the sleeve
    assert len(s7) == 1 and s7[0]["symbol"] not in held
    assert sum(float(o["notional"]) for o in s7) <= 4000


def test_open_order_of_other_strategy_does_not_block_unrelated_symbols(tmp_path, monkeypatch):
    semi = Sleeve("buy_the_dip_semi7_minhold_live", "s7btd", 20000.0)
    oo = [{"symbol": "AMD", "side": "buy", "notional": "100", "client_order_id": "manual-1"}]
    r, posted = _runner(tmp_path, monkeypatch, open_orders=oo, sleeves=[(semi, _cfg(semi.strategy_name, SEMI7))])
    r._run(["entry"], _cfg("buy_the_dip_mag7_minhold_live", MAG7))
    syms = {o["symbol"] for o in posted}
    assert "AMD" not in syms and set(MAG7) <= syms and len(syms & set(SEMI7)) == 6


# ------------------------------------------------------------------ web
from engine.web import ph_strategy_allocations as pa  # noqa: E402

ROWS = [{"name": "buy_the_dip_mag7_minhold_live", "display_name": "Mag-7", "params": {"symbols": MAG7},
         "config_active": True, "version": 2, "cid_prefix": "btd", "allocation_usd": None, "is_primary": True},
        {"name": "buy_the_dip_semi7_minhold_live", "display_name": "Semi-7", "params": {"symbols": SEMI7},
         "config_active": False, "version": 1, "cid_prefix": "s7btd", "allocation_usd": None, "is_primary": False}]


def test_web_parse_and_validate_against_equity_and_cash():
    prop, errs = pa.parse_form({"alloc__buy_the_dip_mag7_minhold_live": "",
                                "alloc__buy_the_dip_semi7_minhold_live": "$20,000"}, ROWS)
    assert errs == [] and prop[1]["allocation_usd"] == 20000 and prop[1]["is_active"]
    assert prop[0]["allocation_usd"] is None and prop[0]["is_active"]
    e, w = pa.check(prop, ROWS, equity=100000, cash=50000)
    assert e == [] and any("rest of the account: $80,000.00" in x for x in w)
    e, w = pa.check(prop, ROWS, equity=15000, cash=15000)
    assert any("exceed account equity" in x for x in e)
    e, w = pa.check(prop, ROWS, equity=100000, cash=5000)
    assert e == [] and any("free cash" in x for x in w)
    _, errs = pa.parse_form({"alloc__buy_the_dip_semi7_minhold_live": "abc"}, ROWS)
    assert errs
    e, _ = pa.check(prop, ROWS, equity=None, cash=None)
    assert e


def test_web_blank_semi_is_inactive_and_render_has_form():
    prop, _ = pa.parse_form({}, ROWS)
    assert prop[1]["is_active"] is False
    out = pa.render([{"account_number": "A1", "label": "live"}], "A1", ROWS, {"equity": 1000.0, "cash": 500.0})
    assert "name='alloc__buy_the_dip_semi7_minhold_live'" in out and "method='post'" in out
    assert "inactive config" in out and "prefix <code>s7btd</code>" in out
    assert pa.default_prefix("buy_the_dip_semi7_minhold_live") == "s7btd"


def test_live_account_page_stays_read_only_but_links_allocations():
    src = (ROOT / "engine" / "web" / "ph_live_account.py").read_text()
    assert "/live/allocations" in src and 'methods=["POST"]' not in src


def test_walk_forward_risk_metrics_and_semi7_basket():
    sys.path.insert(0, str(ROOT / "scripts"))
    import walk_forward_btd as wf
    assert wf.BASKETS["semi7"][1] == SEMI7
    rows = [{"oos_ret": 0.10, "bh_ret": 0.05, "oos_trades": 3, "oos_win_rate": 60.0},
            {"oos_ret": -0.05, "bh_ret": -0.10, "oos_trades": 2, "oos_win_rate": 40.0}]
    m = wf.risk_metrics(rows, 30)
    assert m["beat"] == 2 and m["btd_pos"] == 1 and m["trade_win_rate"] == 50.0
    assert abs(m["btd_mdd"] - 0.05) < 1e-9 and abs(m["bh_mdd"] - 0.10) < 1e-9
    assert m["btd_cagr"] > m["bh_cagr"]
