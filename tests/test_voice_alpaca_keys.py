"""Regression tests for per-user Alpaca credential resolution in the voice tool.

Julian's ``engine.voice`` resolves the signed-in user's Alpaca keys by passing
``user_id`` as a parameter to ``_get_positions_text(user_id)``: it looks up the
user's accounts via ``get_user_accounts(user_id)``, takes the first account, and
resolves keys with ``get_alpaca_keys(user_id, account_id)``. A signed-in user
with no linked account gets a spoken "Link an Alpaca paper account..." message
- never the shared ``ALPACA_PAPER_API_KEY``/``SECRET`` env account. Anonymous
(``user_id=""``) keeps the legacy env-key path. These tests pin that behaviour
at the tool level (no live broker / DB access).
"""
from unittest import mock

import engine.voice as voice


def _fake_client(positions=None, account=None):
    client = mock.MagicMock()
    client.get_positions.return_value = positions if positions is not None else []
    client.get_account.return_value = account or {}
    return client


def _accounts(*account_ids):
    return [{"account_id": aid, "account_name": f"Acct {aid}"} for aid in account_ids]


def test_get_positions_uses_per_user_keys():
    """A signed-in user with a linked account gets their own keys, not env."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")) as gua, \
         mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        voice._get_positions_text("user-123")
        gua.assert_called_once_with("user-123")
        gk.assert_called_once_with("user-123", "acct-1")
        api_cls.assert_called_once_with(paper=True, api_key="PK1", secret_key="SK1")


def test_get_positions_uses_first_account_id():
    """When a user has several accounts, the first account's id resolves the keys."""
    with mock.patch("engine.auth.get_user_accounts",
                    return_value=_accounts("acct-first", "acct-second")) as gua, \
         mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        voice._get_positions_text("user-123")
        gua.assert_called_once_with("user-123")
        gk.assert_called_once_with("user-123", "acct-first")


def test_get_positions_no_accounts_returns_link_message():
    """A signed-in user with no Alpaca accounts gets a link prompt, not env keys."""
    with mock.patch("engine.auth.get_user_accounts", return_value=[]) as gua, \
         mock.patch("engine.auth.get_alpaca_keys") as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        result = voice._get_positions_text("user-123")
        gua.assert_called_once_with("user-123")
        assert "Link an Alpaca paper account" in result
        gk.assert_not_called()
        api_cls.assert_not_called()


def test_get_positions_no_keys_returns_link_message():
    """A signed-in user whose account has no resolvable keys gets a link prompt."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")), \
         mock.patch("engine.auth.get_alpaca_keys", return_value=None) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        result = voice._get_positions_text("user-123")
        gk.assert_called_once_with("user-123", "acct-1")
        assert "Link an Alpaca paper account" in result
        api_cls.assert_not_called()


def test_get_positions_key_lookup_error_returns_unreachable_message():
    """A DB error while resolving keys must NOT fall back to env keys for a signed-in user."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")), \
         mock.patch("engine.auth.get_alpaca_keys", side_effect=RuntimeError("db down")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        result = voice._get_positions_text("user-123")
        assert "couldn't reach the brokerage account" in result
        assert "db down" in result
        api_cls.assert_not_called()


def test_get_positions_anonymous_uses_env_keys():
    """Anonymous (empty user_id) keeps the legacy env-key behaviour."""
    with mock.patch("engine.auth.get_user_accounts") as gua, \
         mock.patch("engine.auth.get_alpaca_keys") as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        result = voice._get_positions_text("")
        assert "no open positions" in result.lower()
        api_cls.assert_called_once_with(paper=True)
        gua.assert_not_called()
        gk.assert_not_called()


def test_get_positions_no_open_positions_message():
    """A signed-in user with an empty portfolio hears the no-positions summary."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")), \
         mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(
            positions=[], account={"equity": 5000, "cash": 1000})
        result = voice._get_positions_text("user-123")
        assert "no open positions" in result.lower()
        assert "$5,000" in result
        assert "$1,000" in result


def test_get_positions_reads_back_user_positions():
    """A signed-in user's positions are formatted into the spoken summary."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")), \
         mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(
            positions=[
                {"symbol": "AAPL", "qty": 10, "market_value": 1900, "unrealized_pl": 100},
                {"symbol": "MSFT", "qty": 5, "market_value": 2000, "unrealized_pl": -50},
            ],
            account={"equity": 5000, "cash": 1000})
        spoken = voice._get_positions_text("user-123")
        assert "AAPL" in spoken
        assert "MSFT" in spoken
        assert "$5,000" in spoken
        assert "2 open positions" in spoken


def test_get_positions_broker_error_returns_unreachable_message():
    """A broker-side failure (after keys resolved) surfaces a friendly message."""
    with mock.patch("engine.auth.get_user_accounts", return_value=_accounts("acct-1")), \
         mock.patch("engine.auth.get_alpaca_keys", return_value=("PK1", "SK1")), \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        client = _fake_client()
        client.get_account.side_effect = RuntimeError("503 service unavailable")
        api_cls.return_value = client
        result = voice._get_positions_text("user-123")
        assert "couldn't reach the brokerage account" in result
        assert "503 service unavailable" in result


def test_user_id_param_isolates_keys_between_users():
    """Each call resolves keys from its own user_id - no shared mutable state leaks."""
    with mock.patch("engine.auth.get_user_accounts",
                    side_effect=lambda uid: _accounts(f"acct-{uid}")) as gua, \
         mock.patch("engine.auth.get_alpaca_keys",
                    side_effect=lambda uid, aid: (f"PK-{uid}", f"SK-{uid}")) as gk, \
         mock.patch("engine.brokers.alpaca.AlpacaAPI") as api_cls:
        api_cls.return_value = _fake_client(positions=[])
        voice._get_positions_text("user-A")
        voice._get_positions_text("user-B")
        assert gua.call_args_list == [mock.call("user-A"), mock.call("user-B")]
        assert gk.call_args_list == [
            mock.call("user-A", "acct-user-A"),
            mock.call("user-B", "acct-user-B"),
        ]
        assert api_cls.call_args_list == [
            mock.call(paper=True, api_key="PK-user-A", secret_key="SK-user-A"),
            mock.call(paper=True, api_key="PK-user-B", secret_key="SK-user-B"),
        ]