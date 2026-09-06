"""DB-free contracts for saved public-market views and daily in-app alerts."""
from datetime import date
from unittest.mock import MagicMock, patch


def test_view_path_keeps_only_supported_filters():
    from engine.publicmarkets.saved_views import view_path

    assert view_path("filings", {"ticker": "AAPL", "forms": "8-K", "ignored": "x"}) \
        == "/filings?ticker=AAPL&forms=8-K"


def test_save_view_rejects_unknown_page_without_touching_database():
    import engine.publicmarkets.saved_views as saved_views

    with patch.object(saved_views, "DatabasePool") as pool:
        assert saved_views.save_view("00000000-0000-0000-0000-000000000001", "Watch", "unknown", {}) is None
        pool.assert_not_called()


def test_delete_view_rejects_malformed_identifier_without_touching_database():
    import engine.publicmarkets.saved_views as saved_views

    with patch.object(saved_views, "DatabasePool") as pool:
        assert not saved_views.delete_view("00000000-0000-0000-0000-000000000001", "not-a-uuid")
        pool.assert_not_called()


def test_generate_daily_alerts_is_idempotent_per_view_and_date():
    import engine.publicmarkets.saved_views as saved_views

    rows = [{"view_id": "00000000-0000-0000-0000-000000000002",
             "user_id": "00000000-0000-0000-0000-000000000001", "name": "New filings",
             "page_key": "filings", "filters": {"ticker": "AAPL"}}]
    select = MagicMock()
    select.mappings.return_value.all.return_value = rows
    insert = MagicMock(rowcount=1)
    session = MagicMock()
    session.execute.side_effect = [select, insert]
    with patch.object(saved_views, "DatabasePool") as pool_cls:
        context = pool_cls.return_value.get_session.return_value
        context.__enter__.return_value = session
        context.__exit__.return_value = False
        assert saved_views.generate_daily_alerts(date(2026, 9, 6)) == 1

    params = session.execute.call_args_list[1].args[1]
    assert params["path"] == "/filings?ticker=AAPL"
    assert params["title"] == "Daily view ready: New filings"


def test_saved_view_page_renders_mobile_friendly_controls_and_alert_inbox():
    from engine.web.ph_saved_views import _render

    html = _render([{
        "view_id": "id", "name": "Upcoming IPOs", "page_key": "ipo-pipeline",
        "path": "/ipo-pipeline", "daily_digest": True,
    }], [{
        "alert_id": "alert", "title": "Daily view ready: Upcoming IPOs",
        "body": "Your saved market view is ready to review.", "target_path": "/ipo-pipeline",
        "read_at": None, "created_at": "2026-09-06T12:00:00Z",
    }], "csrf-test-token")
    assert "Saved views & alerts" in html
    assert "Daily in-app digest" in html
    assert "Alert inbox" in html
    assert "Mark all read" in html
    assert "csrf-test-token" in html
    assert "autocapitalize='characters'" in html


def test_scheduler_starts_saved_view_alert_loop():
    import inspect
    from engine.autonomy import schedule

    assert "_saved_view_alert_loop" in inspect.getsource(schedule.start)


def test_saved_view_csrf_validation_is_session_bound_and_constant_time_safe():
    from engine.web.ph_saved_views import _csrf_token, _valid_csrf

    session = {}
    token = _csrf_token(session)
    assert len(token) >= 32
    assert _valid_csrf(session, token)
    assert not _valid_csrf(session, "other-token")
