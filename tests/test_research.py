from unittest.mock import patch

from fastapi.testclient import TestClient

from engine.research.data import correlation_summary
from engine.research.events import normalize_event
from engine.web.ph_research import _PREMARKET_JS, _json_content


def test_event_aliases_preserve_historical_model_groups():
    assert normalize_event("earnings_releases_and_operating_results") == "earnings"
    assert normalize_event("Managers' Transactions") == "shareholder_event"
    assert normalize_event("negative_profit_warning") == "profit_warning"
    assert normalize_event("A New Event") == "a_new_event"


def test_correlation_summary_groups_event_and_industry():
    source = [
        {"event": "earning", "industry": "Software", "predicted": 1.0, "actual": 2.0,
         "normalized_event": "earnings"},
        {"event": "earnings", "industry": "Software", "predicted": 2.0, "actual": 4.0,
         "normalized_event": "earnings"},
    ]
    with patch("engine.research.data.correlation_data", return_value=source):
        result = correlation_summary(min_samples=2)
    assert result["count"] == 2
    assert result["correlation"] == 1.0
    assert result["matrix"] == [{
        "event": "earnings", "industry": "Software", "count": 2, "correlation": 1.0,
    }]


def test_research_queries_are_explicitly_public_schema():
    import inspect
    from engine.research import data

    source = inspect.getsource(data)
    for relation in (
        "public.news", "public.price_moves_data", "public.premarket_scan_runs",
        "public.premarket_scan_results", "public.classifier_predictions",
        "public.regressor_predictions",
    ):
        assert relation in source


def test_premarket_reader_queries_only_normalized_schema_and_never_writes():
    import inspect
    from engine.research import premarket

    source = inspect.getsource(premarket)
    for relation in (
        "premarket_screener.snapshots",
        "premarket_screener.previous_closes",
        "premarket_screener.companies",
        "premarket_screener.industries",
        "premarket_screener.sectors",
        "premarket_screener.llm_analysis",
        "premarket_screener.calendars",
    ):
        assert relation in source
    assert "INSERT INTO premarket_screener" not in source
    assert "UPDATE premarket_screener" not in source
    assert "DELETE FROM premarket_screener" not in source


def test_premarket_dashboard_has_filters_agent_actions_and_combined_plot():
    assert 'type="date"' in _PREMARKET_JS
    assert 'name="sector"' in _PREMARKET_JS
    assert 'name="top_n"' in _PREMARKET_JS
    assert "Ask Premarket Agent" in _PREMARKET_JS
    assert "fillChat(b.dataset.prompt)" in _PREMARKET_JS
    assert "Sector breadth (count)" in _PREMARKET_JS
    assert "Top movers (%)" in _PREMARKET_JS
    assert "toImageButtonOptions" in _PREMARKET_JS


def test_research_api_rejects_legacy_run_and_normalized_date_combination():
    import app

    response = TestClient(app.app).get(
        "/research/api/premarket?run_id=legacy-id&date=2026-08-07"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "run_id cannot be combined with date"


def test_research_api_forwards_normalized_filters_and_chart_mode():
    import app

    snapshot = {
        "status": "complete",
        "source": "premarket_screener",
        "effective_date": "2026-08-07",
        "as_of": "2026-08-07T09:00:00-04:00",
        "freshness": {"state": "stale", "stale": True},
        "filters": {"sector": "Technology", "ticker": None},
        "available_sectors": ["Technology"],
        "summary": {"total_stocks_scanned": 0},
        "sector_breadth": [],
        "sectors": {},
        "rows": [],
        "top": {"gainers": [], "fallers": [], "movers": []},
    }
    with patch("engine.research.premarket.read_premarket", return_value=snapshot) as read:
        response = TestClient(app.app).get(
            "/research/api/premarket?date=2026-08-07&sector=Technology&top_n=20&chart=none"
        )

    assert response.status_code == 200
    assert response.json()["chart"] is None
    read.assert_called_once_with(
        selected_date="2026-08-07", sector="Technology", ticker=None, top_n=20,
    )


def test_research_json_replaces_non_finite_database_values():
    assert _json_content({"value": float("nan"), "nested": [float("inf"), 1.5]}) == {
        "value": None, "nested": [None, 1.5],
    }
