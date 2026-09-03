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
    def __init__(self, update_row=(1,), select_row=None):
        self.update_row = update_row
        self.select_row = select_row
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "RETURNING platform_queries_used" in sql:
            return _Result(self.update_row)
        if "SELECT platform_queries_used" in sql:
            return _Result(self.select_row)
        return _Result(None)


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
    assert auth.platform_queries_used == 1
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


def test_usage_status_reads_counter_without_incrementing(monkeypatch):
    from engine.ai import query_gate

    session = _Session(select_row=(4,))
    monkeypatch.setattr("engine.db.pool.get_pool", lambda: _Pool(session))
    status = query_gate.get_usage_status("user-1", has_byok=False)
    assert status == {
        "funding_source": "platform",
        "platform_queries_used": 4,
        "platform_query_limit": 5,
        "platform_queries_remaining": 1,
        "percent_used": 80,
    }
    assert not any("UPDATE" in sql for sql, _params in session.calls)


def test_usage_warning_appears_at_90_percent_boundary():
    from engine.ai.query_gate import QueryAuthorization, usage_warning

    assert usage_warning(QueryAuthorization(
        "platform", True, platform_queries_used=4, platform_query_limit=5
    )) is None
    warning = usage_warning(QueryAuthorization(
        "platform", True, platform_queries_used=5, platform_query_limit=5
    ))
    assert warning and "used all 5" in warning
    assert usage_warning(QueryAuthorization("byok")) is None


def test_usage_render_discloses_counter_scope():
    from engine.ai.query_gate import render_usage_status

    rendered = render_usage_status({
        "funding_source": "platform",
        "platform_queries_used": 3,
        "platform_query_limit": 5,
        "platform_queries_remaining": 2,
        "percent_used": 60,
    })
    assert "3 / 5 (60%)" in rendered
    assert "Hermes sidecar token/cost usage is not yet included" in rendered


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
