from contextlib import contextmanager
import sys
import types

import pytest
from fastcore.xml import to_xml


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Session:
    def __init__(self, update_row=(1,)):
        self.update_row = update_row
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        return _Result(self.update_row if "RETURNING platform_queries_used" in sql else None)


class _Pool:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def get_session(self):
        yield self.session


def test_query_gate_uses_byok_without_touching_database(monkeypatch):
    from engine.ai import query_gate

    monkeypatch.setattr("engine.db.pool.get_pool", lambda: pytest.fail("DB used"))
    auth = query_gate.authorize_query("user-1", has_byok=True)
    assert auth.funding_source == "byok"
    assert auth.platform_slot is False


def test_query_gate_atomically_reserves_platform_allowance(monkeypatch):
    from engine.ai import query_gate

    session = _Session()
    monkeypatch.setattr("engine.db.pool.get_pool", lambda: _Pool(session))
    auth = query_gate.authorize_query("user-1", has_byok=False)
    assert auth.platform_slot is True
    update = next(call for call in session.calls if "RETURNING" in call[0])
    assert "platform_queries_used <" in update[0]
    assert update[1]["query_limit"] == 5


def test_query_gate_blocks_after_allowance(monkeypatch):
    from engine.ai import query_gate

    monkeypatch.setattr(
        "engine.db.pool.get_pool", lambda: _Pool(_Session(update_row=None))
    )
    with pytest.raises(query_gate.QueryLimitExceeded, match="5 platform-funded"):
        query_gate.authorize_query("user-1", has_byok=False)


def test_settings_xai_key_is_never_rendered(monkeypatch):
    from engine.config import Settings
    from engine.web import ph_settings

    secret = "xai-this-must-never-appear"
    monkeypatch.setattr(
        ph_settings, "get_settings",
        lambda _uid: Settings("xai", "grok-4-1-fast-reasoning", "yfinance",
                              "tavily", "deepagents", secret),
    )
    monkeypatch.setattr("engine.auth.get_user_accounts", lambda _uid: [])
    monkeypatch.setattr(
        "engine.auth.get_provider_key_status",
        lambda _uid, _provider: {"configured": True, "hint": "xai-...1234"},
    )
    html = to_xml(ph_settings._settings_page(
        {"user_id": "user-1", "email": "user@example.com"}
    ))
    assert secret not in html
    assert "xai-...1234" in html
    assert "toggleSecret" in html
    assert "Saved credentials are never sent" in html


def test_settings_dict_never_exposes_api_key():
    from engine.config import Settings

    settings = Settings("xai", "model", "yfinance", "tavily", "deepagents",
                        "xai-secret")
    assert "api_key" not in settings.as_dict()
    assert "xai-secret" not in str(settings.as_dict())
    assert "xai-secret" not in repr(settings)


def test_xai_byok_is_passed_directly_without_platform_probe(monkeypatch):
    from engine import config

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )
    monkeypatch.setattr(
        config, "_resolve_xai_model",
        lambda _model: pytest.fail("BYOK must not trigger a platform-key probe"),
    )
    settings = config.Settings(
        "xai", "grok-test", "yfinance", "tavily", "deepagents", "xai-user-key"
    )
    config.build_chat_model(settings)
    assert captured["api_key"] == "xai-user-key"
    assert captured["model"] == "grok-test"
