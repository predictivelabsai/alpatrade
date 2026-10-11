"""Activation points: Leaderboard rows, strategy pages, My strategies, dashboard (no chat needed)."""
from engine.leaderboard import activate as act
from engine.web import ph_leaderboard as lb


def test_controls_by_state():
    h = act.controls_html(9, None)
    assert "/strategies/9/activate/paper" in h and "/strategies/9/activate/live" in h and "act-badge" not in h
    h = act.controls_html(9, {"paper": "running", "live": "active", "allocation": 500}, back="/dashboard")
    assert "Paper running" in h and "Live running · $500" in h
    assert "/strategies/9/paper/stop" in h and "/strategies/9/live/pause" in h and "/strategies/9/live/deactivate" in h
    assert "activate/live" not in h and "name='back' value='/dashboard'" in h
    h = act.controls_html(9, {"live": "paused"})
    assert "Live paused" in h and "/strategies/9/live/resume" in h
    h = act.controls_html(9, {"paper": "ended", "live": "deactivated"})
    assert "Activate Paper" in h and "Activate Live" in h and "Paper stopped" in h


def test_leaderboard_row_buttons():
    s = {"id": 3, "name": "x", "author": "a", "user_id": "other"}
    signed_in = lb._row(1, s, {}, {"user_id": "me"})
    assert "/strategies/3/activate/paper" in signed_in and "/strategies/3/activate/live" in signed_in
    assert "value='/leaderboard#strategy-3'" in signed_in
    out = lb._row(1, s, {}, None)
    assert "/strategies/3/clone" in out and "activate/paper" not in out


def test_my_strategies_lists_clone_with_controls():
    rows = [({"id": 39, "name": "Mag-7 clone", "author": "k", "user_id": "me", "kind": "backtest"}, {})]
    h = lb.my_strategies_html(rows, statuses={39: {"paper": "starting"}})
    assert "my-strategy-39" in h and "Paper starting" in h and "/strategies/39/paper/stop" in h
    assert "/strategies/39/activate/live" in h and "value='/strategies'" in h


def test_dashboard_panel(monkeypatch):
    from engine.leaderboard import store
    from engine.web import ph_pnl
    monkeypatch.setattr(store, "list_for_user", lambda uid: [
        {"id": 39, "name": "Clone", "kind": "backtest"}, {"id": 1, "name": "Julian live", "kind": "live"}])
    monkeypatch.setattr(act, "statuses", lambda uid: {39: {"live": "paused"}})
    h = ph_pnl.my_strategies_panel("u")
    assert "id='my-strategies'" in h and "Live paused" in h and "/strategies/39/live/resume" in h
    assert "Julian live" not in h


def test_own_or_clone(monkeypatch):
    from engine.leaderboard import clone_bt
    monkeypatch.setattr(clone_bt, "clone_strategy", lambda sid, user: (77, True) if sid == 3 else None)
    assert act.own_or_clone(3, {"user_id": "me"}) == 77 and act.own_or_clone(4, {"user_id": "me"}) is None
