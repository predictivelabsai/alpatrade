"""DB-free contracts for account-scoped web chat persistence and progress."""
import inspect
from pathlib import Path

from fastcore.xml import to_xml

from engine.web.ph_chat import CHAT_JS
from engine.web.ph_layout import PH_JS, _left_pane


def test_sidebar_loads_account_chat_history_and_new_chat_gets_new_thread():
    html = to_xml(_left_pane("app", {"email": "owner@example.com"}))
    assert 'hx-get="/app/chats"' in html
    assert 'id="session-list"' in html
    assert "window.location.href='/app?new=1'" in PH_JS
    assert '<details open class="nav-section">' in html


def test_chat_client_loads_saved_messages_and_supports_owned_delete():
    assert "fetch('/app/chat/history')" in CHAT_JS
    assert "fetch('/app/chats/'+encodeURIComponent(tid),{method:'DELETE'})" in CHAT_JS
    assert "window.ALPA_THREAD_ID" in CHAT_JS
    assert "fetch('/app/chats',{cache:'no-store'})" in CHAT_JS
    assert "window.addEventListener('pageshow',loadConversationList)" in CHAT_JS


def test_chat_client_shows_remote_progress_instead_of_silent_dots():
    assert "type==='progress'" in CHAT_JS
    assert "Connecting to Hermes..." in CHAT_JS
    assert "elapsed_seconds" in CHAT_JS
    assert "setProgress(bubble,'Using '" in CHAT_JS


def test_hermes_gateway_does_not_receive_duplicate_browser_history():
    from engine.web import ph_chat

    source = inspect.getsource(ph_chat._stream)
    assert "Hermes already persists this stable session" in source
    assert "history=None" in source


def test_app_routes_apply_user_ownership_to_history_and_delete():
    from engine.web import ph_chat

    source = inspect.getsource(ph_chat.register)
    assert 'load_conversation_messages(thread_id, user_id=str(uid))' in source
    assert 'conversation_belongs_to_user(thread_id, str(uid))' in source
    assert 'delete_conversation(thread_id, user_id=str(uid))' in source
    assert 'recent = list_conversations(user_id=uid, limit=1)' in source
    assert 'conversation_belongs_to_user(current, uid)' in source


def test_chat_store_qualifies_schema_and_filters_owner():
    source = Path("engine/ai/chat_store.py").read_text(encoding="utf-8")
    assert "alpatrade.chat_conversations" in source
    assert "alpatrade.chat_messages" in source
    assert "c.user_id = CAST(:uid AS UUID)" in source
    assert "user_id = CAST(:uid AS UUID)" in source


def test_gateway_approval_is_disabled_only_inside_isolated_hermes_service():
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    hermes = compose.split("\n  api:", 1)[0]
    assert "HERMES_EXEC_ASK=false" in hermes
    for forbidden in ("DATABASE_URL=", "ALPACA_PAPER_API_KEY=", "JWT_SECRET="):
        assert forbidden not in hermes
