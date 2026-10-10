"""Clone strategy flow: rows created, idempotency, ownership, signed-out redirect, backtest
kick-off into chat, never live (engine/leaderboard/clone_bt.py, engine/web/ph_leaderboard.py)."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("XAI_API_KEY", "test")

from engine.leaderboard import clone_bt, store  # noqa: E402

SEED_MD = (Path(__file__).resolve().parents[1] / "engine/leaderboard/seeds/mag7-btd-live.md").read_text()
CWT_MD = """---\ntitle: RS\nauthor: Trader\n---\n# RS\n\n```json\n{"schema": "alpatrade.strategy_config/v1",
"kind": "backtest", "template": "relative_strength", "params": {"lookback": 126, "top_n": 10,
"universe": "sp500_current"}, "execution": {"cash_only": true}}\n```\n"""


class FakeDB:
    """In-memory stand-in for user_strategies + user_strategy_configs."""

    def __init__(self):
        self.strats = {7: {"id": 7, "user_id": "owner-1", "name": "Mag-7 BTD", "author": "Julian",
                           "author_name": "Julian", "description": "d", "is_public": True,
                           "skill_md": SEED_MD, "kind": "live", "cloned_from_id": None,
                           "live_strategy_slug": "buy_the_dip_mag7_minhold_live", "source": None,
                           "source_url": None, "backtest_metrics": None},
                       8: {"id": 8, "user_id": "owner-1", "name": "RS", "author": "Trader",
                           "author_name": "Trader", "description": "d", "is_public": True,
                           "skill_md": CWT_MD, "kind": "backtest", "cloned_from_id": None,
                           "live_strategy_slug": None, "source": "Chat With Traders",
                           "source_url": "https://chatwithtraders.com/x", "backtest_metrics": {"template": "relative_strength"}},
                       9: {"id": 9, "user_id": "owner-2", "name": "Private", "author": "x", "author_name": "x",
                           "description": "", "is_public": False, "skill_md": "", "kind": "live",
                           "cloned_from_id": None, "live_strategy_slug": None, "source": None,
                           "source_url": None, "backtest_metrics": None}}
        self.configs = {}
        self.next = 100

    def install(self, mp):
        mp.setattr(store, "get", lambda sid: dict(self.strats[int(sid)]) if int(sid) in self.strats else None)

        def clone(sid, uid, author_name=None):
            src = self.strats[int(sid)]
            self.next += 1
            self.strats[self.next] = {**src, "id": self.next, "user_id": uid, "author_name": author_name,
                                      "author": author_name, "is_public": False, "cloned_from_id": src["id"],
                                      "name": src["name"] + " (copy)"}
            return self.next
        mp.setattr(store, "clone", clone)
        mp.setattr(clone_bt, "existing_clone", lambda sid, uid: next(
            (k for k, v in self.strats.items() if v["user_id"] == uid and v["cloned_from_id"] == int(sid)), None))
        mp.setattr(clone_bt, "get_config", lambda sid, uid: self.configs.get((int(sid), uid)))

        def upsert(sid, uid, t, p, e, mode):
            self.configs[(int(sid), uid)] = {"template": t, "params": p, "execution": e, "mode": mode,
                                             "is_live": False, "is_active": True}
        mp.setattr(clone_bt, "upsert_config", upsert)

        db = self

        class S:
            def execute(self, sql, params=None):
                if "SET kind = 'backtest', source" in str(sql):
                    s = db.strats[params["i"]]
                    s.update(kind="backtest", backtest_metrics=None, live_strategy_slug=None)
        mp.setattr(clone_bt, "_pool", lambda: type("P", (), {"get_session": lambda self: contextlib.nullcontext(S())})())
        mp.setattr(clone_bt, "has_paper_keys", lambda uid: uid == "with-keys")


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.install(monkeypatch)
    return d


USER = {"user_id": "user-1", "email": "alice@example.com"}


def test_clone_creates_private_copy_and_paper_config(db):
    new_id, created = clone_bt.clone_strategy(7, USER)
    s = db.strats[new_id]
    assert created and s["user_id"] == "user-1" and s["is_public"] is False
    assert s["cloned_from_id"] == 7 and s["author_name"] == "alice" and s["live_strategy_slug"] is None
    cfg = db.configs[(new_id, "user-1")]
    assert cfg["template"] == "buy_the_dip" and cfg["is_live"] is False and cfg["is_active"]
    assert cfg["mode"] == "simulated"            # no Alpaca paper keys
    assert cfg["params"]["dip"] == 3.0 and cfg["params"]["sl"] == 1.5


def test_clone_with_keys_is_paper_mode(db):
    new_id, _ = clone_bt.clone_strategy(7, {"user_id": "with-keys", "email": "k@x"})
    assert db.configs[(new_id, "with-keys")]["mode"] == "paper"


def test_clone_is_idempotent(db):
    a = clone_bt.clone_strategy(7, USER)
    b = clone_bt.clone_strategy(7, USER)
    assert a[0] == b[0] and b[1] is False
    assert sum(1 for s in db.strats.values() if s["user_id"] == "user-1") == 1


def test_ownership_private_strategy_not_clonable(db):
    assert clone_bt.clone_strategy(9, USER) is None


def test_cwt_template_cloned_and_flagged_not_paper_tradable(db):
    new_id, _ = clone_bt.clone_strategy(8, USER)
    cfg = db.configs[(new_id, "user-1")]
    assert cfg["template"] == "relative_strength" and cfg["params"]["top_n"] == 10
    st = clone_bt.paper_status("relative_strength", "with-keys")
    assert st["mode"] == "simulated" and "isn't available" in st["label"]


def test_run_job_owner_only(db):
    new_id, _ = clone_bt.clone_strategy(7, USER)
    with pytest.raises(PermissionError):
        clone_bt.run_job(new_id, "someone-else")


def test_run_job_uses_matching_engine_and_stores_audit_stamp(db, monkeypatch):
    new_id, _ = clone_bt.clone_strategy(8, USER)
    seen, saved = {}, {}
    monkeypatch.setattr(clone_bt, "_template", lambda t, p, a, b, prog: seen.update(t=t, p=p) or {
        "curve": [("2020-01-02", 10000.0), ("2020-06-01", 10500.0), ("2021-01-04", 11000.0)],
        "trades": 4, "win_rate_pct": 50.0, "fees_paid": 1.0, "universe": "3 symbols", "used_params": p,
        "slippage_bps": 10.0, "engine_desc": "engine.backtest.templates (relative_strength)"})
    monkeypatch.setattr(clone_bt, "_spy_close", lambda a, b: {"2020-01-02": 300.0, "2021-01-04": 330.0})
    monkeypatch.setattr(clone_bt, "save_metrics", lambda sid, uid, bm: saved.update(bm=bm))
    md, bm = clone_bt.run_job(new_id, "user-1", {"stop": 0.02})
    assert seen["t"] == "relative_strength" and seen["p"]["stop"] == 0.02
    assert db.configs[(new_id, "user-1")]["params"]["stop"] == 0.02     # overrides persisted
    assert abs(bm["total_return_pct"] - 10.0) < 1e-9 and abs(bm["spy_return_pct"] - 10.0) < 1e-9
    assert bm["engine_stamp"]["engine_version"] and bm["audit_input"]["fees_recorded"] is True
    assert saved["bm"] is bm and "__CHART_DATA__" in md and "strategy_vs_spy" in md
    assert "SPY" in md and f"/strategies/{new_id}" in md
    assert "audit" not in md.lower() and "audit" in bm      # verdict stored, not shown


def test_routes_signed_out_redirect_and_signed_in_kicks_off_backtest(db, monkeypatch):
    from starlette.testclient import TestClient
    import app as app_module
    from engine.web import ph_leaderboard as lb
    c = TestClient(app_module.app)
    r = c.get("/strategies/7/clone", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/signin")
    assert "next=/strategies/7/clone" in r.headers["location"]
    r = c.post("/strategies/7/clone", follow_redirects=False)
    assert r.status_code == 303 and "next=/strategies/7/clone" in r.headers["location"]
    monkeypatch.setattr(lb, "_user", lambda session: USER)
    r = c.post("/strategies/7/clone", follow_redirects=False)
    loc = r.headers["location"]
    assert r.status_code == 303 and loc.startswith("/app?new=1&autorun=")
    assert "backtest-strategy%20101%20cloned" in loc
    r2 = c.get("/strategies/7/clone", follow_redirects=False)   # ?next landing, idempotent
    assert r2.headers["location"] == loc
    assert c.post("/strategies/9/clone", follow_redirects=False).status_code == 404


def test_no_live_flags_anywhere(db):
    new_id, _ = clone_bt.clone_strategy(7, USER)
    assert db.strats[new_id]["live_strategy_slug"] is None
    assert all(c["is_live"] is False for c in db.configs.values())
    sql = (Path(__file__).resolve().parents[1] / "sql/47_user_strategy_configs.sql").read_text()
    assert "CHECK (is_live = FALSE)" in sql
    src = (Path(__file__).resolve().parents[1] / "engine/leaderboard/clone_bt.py").read_text()
    for bad in ("submit_order", "strategy_allocations (", "INSERT INTO alpatrade.strategy_configs"):
        assert bad not in src


def test_actions_buttons_and_copy_toast():
    from engine.web import ph_leaderboard as lb
    s = {"id": 5, "user_id": "u", "name": "X", "skill_md": "x"}
    out = lb._actions(s, None)
    assert "href='/strategies/5/clone'" in out and "Clone strategy" in out and "lbCopyClip(5)" in out
    assert "action='/strategies/5/clone'" in lb._actions(s, {"user_id": "other"})
    assert "Run backtest" in lb._actions(s, {"user_id": "u"})
    assert "toast('Copied" in lb.LB_JS


def test_chat_renders_strategy_vs_spy_chart():
    from engine.web import ph_chat
    assert "data.type==='strategy_vs_spy'" in ph_chat.CHAT_JS and "/backtest-strategy" in Path(ph_chat.__file__).read_text()


def test_clone_name():
    assert store.clone_name("Mag-7 Buy-the-Dip · 3-day hold (live)") == "Mag-7 Buy-the-Dip · 3-day hold — clone"
    assert store.clone_name("X (live) (copy)") == "X — clone"
    assert store.clone_name("X — clone") == "X — clone"


def test_btd_stop_reaches_engine_and_min_eq_max_hold_fixes_entry_count(db, monkeypatch):
    """#37: with min_hold == max_hold every position lives exactly max_hold days, so entries (and
    the trade count) don't depend on the stop; the stop must still reach the engine."""
    seen = {}
    import utils.buy_the_dip as btd
    monkeypatch.setattr(btd, "backtest_buy_the_dip", lambda syms, a, b, **kw: seen.update(kw) or None)
    with pytest.raises(RuntimeError):
        clone_bt._btd({"sl": 2.0, "tp": 8.0, "dip": 3.0, "min_hold": 3, "max_hold": 3}, "2020-01-01", "2020-02-01", print)
    assert seen["stop_loss"] == 0.02 and seen["min_hold_days"] == 3 and seen["hold_days"] == 3
