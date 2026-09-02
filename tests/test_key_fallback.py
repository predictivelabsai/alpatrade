"""Strict Alpaca key resolution.

Signed-in users must never silently fall back to the shared server (.env)
keys; only CLI/anonymous paths (no user context) may use the env fallback.
These tests pin the no-keys behavior of the two resolution points that still
carry an env fallback: utils.alpaca_agent._get_trading_client and
engine.brokers.alpaca.AlpacaAPI.
"""

import os
from unittest import mock

import pytest

# Import at module scope: these modules call load_dotenv() at import time,
# which (re)populates ALPACA_PAPER_* from .env — importing inside a cleared-env
# window would defeat the fixture.
from utils import alpaca_agent  # noqa: E402
from utils.alpaca_agent import _get_trading_client  # noqa: E402
from engine.brokers.alpaca import AlpacaAPI  # noqa: E402


@pytest.fixture
def no_alpaca_env():
    """Remove every ALPACA_PAPER_* variable for the duration of the test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALPACA_PAPER_")}
    with mock.patch.dict(os.environ, env, clear=True):
        yield


def test_get_trading_client_raises_without_any_keys(no_alpaca_env):
    with pytest.raises(RuntimeError):
        _get_trading_client()


def test_alpaca_api_requires_keys(no_alpaca_env):
    with pytest.raises(ValueError):
        AlpacaAPI()


def test_per_user_keys_skip_env(no_alpaca_env):
    """Keys provided via the contextvar must be used as-is, without consulting
    the (cleared) environment."""
    sentinel = object()
    with mock.patch.object(alpaca_agent, "_make_trading_client",
                           return_value=sentinel) as make_client:
        token = alpaca_agent._user_alpaca_keys.set(("user-key", "user-secret"))
        try:
            client = alpaca_agent._get_trading_client()
        finally:
            alpaca_agent._user_alpaca_keys.reset(token)

    assert client is sentinel
    make_client.assert_called_once_with("user-key", "user-secret")