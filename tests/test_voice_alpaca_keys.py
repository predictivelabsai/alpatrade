"""Regression tests for per-user Alpaca credential resolution in the voice tool.

The /ws/voice proxy is a single long-lived connection handler shared across
users, so its ``get_positions`` tool must resolve the *signed-in user's* keys
from ``user_accounts`` — never the shared ``ALPACA_PAPER_API_KEY``/``SECRET``
env account. These tests pin that behaviour at the tool level (no live
broker / DB access), mirroring ``tests/test_chat_alpaca_keys.py`` for the chat
path.
"""
import pytest
from unittest import mock

import engine.voice as voice


@pytest.fixture(autouse=True)
def _reset_user_context():
    """Ensure the per-request user context does not leak between tests."""
    yield
    voice._current_user_id.set(None)
    voice._current_account_id.set(None)


def _fake_client(positions=None, account=None):
    client = mock.MagicMock()
    client.get_positions.return_value = positions if positions is not None else []
    client.get_account.return_value = account or {}
    return client


def test_alpaca_client_uses_per_user_keys():
    """A signed-in user with a linked account gets their own keys, not env."""
    voice.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client()
        client = voice._alpaca_client()
        gk.assert_called_once_with("user-123", None)
        api_cls.assert_called_once_with(api_key="PK1", secret_key="SK1", paper=True)
        assert client is api_cls.return_value


def test_alpaca_client_passes_account_id():
    """An explicit account_id is forwarded to get_alpaca_keys."""
    voice.set_request_user("user-123", account_id="acct-9")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client()
        voice._alpaca_client()
        gk.assert_called_once_with("user-123", "acct-9")


def test_alpaca_client_raises_when_no_linked_account():
    """A signed-in user with no linked account must NOT fall back to env keys."""
    voice.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        with pytest.raises(voice._NoLinkedAccount):
            voice._alpaca_client()
        api_cls.assert_not_called()


def test_alpaca_client_raises_when_get_alpaca_keys_errors():
    """A DB error resolving keys must NOT fall back to env keys for a signed-in user."""
    voice.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", side_effect=RuntimeError("db down")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        with pytest.raises(voice._NoLinkedAccount):
            voice._alpaca_client()
        api_cls.assert_not_called()


def test_alpaca_client_falls_back_to_env_when_anonymous():
    """Anonymous (no user in context) keeps the legacy env-key behaviour."""
    voice.set_request_user(None)
    with mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client()
        voice._alpaca_client()
        api_cls.assert_called_once_with(paper=True)


def test_get_positions_uses_user_keys():
    """get_positions resolves the signed-in user's account."""
    voice.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        result = voice._get_positions_text()
        assert "no open positions" in result.lower()
        gk.assert_called_once_with("user-123", None)
        api_cls.assert_called_once_with(api_key="PK1", secret_key="SK1", paper=True)


def test_get_positions_no_linked_account_message():
    """A signed-in user with no account gets a clear message, not env positions."""
    voice.set_request_user("user-123")
    with mock.patch("engine.auth.get_alpaca_keys", return_value=None), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        result = voice._get_positions_text()
        assert "linked" in result.lower()
        # The broker must never have been called with the shared env account.
        api_cls.assert_not_called()


def test_get_positions_anonymous_uses_env():
    """Anonymous path keeps legacy env-key behaviour (eval / CLI compatibility)."""
    voice.set_request_user(None)
    with mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        result = voice._get_positions_text()
        assert "no open positions" in result.lower()
        api_cls.assert_called_once_with(paper=True)


def test_get_positions_reads_back_user_positions():
    """A signed-in user's positions are formatted into the spoken summary."""
    voice.set_request_user("user-123")
    positions = [
        {"symbol": "AAPL", "qty": 10, "market_value": 1900, "unrealized_pl": 100},
        {"symbol": "MSFT", "qty": 5, "market_value": 2000, "unrealized_pl": -50},
    ]
    account = {"equity": 5000, "cash": 1000}
    with mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=positions, account=account)
        spoken = voice._get_positions_text()
        assert "AAPL" in spoken
        assert "MSFT" in spoken
        assert "$5,000" in spoken  # equity formatted
        assert "2 open positions" in spoken


def test_context_does_not_leak_between_users():
    """Setting a second user must fully replace the first (no bleed-through)."""
    voice.set_request_user("user-A")
    assert voice._current_user_id.get() == "user-A"
    voice.set_request_user("user-B")
    assert voice._current_user_id.get() == "user-B"
    voice.set_request_user(None)
    assert voice._current_user_id.get() is None