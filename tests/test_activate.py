"""Activate Paper / Activate Live after a clone or backtest (engine/leaderboard/activate.py)."""
import pytest

from engine.leaderboard import activate as act
from utils.strategy_allocation import _PREFIX_RE

UID = "5eae3ba6-e402-49d0-9749-d9fc7d68af30"
MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
CFG = {"template": "buy_the_dip", "params": {"symbols": MAG7, "dip": 3, "tp": 8, "sl": 1.5,
                                              "min_hold": 3, "max_hold": 3, "pos_frac": 0.142857}}
RUNNER_ROWS = [{"name": "buy_the_dip_mag7_minhold_live", "cid_prefix": "btd", "allocation_usd": None,
                "is_primary": True, "config_active": True, "alloc_active": False, "params": {"symbols": MAG7}},
               {"name": "buy_the_dip_semi7_minhold_live", "cid_prefix": "s7btd", "allocation_usd": None,
                "is_primary": False, "config_active": False, "alloc_active": False,
                "params": {"symbols": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"]}}]


@pytest.fixture
def owned(monkeypatch):
    rec = []
    monkeypatch.setattr(act, "_owned", lambda sid, uid: ({"id": sid, "name": "clone", "user_id": uid}, CFG))
    monkeypatch.setattr(act, "_record", lambda *a, **k: rec.append((a, k)))
    return rec


def test_prefix_is_valid_and_never_collides_with_runner():
    p = act.cid_prefix(UID, 39)
    assert _PREFIX_RE.match(p) and p not in ("btd", "s7btd") and p.startswith("u")
    assert act.cid_prefix(UID, 39) == p and act.cid_prefix(UID, 40) != p


def test_paper_needs_keys(owned, monkeypatch):
    monkeypatch.setattr(act, "_paper_account", lambda uid: None)
    r = act.activate_paper(39, UID, enqueue=lambda **k: pytest.fail("queued without keys"))
    assert not r["ok"] and r["needs_keys"] and "Settings > Integrations" in r["message"]


def test_paper_queues_paper_job_on_own_account(owned, monkeypatch):
    monkeypatch.setattr(act, "_paper_account", lambda uid: "acct-1")
    calls = []
    r = act.activate_paper(39, UID, enqueue=lambda **k: calls.append(k) or "job-1")
    assert r["ok"] and calls[0]["kind"] == "deepagent_paper" and calls[0]["account_id"] == "acct-1"
    p = calls[0]["config"]["approved_best_config"]["params"]
    assert p["dip_threshold"] == 0.03 and p["stop_loss_threshold"] == 0.015 and p["hold_days"] == 3
    assert owned[0][0][2] == "paper"


def _live(monkeypatch, alloc, confirm="LIVE", runner_here=False, cash=1000.0):
    monkeypatch.setattr("engine.live_accounts.get_live_account_credentials",
                        lambda uid, acct=None: {"account_number": "777", "api_key": "x", "secret_key": "y"})
    return act.activate_live(39, UID, alloc, confirm, snapshot=lambda c: {"equity": 2000.0, "cash": cash},
                             existing=lambda a: RUNNER_ROWS, runner_account=lambda a: runner_here)


def test_live_needs_keys(owned, monkeypatch):
    monkeypatch.setattr("engine.live_accounts.get_live_account_credentials", lambda uid, acct=None: None)
    r = act.live_plan(39, UID, 100)
    assert r["needs_keys"] and "Settings > Integrations" in r["errors"][0]


def test_live_requires_typed_confirmation_and_cash(owned, monkeypatch):
    assert not _live(monkeypatch, 100, confirm="yes")["ok"]
    r = _live(monkeypatch, 5000)
    assert not r["ok"] and any("free cash" in e for e in r["errors"])
    assert not owned  # nothing recorded


def test_live_records_pending_runner_on_users_own_account(owned, monkeypatch):
    r = _live(monkeypatch, 500)
    assert r["ok"] and "nothing has been ordered" in r["message"]
    (args, kw), = owned
    assert args[2] == "live" and args[4] == "pending_runner" and kw["allocation"] == 500.0
    assert kw["prefix"] == act.cid_prefix(UID, 39)


def test_live_mag7_clone_cannot_overlap_runner_primary(owned, monkeypatch):
    r = _live(monkeypatch, 500, runner_here=True)   # operator account: Mag-7 primary owns those symbols
    assert not r["ok"] and any("universe" in e.lower() or "overlap" in e.lower() or "AAPL" in e for e in r["errors"])


def test_activate_never_touches_runner_config():
    import inspect
    src = inspect.getsource(act)
    for bad in ("INSERT INTO alpatrade.strategy_allocations", "INSERT INTO alpatrade.strategy_configs",
                "UPDATE alpatrade.strategy_configs", "submit_order", "place_order"):
        assert bad not in src


def test_chat_result_has_both_buttons():
    from engine.leaderboard.clone_bt import result_markdown
    bm = {"period_start": "2024-01-01", "period_end": "2026-10-09", "trading_days": 700, "equity_curve": {}}
    md = result_markdown({"id": 39, "name": "clone"}, bm, CFG, {"label": "x", "keys": True})
    assert "/strategies/39/activate/paper" in md and "Activate Paper" in md
    assert "/strategies/39/activate/live" in md and "Activate Live" in md
