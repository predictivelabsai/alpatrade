from unittest.mock import patch

from engine.research.data import (
    _flatten_report,
    correlation_summary,
    premarket_runs,
    premarket_snapshot,
)
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


def test_research_query_schema_convention():
    import inspect
    from engine.research import data

    source = inspect.getsource(data)
    # Shared Finespresso relations stay in public.
    for relation in (
        "public.news", "public.price_moves_data", "public.classifier_predictions",
        "public.regressor_predictions",
    ):
        assert relation in source
    # Premarket scans are AlpaTrade-owned (sql/16) and read from the alpatrade schema.
    assert "alpatrade.premarket_scan_runs" in source
    assert "public.premarket_scan_runs" not in source
    assert "public.premarket_scan_results" not in source


def test_premarket_runs_reads_alpatrade_scan_timestamp():
    captured = {}

    def fake_rows(sql, params=None):
        captured.update(sql=sql, params=params or {})
        return []

    with patch("engine.research.data._rows", side_effect=fake_rows):
        assert premarket_runs(5) == []
    assert "alpatrade.premarket_scan_runs" in captured["sql"]
    assert "scan_timestamp AS timestamp" in captured["sql"]
    assert captured["params"]["limit"] == 5


def test_flatten_report_dedupes_and_drops_blobs():
    report = {"sectors": {"Technology": {
        "up": [{"ticker": "AAPL", "sector": "Technology", "movement_pct": 2.5,
                "premarket_close": 105.0, "history": [{"price": 1}], "catalysts": [{}],
                "ai_reasoning": "x", "ai_sources": [{}]}],
        "down": [{"ticker": "MSFT", "sector": "Technology", "movement_pct": -4.0,
                  "premarket_close": 99.0}]},
        "Consumer Discretionary": {
            "up": [{"ticker": "AMZN", "sector": "Consumer Discretionary",
                    "movement_pct": 3.0}], "down": []}}}
    assert _flatten_report(report) == [
        {"ticker": "AAPL", "sector": "Technology", "movement_pct": 2.5,
         "premarket_close": 105.0},
        {"ticker": "MSFT", "sector": "Technology", "movement_pct": -4.0,
         "premarket_close": 99.0},
        {"ticker": "AMZN", "sector": "Consumer Discretionary", "movement_pct": 3.0},
    ]


def test_premarket_snapshot_sorts_and_limits():
    report = {"sectors": {"Technology": {
        "up": [{"ticker": "AAPL", "movement_pct": 2.5}],
        "down": [{"ticker": "MSFT", "movement_pct": -4.0}]}}}
    with patch("engine.research.data._rows", return_value=[
            {"run_id": "u1", "timestamp": "2026-09-03", "report": report}]):
        rows = premarket_snapshot(limit=1)
    assert [row["ticker"] for row in rows] == ["MSFT"]


def test_premarket_snapshot_accepts_jsonb_text_and_run_id():
    captured = {}

    def fake_rows(sql, params=None):
        captured.update(sql=sql, params=params or {})
        return [{"run_id": "u1", "timestamp": "2026-09-03",
                 "report": '{"sectors": {"Technology": {"up": '
                           '[{"ticker": "AAPL", "movement_pct": 1.0}], "down": []}}}'}]

    with patch("engine.research.data._rows", side_effect=fake_rows):
        rows = premarket_snapshot(run_id="u1")
    assert [row["ticker"] for row in rows] == ["AAPL"]
    assert "run_id=:run_id" in captured["sql"]
    assert captured["params"]["run_id"] == "u1"


def test_premarket_snapshot_returns_empty_without_runs():
    with patch("engine.research.data._rows", return_value=[]):
        assert premarket_snapshot() == []


def test_research_json_replaces_non_finite_database_values():
    assert _json_content({"value": float("nan"), "nested": [float("inf"), 1.5]}) == {
        "value": None, "nested": [None, 1.5],
    }
