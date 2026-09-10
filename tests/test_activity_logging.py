from contextlib import contextmanager
from pathlib import Path

from fastcore.xml import to_xml


class _Result:
    def __init__(self, rows=None, scalar="11111111-1111-1111-1111-111111111111"):
        self.rows = rows or []
        self.scalar = scalar
    def scalar_one(self): return self.scalar
    def mappings(self): return self
    def all(self): return self.rows


class _Session:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []
    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.rows)


class _Pool:
    def __init__(self, session): self.session = session
    @contextmanager
    def get_session(self): yield self.session


def test_activity_migration_creates_both_tables_and_job_triggers():
    sql = Path("sql/29_activity_logging.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS alpatrade.user_logging" in sql
    assert "CREATE TABLE IF NOT EXISTS alpatrade.agent_logging" in sql
    assert "trg_hermes_agent_logging" in sql
    assert "trg_run_agent_logging" in sql
    assert "trg_autonomy_agent_logging" in sql
    assert "ON CONFLICT (source_table, source_id)" in sql
    assert sql.count("EXCEPTION WHEN OTHERS") == 3


def test_user_log_redacts_keys_and_completes_pending_owned_row(monkeypatch):
    from engine.ai import activity_logging

    session = _Session()
    monkeypatch.setattr(activity_logging, "get_pool", lambda: _Pool(session))
    activity_logging.start_user_log(
        "user-1", "thread-1", "use api_key=xai-secretvalue123 for this"
    )
    activity_logging.complete_user_log(
        "user-1", "thread-1", "Authorization: Bearer private-token",
        {"framework": "hermes", "ignored_secret": "must-not-persist"},
    )
    assert "secretvalue123" not in str(session.calls)
    assert "private-token" not in str(session.calls)
    update_sql, update_params = session.calls[-1]
    assert "status = 'pending'" in update_sql
    assert "user_id = CAST(:uid AS UUID)" in update_sql
    assert update_params["framework"] == "hermes"
    assert "ignored_secret" not in update_params["metadata"]


def test_non_admin_log_queries_are_forcibly_owner_scoped(monkeypatch):
    from engine.ai import activity_logging

    session = _Session()
    monkeypatch.setattr(activity_logging, "get_pool", lambda: _Pool(session))
    activity_logging.list_user_logs("user-1", is_admin=False)
    activity_logging.list_agent_logs("user-1", is_admin=False)
    for sql, params in session.calls:
        assert "l.user_id = CAST(:requester_id AS UUID)" in sql
        assert params["requester_id"] == "user-1"


def test_admin_can_filter_all_logs_by_email(monkeypatch):
    from engine.ai import activity_logging

    session = _Session()
    monkeypatch.setattr(activity_logging, "get_pool", lambda: _Pool(session))
    activity_logging.list_user_logs(
        "admin-1", is_admin=True, email="kaljuvee@gmail.com"
    )
    sql, params = session.calls[0]
    assert "l.user_id = CAST(:requester_id AS UUID)" not in sql
    assert "u.email ILIKE :email" in sql
    assert params["email"] == "%kaljuvee@gmail.com%"


def test_logging_page_shows_private_or_admin_scope(monkeypatch):
    from engine.ai import activity_logging, llm_usage
    from engine.web.ph_logging import _logging_page

    monkeypatch.setattr(activity_logging, "list_user_logs", lambda *a, **k: [])
    monkeypatch.setattr(activity_logging, "list_agent_logs", lambda *a, **k: [])
    monkeypatch.setattr(llm_usage, "list_usage", lambda *a, **k: [])
    monkeypatch.setattr(llm_usage, "usage_summary", lambda *a, **k: [])
    regular = to_xml(_logging_page({
        "user_id": "user-1", "email": "user@example.com", "is_admin": False,
    }))
    admin = to_xml(_logging_page({
        "user_id": "admin-1", "email": "admin@example.com", "is_admin": True,
    }))
    assert "only activity owned by your account" in regular
    assert "Filter by user email" not in regular
    assert "activity for all users" in admin
    assert "Filter by user email" in admin
    assert "LLM usage today" in admin
    assert "Key source" in admin


def test_logging_response_renders_markdown_table_and_escapes_html():
    from engine.web.ph_logging import _render_response

    rendered = str(_render_response(
        "Positions\n| Symbol | P&L |\n|---|---|\n| <AAPL> | +$12 |"
    ))
    assert '<table class="response-table">' in rendered
    assert "<th>Symbol</th>" in rendered
    assert "&lt;AAPL&gt;" in rendered
    assert "<AAPL>" not in rendered


def test_chat_persistence_also_records_activity(monkeypatch):
    from engine.ai import activity_logging, chat_store
    from engine.web.ph_chat import _save_chat_message

    events = []
    monkeypatch.setattr(chat_store, "save_conversation", lambda *a, **k: None)
    monkeypatch.setattr(chat_store, "save_message", lambda *a, **k: None)
    monkeypatch.setattr(
        activity_logging, "start_user_log",
        lambda uid, thread, content: events.append(("start", uid, thread, content)),
    )
    monkeypatch.setattr(
        activity_logging, "complete_user_log",
        lambda uid, thread, content, metadata: events.append(
            ("complete", uid, thread, content, metadata)
        ),
    )
    _save_chat_message("thread-1", "user-1", "user", "Question")
    _save_chat_message(
        "thread-1", "user-1", "assistant", "Answer",
        {"framework": "deepagents"},
    )
    assert events[0] == ("start", "user-1", "thread-1", "Question")
    assert events[1][0:4] == ("complete", "user-1", "thread-1", "Answer")
