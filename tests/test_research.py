from unittest.mock import patch

from engine.research.data import correlation_summary
from engine.research.events import normalize_event
from engine.web.ph_research import _json_content


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


def test_research_json_replaces_non_finite_database_values():
    assert _json_content({"value": float("nan"), "nested": [float("inf"), 1.5]}) == {
        "value": None, "nested": [None, 1.5],
    }
