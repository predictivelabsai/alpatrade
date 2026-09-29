"""Per-user daily email report preferences: storage, defaults, both senders and
the Settings UI. Offline — DB, Alpaca and Postmark are faked."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastcore.xml import to_xml

from engine.reporting import preferences as prefs_mod
from engine.reporting.preferences import DEFAULTS, LIVE, PAPER


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Session:
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.calls = list(rows), fail, []

    def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError("relation does not exist")
        self.calls.append((str(statement), params))
        return _Rows(self.rows)


class _Pool:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def get_session(self):
        yield self.session


def _use_pool(monkeypatch, session):
    monkeypatch.setattr(prefs_mod, "_pool", lambda: _Pool(session))
    return session


# ---- storage / defaults ------------------------------------------------------

def test_defaults_are_live_on_paper_off():
    assert DEFAULTS == {LIVE: True, PAPER: False}


def test_users_without_a_row_get_defaults(monkeypatch):
    _use_pool(monkeypatch, _Session(rows=[("u-2", False, True)]))
    out = prefs_mod.preferences_for(["u-1", "u-2"])
    assert out["u-1"] == {LIVE: True, PAPER: False}
    assert out["u-2"] == {LIVE: False, PAPER: True}
    assert prefs_mod.get_report_preferences("u-1") == {LIVE: True, PAPER: False}


def test_lookup_failure_is_reported_as_none_and_page_uses_defaults(monkeypatch):
    _use_pool(monkeypatch, _Session(fail=True))
    assert prefs_mod.preferences_for(["u-1"]) is None
    assert prefs_mod.get_report_preferences("u-1") == DEFAULTS


def test_store_upserts_only_known_boolean_fields(monkeypatch):
    session = _use_pool(monkeypatch, _Session())
    monkeypatch.setattr(prefs_mod, "_ddl_done", False)
    prefs_mod.store_report_preferences("u-1", report_live_daily=0, report_paper_daily=1,
                                       evil="x")
    ddl, _ = session.calls[0]
    sql, params = session.calls[1]
    assert "CREATE TABLE IF NOT EXISTS alpatrade.user_report_preferences" in ddl
    assert "ON CONFLICT (user_id) DO UPDATE" in sql and "evil" not in sql
    assert params == {"user_id": "u-1", LIVE: False, PAPER: True}


def test_store_with_nothing_to_update_is_a_noop(monkeypatch):
    session = _use_pool(monkeypatch, _Session())
    prefs_mod.store_report_preferences("u-1")
    assert session.calls == []


def test_filter_opted_in_skips_and_falls_back_to_legacy(monkeypatch):
    targets = [{"user_id": "u-1"}, {"user_id": "u-2"}]
    monkeypatch.setattr(prefs_mod, "preferences_for",
                        lambda ids: {"u-1": {LIVE: True, PAPER: False},
                                     "u-2": {LIVE: False, PAPER: True}})
    assert prefs_mod.filter_opted_in(targets, PAPER, "paper") == [{"user_id": "u-2"}]
    assert prefs_mod.filter_opted_in(targets, LIVE, "live") == [{"user_id": "u-1"}]
    monkeypatch.setattr(prefs_mod, "preferences_for", lambda ids: None)
    assert prefs_mod.filter_opted_in(targets, PAPER, "paper") == targets


def test_migration_is_idempotent_and_preserves_current_paper_recipients():
    sql = Path("sql/39_user_report_preferences.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS alpatrade.user_report_preferences" in sql
    assert "report_live_daily  BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert "report_paper_daily BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "ON CONFLICT (user_id) DO NOTHING" in sql
    assert "status = 'sent'" in sql and "'daily_paper'" in sql
    import re
    assert not re.search(r"^\s*(DROP|DELETE|TRUNCATE|UPDATE)\b", sql, re.I | re.M)


# ---- live sender -------------------------------------------------------------

@pytest.fixture
def live_sched(monkeypatch):
    from engine.autonomy import schedule
    from scripts import daily_live_report as rep
    from tests.test_daily_live_report import _client

    schedule._live_done.clear()
    schedule._live_closes.clear()
    monkeypatch.setenv("LIVE_REPORT_ENABLED", "true")
    targets = [{"user_id": "u-in", "email": "in@example.com", "account_number": "111",
                "label": "live"},
               {"user_id": "u-out", "email": "out@example.com", "account_number": "222",
                "label": "live"}]
    monkeypatch.setattr(rep, "report_targets", lambda email=None: targets)
    monkeypatch.setattr(rep, "client_for", lambda t: _client())
    sent = []
    monkeypatch.setattr(rep, "send_report",
                        lambda t, day=None, client=None, **k: sent.append(t["email"])
                        or {"sent": True, "message_id": "m"})
    return schedule, sent


AFTER_CLOSE = datetime(2026, 9, 25, 20, 21, tzinfo=timezone.utc)


def test_live_scheduler_skips_opted_out_owner_once(live_sched, monkeypatch, caplog):
    schedule, sent = live_sched
    monkeypatch.setattr(prefs_mod, "preferences_for",
                        lambda ids: {"u-in": {LIVE: True, PAPER: False},
                                     "u-out": {LIVE: False, PAPER: False}})
    with caplog.at_level("INFO", logger="autonomy.schedule"):
        results = schedule.run_due_live_reports(AFTER_CLOSE)
        assert schedule.run_due_live_reports(AFTER_CLOSE) == []
    assert sent == ["in@example.com"]
    assert {"ok": True, "sent": False, "skipped": "opted_out",
            "account_number": "222"} in results
    assert sum("opted out" in r.message for r in caplog.records) == 1


def test_live_scheduler_sends_all_when_preferences_unavailable(live_sched, monkeypatch):
    schedule, sent = live_sched
    monkeypatch.setattr(prefs_mod, "preferences_for", lambda ids: None)
    schedule.run_due_live_reports(AFTER_CLOSE)
    assert sent == ["in@example.com", "out@example.com"]


def test_live_scheduler_does_not_read_preferences_before_close(live_sched, monkeypatch):
    schedule, sent = live_sched
    calls = []
    monkeypatch.setattr(prefs_mod, "preferences_for", lambda ids: calls.append(1) or {})
    schedule.run_due_live_reports(datetime(2026, 9, 25, 20, 10, tzinfo=timezone.utc))
    assert calls == [] and sent == []


# ---- paper sender ------------------------------------------------------------

def test_paper_scheduler_only_emails_opted_in_owners(monkeypatch):
    from engine.autonomy import schedule
    from scripts import daily_pnl_report as paper
    import utils.email_util as email_util

    targets = [{"user_id": u, "account_id": f"a-{u}", "email": f"{u}@example.com",
                "account_name": "Default", "keys": ("k", "s")} for u in ("u-1", "u-2")]
    monkeypatch.setattr(paper, "report_targets", lambda: targets)
    claims, sent = [], []
    monkeypatch.setattr(paper, "claim_report_delivery",
                        lambda uid, aid, day: claims.append(uid) or True)
    monkeypatch.setattr(paper, "finish_report_delivery", lambda *a, **k: None)
    monkeypatch.setattr(paper, "reconcile_stale_runs", lambda *a: 0)
    monkeypatch.setattr(paper, "gather", lambda **k: {"day_pnl": 1.0})
    monkeypatch.setattr(paper, "render", lambda d: "<p>x</p>")
    monkeypatch.setattr(email_util, "send_email_to", lambda to, s, h: sent.append(to) or True)
    monkeypatch.setattr(prefs_mod, "preferences_for",
                        lambda ids: {"u-1": dict(DEFAULTS), "u-2": {LIVE: True, PAPER: True}})
    schedule._run_pnl_report()
    assert claims == ["u-2"]  # opted-out owner never claims a delivery row
    assert sent == ["u-2@example.com"]


# ---- Settings UI -------------------------------------------------------------

def _page(monkeypatch, *, paper: bool, live: bool, stored=None):
    from engine.config import Settings
    from engine.web import ph_settings

    monkeypatch.setattr(ph_settings, "get_settings",
                        lambda _uid: Settings("xai", "grok-4-1-fast-reasoning", "yfinance",
                                              "tavily", "deepagents", None))
    monkeypatch.setattr("engine.auth.get_user_accounts",
                        lambda _uid: [{"account_id": "a-1", "api_key_hint": "PK****"}]
                        if paper else [])
    monkeypatch.setattr("engine.auth.get_provider_key_status",
                        lambda _uid, _p: {"configured": False, "hint": ""})
    monkeypatch.setattr(ph_settings, "_has_live_account", lambda _uid: live)
    monkeypatch.setattr(prefs_mod, "preferences_for",
                        lambda ids: {"user-1": stored or dict(DEFAULTS)})
    return to_xml(ph_settings._settings_page({"user_id": "user-1", "email": "u@example.com"}))


def _checkbox(html: str, field: str) -> str:
    start = html.index(f'id="pref-{field}"')
    return html[html.rindex("<input", 0, start):html.index(">", start) + 1]


def test_settings_shows_both_report_checkboxes_with_defaults(monkeypatch):
    html = _page(monkeypatch, paper=True, live=True)
    assert "Email reports" in html and 'action="/settings/reports"' in html
    assert "Daily live trading report" in html and "Daily paper trading report" in html
    live, paper = _checkbox(html, LIVE), _checkbox(html, PAPER)
    assert "checked" in live and "disabled" not in live
    assert "checked" not in paper and "disabled" not in paper


def test_settings_disables_reports_without_matching_keys(monkeypatch):
    html = _page(monkeypatch, paper=False, live=False,
                 stored={LIVE: True, PAPER: True})
    live, paper = _checkbox(html, LIVE), _checkbox(html, PAPER)
    assert "disabled" in live and "checked" not in live
    assert "disabled" in paper and "checked" not in paper
    assert "Needs a linked live Alpaca account" in html
    assert "Needs your Alpaca paper keys" in html


def _post_client(monkeypatch, *, paper: bool, live: bool):
    from fasthtml.common import fast_app
    from starlette.testclient import TestClient
    from engine.web import ph_settings

    app, rt = fast_app()
    ph_settings.register(app, rt)
    monkeypatch.setattr(ph_settings, "_user", lambda s: {"user_id": "user-1"})
    monkeypatch.setattr(ph_settings, "_has_live_account", lambda _uid: live)
    monkeypatch.setattr(ph_settings, "_has_paper_keys", lambda _uid: paper)
    stored = []
    monkeypatch.setattr(prefs_mod, "store_report_preferences",
                        lambda uid, **f: stored.append((uid, f)))
    return TestClient(app), stored


def test_saving_both_unticked_opts_out_of_everything(monkeypatch):
    client, stored = _post_client(monkeypatch, paper=True, live=True)
    r = client.post("/settings/reports", data={}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings?msg=saved"
    assert stored == [("user-1", {LIVE: False, PAPER: False})]


def test_saving_only_touches_options_the_user_can_toggle(monkeypatch):
    client, stored = _post_client(monkeypatch, paper=True, live=False)
    client.post("/settings/reports", data={PAPER: "1", LIVE: "1"}, follow_redirects=False)
    assert stored == [("user-1", {PAPER: True})]
