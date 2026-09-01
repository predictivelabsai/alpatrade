"""Regression tests for per-user state isolation in the chat/orchestrator path.

Pins three fixes that stop global mutable state from leaking across users:

1. ``agui_app._app_state`` is now a per-user dict (``get_app_state``) — each
   signed-in user gets their own orchestrator handle, background task and
   command history.
2. ``engine.web.ph_chat._HISTORY`` is keyed by ``(user_id, thread_id)`` so a
   shared thread id can never expose another user's chat history.
3. ``engine.agents.state.PortfolioState`` is scoped by ``user_id`` so concurrent
   runs from different users write to separate state files.

No live broker / DB access — mocks only.
"""
import asyncio

import pytest

import agui_app


@pytest.fixture(autouse=True)
def _reset_state():
    """Clear per-user app state and request context between tests."""
    yield
    agui_app._app_states.clear()
    agui_app._current_user_id.set(None)
    agui_app._current_account_id.set(None)


# ---------------------------------------------------------------------------
# 1. _app_state per-user isolation
# ---------------------------------------------------------------------------

def test_get_app_state_returns_distinct_instances_per_user():
    a = agui_app.get_app_state("user-A")
    b = agui_app.get_app_state("user-B")
    assert a is not b
    # Same user → same instance (stable across calls).
    assert agui_app.get_app_state("user-A") is a


def test_get_app_state_anonymous_key_is_none():
    anon = agui_app.get_app_state(None)
    assert agui_app.get_app_state(None) is anon
    assert agui_app.get_app_state("user-A") is not anon


def test_account_switch_isolated_per_user(monkeypatch):
    from agui_app import _command_interceptor

    accounts = {
        "user-A": [{"account_id": "acc-a", "account_name": "Account A", "api_key_hint": "PK-A"}],
        "user-B": [{"account_id": "acc-b", "account_name": "Account B", "api_key_hint": "PK-B"}],
    }

    monkeypatch.setattr("engine.auth.get_user_accounts", lambda uid: accounts[uid])

    asyncio.run(_command_interceptor("account:switch 1", {"user": {"user_id": "user-A"}}))
    asyncio.run(_command_interceptor("account:switch 1", {"user": {"user_id": "user-B"}}))

    assert agui_app.get_app_state("user-A").account_id == "acc-a"
    assert agui_app.get_app_state("user-B").account_id == "acc-b"


def test_background_task_isolated_per_user():
    a = agui_app.get_app_state("user-A")
    b = agui_app.get_app_state("user-B")
    a._bg_task = object()
    assert a._bg_task is not None
    assert b._bg_task is None


def test_orchestrator_handle_isolated_per_user():
    a = agui_app.get_app_state("user-A")
    b = agui_app.get_app_state("user-B")
    a._orch = object()
    assert a._orch is not None
    assert b._orch is None


def test_command_history_isolated_per_user():
    a = agui_app.get_app_state("user-A")
    b = agui_app.get_app_state("user-B")
    a.command_history.append("positions")
    assert a.command_history == ["positions"]
    assert b.command_history == []


# ---------------------------------------------------------------------------
# 2. _HISTORY keyed by (user_id, thread_id)
# ---------------------------------------------------------------------------

def test_history_key_isolates_users_with_same_thread():
    from engine.web import ph_chat

    assert ph_chat._history_key("user-A", "thread-1") != ph_chat._history_key("user-B", "thread-1")
    assert ph_chat._history_key("user-A", "thread-1") == ph_chat._history_key("user-A", "thread-1")


def test_history_storage_isolated_per_user():
    from engine.web import ph_chat

    ph_chat._HISTORY.clear()
    key_a = ph_chat._history_key("user-A", "thread-1")
    key_b = ph_chat._history_key("user-B", "thread-1")

    ph_chat._HISTORY.setdefault(key_a, []).append({"role": "user", "content": "secret A"})

    assert key_b not in ph_chat._HISTORY
    assert ph_chat._HISTORY[key_a] == [{"role": "user", "content": "secret A"}]


# ---------------------------------------------------------------------------
# 3. PortfolioState scoped by user_id
# ---------------------------------------------------------------------------

def test_portfolio_state_file_scoped_per_user():
    from engine.agents.state import _state_file

    assert _state_file("user-A") != _state_file("user-B")
    assert _state_file(None) == _state_file(None)
    assert str(_state_file("user-A")).endswith("agent_state_user-A.json")


def test_portfolio_state_round_trips_user_id(tmp_path):
    from engine.agents.state import PortfolioState

    p = tmp_path / "state.json"
    s = PortfolioState(run_id="r1", user_id="user-A")
    s.save(p)
    loaded = PortfolioState.load(p)
    assert loaded.user_id == "user-A"
    assert loaded.run_id == "r1"


def test_portfolio_state_load_scopes_by_user(tmp_path, monkeypatch):
    from engine.agents import state as state_mod

    # Point per-user files at a temp dir so we never touch the real data/ dir.
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "agent_state.json")
    monkeypatch.setattr(
        state_mod,
        "_state_file",
        lambda user_id: (tmp_path / f"agent_state_{user_id}.json") if user_id
        else (tmp_path / "agent_state.json"),
    )

    a = state_mod.PortfolioState.load(user_id="user-A")
    a.run_history.append({"run_id": "run-a"})
    a.save()

    b = state_mod.PortfolioState.load(user_id="user-B")
    assert b.run_history == []
    assert b.user_id == "user-B"
