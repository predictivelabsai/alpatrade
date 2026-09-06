"""DB-free contracts for public-market ingestion observability."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def test_data_health_snapshot_reports_freshness_and_field_gaps():
    import engine.publicmarkets.observability as observability

    now = datetime.now(timezone.utc)

    def execute(_statement):
        result = MagicMock()
        result.mappings.return_value.one.return_value = {
            "total": 10, "last_updated": now - timedelta(hours=2),
            "missing_0": 4, "missing_1": 0, "missing_2": 0, "missing_3": 0,
        }
        return result

    session = MagicMock()
    session.execute.side_effect = execute
    with patch.object(observability, "DatabasePool") as pool_cls:
        context = pool_cls.return_value.get_session.return_value
        context.__enter__.return_value = session
        context.__exit__.return_value = False
        snapshot = observability.data_health_snapshot()

    assert len(snapshot) == 5
    assert snapshot[0]["label"] == "Press releases"
    assert snapshot[0]["status"] == "warning"
    assert snapshot[0]["gaps"] == [{"label": "ticker", "count": 4}]


def test_data_health_render_shows_status_slo_and_gaps():
    from engine.web.ph_data_health import _render

    html = _render([{
        "label": "Press releases", "status": "warning", "total": 25,
        "last_updated": datetime(2026, 9, 6, 10, tzinfo=timezone.utc), "age_hours": 2.0,
        "max_age_hours": 24, "gaps": [{"label": "ticker", "count": 8}],
    }])
    assert "Data health" in html
    assert "warning" in html
    assert "24h" in html
    assert "ticker: 8 missing" in html


def test_data_health_page_is_registered_as_monitoring_route():
    import app  # noqa: F401
    from engine.web import ph_layout

    assert ("Data health", "/monitoring/data-health", "data-health") in ph_layout.MONITORING_PAGES
