"""Per-user live runner (utils/user_live_runner.py): one process per activation, user-only config."""
import argparse
import pytest

import utils.user_live_runner as ulr
from utils.live_btd_runner import PassStop, Runner, build_parser
from utils.live_btd_config import DEFAULT_PARAMS

@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BTD_STATE_DIR", str(tmp_path))     # never the real ~/.alpatrade-live


PARAMS = {"symbols": ["XOM", "CVX"], "dip": 2.5, "tp": 6, "sl": 2, "min_hold": 2, "max_hold": 4, "pos_frac": 0.5}


def _act(status="active", params=None, alloc=400.0, acct="USER123"):
    return ulr.Activation(7, "u-1", "kairi@example.com", 39, acct, "u466196", alloc, status,
                          dict(params or PARAMS), {}, "clone")


def _runner(monkeypatch, status="active", env=None, holder="hp", **kw):
    st = {"s": status}
    monkeypatch.setattr(ulr, "load_activation", lambda eng, i: _act(st["s"], **kw))
    monkeypatch.setattr(ulr, "load_status", lambda eng, i: st["s"])
    a = build_parser().parse_args(["--instance", "hp", "--role", "primary"])
    e = {"DATABASE_URL": "postgresql://x", "ALPACA_LIVE_ACCOUNT": "885504372", "ALPACA_LIVE_API_KEY": "OPKEY",
         "ALPACA_LIVE_SECRET_KEY": "OPSECRET", ulr.FLAG: "1", **(env or {})}
    r = ulr.UserRunner(a, 7, engine=object(), env=e, creds_fn=lambda: {"api_key": "AKUSER", "secret_key": "s"},
                       operator_holder=lambda: holder)
    r._verified = "USER123"
    return r, st


def test_params_come_only_from_the_user():
    p = ulr.user_params(PARAMS)
    assert p["symbols"] == ["XOM", "CVX"] and p["dip"] == 2.5 and p["max_hold"] == 4 and p["pos_frac"] == 0.5
    assert p["symbols"] != DEFAULT_PARAMS["symbols"]
    for k in ulr.REQUIRED:
        with pytest.raises(ValueError):
            ulr.user_params({x: v for x, v in PARAMS.items() if x != k})   # never filled from Julian's defaults
    assert ulr.user_params({**PARAMS, "dip": 0.03})["dip"] == 3.0


def test_user_keys_prefix_allocation_and_no_operator_keys(monkeypatch):
    r, _ = _runner(monkeypatch)
    assert r.headers["APCA-API-KEY-ID"] == "AKUSER"
    assert not any(k.startswith(("ALPACA_LIVE_API", "ALPACA_LIVE_SECRET")) for k in r.env)
    sl, extra = r.plan_sleeves({}, r.load_config())
    assert (sl.cid_prefix, sl.allocation_usd, sl.is_primary, extra) == ("u466196", 400.0, False, [])
    assert r.load_sleeves("885504372", "x") == (None, [])
    assert r.store("USER123").inner.runner_key == "user-btd:USER123:u466196"
    assert "/users/u466196" in r.here and ".alpatrade-live" not in r.here and r.load_config().source == "user_strategy_configs"


def test_never_runs_on_the_operator_account(monkeypatch):
    with pytest.raises(PassStop):
        _runner(monkeypatch, acct="885504372")


def test_kill_switches(monkeypatch):
    r, st = _runner(monkeypatch)
    assert r.entry_gate() is None
    st["s"] = "paused"
    assert "paused" in r.entry_gate()
    with pytest.raises(PassStop):
        r.pre_order({"side": "buy", "notional": "10", "client_order_id": "u466196-XOM-20261012"})
    r.pre_order({"side": "sell", "client_order_id": "u466196tp-XOM-20261012"})   # exits still allowed
    st["s"] = "deactivated"
    with pytest.raises(PassStop):
        r.pre_order({"side": "sell", "client_order_id": "u466196x-XOM-20261012"})
    r2, _ = _runner(monkeypatch, env={ulr.FLAG: "0"})
    assert "kill switch" in r2.entry_gate()
    with pytest.raises(PassStop):
        r2.pre_order({"side": "sell", "client_order_id": "u466196x-XOM-20261012"})


def test_order_time_guards(monkeypatch):
    r, _ = _runner(monkeypatch)
    r.pre_order({"side": "buy", "notional": "200.00", "client_order_id": "u466196-XOM-20261012"})
    for body in ({"side": "buy", "notional": "10", "client_order_id": "btd-XOM-20261012"},
                 {"side": "buy", "notional": "10", "client_order_id": "s7btd-XOM-20261012"},
                 {"side": "buy", "notional": "400.01", "client_order_id": "u466196-XOM-20261012"}):
        with pytest.raises(PassStop):
            r.pre_order(body)
    r._verified = "OTHER"
    with pytest.raises(PassStop):
        r.pre_order({"side": "buy", "notional": "1", "client_order_id": "u466196-XOM-20261012"})


def test_single_placer_follows_operator_lease(monkeypatch):
    r, _ = _runner(monkeypatch, holder="mac")
    called = []

    class Inner:
        instance = "hp"
        def peek(self): return ulr.LeaseResult(ok=True, state={"positions": {}}, version=1)
        def acquire(self, *a, **k): called.append(1); return ulr.LeaseResult(ok=True, act=True)
    g = ulr._GatedStore(Inner(), lambda: "mac")
    lr = g.acquire()
    assert lr.ok and not lr.act and "mac" in lr.reason and not called
    assert ulr._GatedStore(Inner(), lambda: "hp").acquire().act and called
    assert not ulr._GatedStore(Inner(), lambda: None).acquire().act


def _entries(r, cash, allocation_exposure=0.0):
    snaps = {s: {"latestTrade": {"p": 90.0}, "dailyBar": {"t": "2026-10-12", "c": 90},
                 "prevDailyBar": {"c": 100.0}} for s in ("XOM", "CVX")}
    bars = {"bars": {s: [{"h": 100.0}] * 20 for s in ("XOM", "CVX")}}

    def get(url, **p):
        if url.endswith("/snapshots"): return snaps
        if url.endswith("/bars"): return bars
        if "/v2/assets/" in url: return {"tradable": True, "fractionable": True}
        if url.endswith("/v2/orders"): return []
        if "/v2/positions/" in url: raise type("E", (Exception,), {"response": type("R", (), {"status_code": 404})()})()
        return {}
    r.get = get
    sent = []
    import datetime as dt
    st = {"positions": {}, "last_entry": {}}
    r._entries(st, {"pending": []}, None, {}, [], r.load_config().params, ["XOM", "CVX"], 10000.0, cash, cash,
               dt.date(2026, 10, 12), lambda: True, lambda: None, lambda b: (r.pre_order(b), sent.append(b)),
               sleeve=r.sleeve, sleeve_val=400.0, other_held=frozenset())
    return sent


def test_sizing_is_cash_only_and_capped_by_allocation(monkeypatch):
    import utils.live_btd_runner as lbr
    monkeypatch.setattr(lbr, "alpaca_symbol_busy", lambda *a: None)
    r, _ = _runner(monkeypatch)
    sent = _entries(r, cash=10000.0)
    assert [b["client_order_id"][:8] for b in sent] == ["u466196-", "u466196-"]
    assert sum(float(b["notional"]) for b in sent) <= 400.0          # 2 x 0.5 x $400 sleeve
    assert _entries(r, cash=150.0) == []                              # $200 target > $150 free cash -> no order


def test_operator_runner_hooks_are_noops():
    assert Runner.entry_gate(object()) is None and Runner.pre_order(object(), {}) is None


def test_supervisor_and_scheduler_scripts_exist_and_are_separate():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sup = (root / "scripts/user_live_supervisor.py").read_text()
    op = (root / "scripts/live_btd_scheduler.py").read_text()
    assert "user_live_scheduler.py" in sup and "USER_LIVE" not in op and "user_live" not in op
    assert "operator_account" in sup or "ALPACA_LIVE_ACCOUNT" in sup


def test_encryption_key_from_dotenv_reaches_engine_auth(monkeypatch):
    import os
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    _runner(monkeypatch, env={"ENCRYPTION_KEY": "k" * 44})
    assert os.environ["ENCRYPTION_KEY"] == "k" * 44
