"""Regression tests for per-user Alpaca credential resolution in the chat tools.

The chat agent is built once and shared across users, so its Alpaca tools
(``get_alpaca_positions``, ``get_alpaca_account``, ``place_paper_order``, …)
must resolve the *signed-in user's* keys from ``user_accounts`` — never the
shared ``ALPACA_PAPER_API_KEY``/``SECRET`` env account. These tests pin that
behaviour at the tool level (no live broker / DB access).
"""
import pytest
from unittest import mock

import agui_app


@pytest.fixture(autouse=True)
def _reset_user_context():
    """Ensure the per-request user context does not leak between tests."""
    yield
    agui_app._current_user_id.set(None)
    agui_app._current_account_id.set(None)


def _fake_client(positions=None, account=None):
    client = mock.MagicMock()
    client.get_positions.return_value = positions if positions is not None else []
    client.get_account.return_value = account or {}
    return client


def test_alpaca_client_uses_per_user_keys():
    """A signed-in user with a linked account gets their own keys, not env."""
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client()
        client = agui_app._alpaca_client()
        gk.assert_called_once_with("user-123", None)
        api_cls.assert_called_once_with(api_key="PK1", secret_key="SK1", paper=True)
        assert client is api_cls.return_value


def test_alpaca_client_raises_when_no_linked_account():
    """A signed-in user with no linked account must NOT fall back to env keys."""
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        with pytest.raises(agui_app._NoLinkedAccount):
            agui_app._alpaca_client()
        api_cls.assert_not_called()


def test_alpaca_client_falls_back_to_env_when_anonymous():
    """Anonymous (no user in context) keeps the legacy env-key behaviour."""
    agui_app.set_request_user(None)
    with mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client()
        agui_app._alpaca_client()
        api_cls.assert_called_once_with(paper=True)


def test_get_alpaca_positions_uses_user_keys():
    """get_alpaca_positions resolves the signed-in user's account."""
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        result = agui_app.get_alpaca_positions()
        assert result == "No open positions."
        api_cls.assert_called_once_with(api_key="PK1", secret_key="SK1", paper=True)


def test_get_alpaca_positions_no_linked_account_message():
    """A signed-in user with no account gets a clear message, not env positions."""
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None):
        result = agui_app.get_alpaca_positions()
        assert "No linked Alpaca account" in result


def test_get_alpaca_account_no_linked_account_message():
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None):
        result = agui_app.get_alpaca_account()
        assert "No linked Alpaca account" in result


def test_place_paper_order_no_linked_account_message():
    agui_app.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None):
        result = agui_app.place_paper_order(symbol="AAPL", qty=1, confirm=True)
        assert "No linked Alpaca account" in result


def test_list_user_accounts_scoped_to_current_user():
    """list_user_accounts must only show the signed-in user's accounts."""
    agui_app.set_request_user("user-123")
    accounts = [{"account_id": "a1", "account_name": "My Paper", "created_at": "2026-01-01"}]
    with mock.patch("engine.auth.get_user_accounts", return_value=accounts) as gua:
        result = agui_app.list_user_accounts()
        gua.assert_called_once_with("user-123")
        assert "My Paper" in result


def test_list_user_accounts_requires_login():
    agui_app.set_request_user(None)
    result = agui_app.list_user_accounts()
    assert "Not logged in" in result
