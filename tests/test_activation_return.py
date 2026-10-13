"""A just-activated strategy reads 0.00%: measured from activation vs its allocation, own fills only."""
from datetime import date, datetime, timezone

import pytest

from engine.leaderboard import perf

ROW = {"mode": "live", "status": "pending_runner", "cid_prefix": "ua43796", "allocation_usd": 670,
       "confirmed_at": datetime(2026, 10, 11, 19, 20, tzinfo=timezone.utc)}
S = {"id": 39, "user_id": "u1", "kind": "backtest",
     "backtest_metrics": {"total_return_pct": 10, "spy_return_pct": 40, "period_start": "2016-01-04",
                          "period_end": "2026-10-09"}}


def _m(pnl, today=date(2026, 10, 12), spy=lambda a, b: pytest.fail("no SPY before fills")):
    return perf.activation_metrics(S, today, row_fn=lambda u, i: ROW, pnl_fn=lambda *a: pnl, spy_fn=spy)


def test_zero_at_activation_even_if_account_and_spy_moved():
    m = _m({"realized": 0.0, "unrealized": 0.0, "fills": 0})
    assert m["return_pct"] == 0.0 and m["annualised_pct"] == 0.0 and m["alpha_pct"] is None
    assert m["start_equity"] == 670 and m["is_activation"] and m["start_date"] == date(2026, 10, 11)
    assert perf.pct(m["return_pct"]) in ("+0.00%", "0.00%")


def test_own_fills_only_vs_allocation():
    m = _m({"realized": 3.35, "unrealized": 3.35, "fills": 1}, today=date(2026, 10, 16), spy=lambda a, b: 0.5)
    assert m["return_pct"] == pytest.approx(1.0) and m["alpha_pct"] == pytest.approx(0.5)
    assert m["trading_days"] == 4 and m["annualised_pct"] == pytest.approx(63.0)


def test_not_activated_falls_back_to_backtest(monkeypatch):
    monkeypatch.setattr(perf, "activation_metrics", lambda s, t=None, **k: None)
    m = perf.strategy_metrics(dict(S))
    assert m.get("is_backtest")


def test_activated_strategy_metrics_override_backtest(monkeypatch):
    monkeypatch.setattr(perf, "_activation_row", lambda u, i: ROW)
    monkeypatch.setattr(perf, "_activation_pnl", lambda *a: {"realized": 0, "unrealized": 0, "fills": 0})
    perf.clear_cache()
    m = perf.strategy_metrics(dict(S))
    assert m["is_activation"] and m["return_pct"] == 0.0 and m["alpha_pct"] is None
    perf.clear_cache()
    from engine.web import ph_leaderboard as lb
    cell = lb._annualised_cell(m)
    assert "0.00%" in cell and "excluded" in cell


def test_dashboard_card_shows_since_activation(monkeypatch):
    from engine.leaderboard import activate as act, store
    from engine.web import ph_pnl
    monkeypatch.setattr(store, "list_for_user", lambda uid: [dict(S, name="Clone")])
    monkeypatch.setattr(act, "statuses", lambda uid: {39: {"live": "pending_runner", "allocation": 670}})
    monkeypatch.setattr(perf, "strategy_metrics", lambda s, t=None: _m({"realized": 0, "unrealized": 0, "fills": 0}))
    h = ph_pnl.my_strategies_panel("u1")
    assert "0.00% since activation ($0.00)" in h
