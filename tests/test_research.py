import json
from unittest.mock import MagicMock, patch

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


def test_extract_tickers_uses_known_universe(monkeypatch):
    import engine.research.news_intel as ni

    monkeypatch.setattr(ni, "ticker_map", lambda: {
        "AAPL": {"company": "Apple", "sector": "Technology"},
        "MSFT": {"company": "Microsoft", "sector": "Technology"},
        "AI": {"company": "C3.ai", "sector": "Technology"},
    })
    assert ni.extract_tickers("Chip rally: $AAPL jumps while MSFT slips") == ["AAPL", "MSFT"]
    assert ni.extract_tickers("FED GDP REPORT SHOCKS WALL STREET") == []
    # Word-collision symbols need the $ prefix; $AI still matches C3.ai.
    assert ni.extract_tickers("AI is transforming everything") == []
    assert ni.extract_tickers("Traders pile into $AI") == ["AI"]


def test_collect_filters_searches_and_enriches(monkeypatch):
    import engine.research.news_intel as ni

    monkeypatch.setattr(ni, "extract_tickers", lambda title, summary: ["AAPL"])
    monkeypatch.setattr(ni, "ticker_map",
                        lambda: {"AAPL": {"company": "Apple", "sector": "Technology"}})
    articles = [
        {"title": "Chip rally lifts Apple", "url": "u1", "summary": "s1",
         "source": "CNBC Markets", "icon": "CNBC", "published": "2026-09-03T10:00:00+00:00"},
        {"title": "Local football results", "url": "u2", "summary": "s2",
         "source": "BBC", "icon": "BBC", "published": "2026-09-03T09:00:00+00:00"},
    ]
    out = ni.collect(query="chip", fetch=lambda: articles)
    assert [row["url"] for row in out["rows"]] == ["u1"]
    assert out["rows"][0]["tickers"] == ["AAPL"]
    assert out["rows"][0]["sector_map"] == {"AAPL": "Technology"}
    assert out["sector_counts"] == {"Technology": 1}
    assert out["sources"] == ["CNBC Markets"]
    assert out["top_tickers"] == [("AAPL", 1)]


def test_collect_source_filter_and_limit(monkeypatch):
    import engine.research.news_intel as ni

    monkeypatch.setattr(ni, "extract_tickers", lambda title, summary: [])
    articles = [{"title": f"t{i}", "url": f"u{i}", "summary": "",
                 "source": "A" if i % 2 else "B", "icon": "X",
                 "published": "2026-09-03T10:00:00+00:00"} for i in range(6)]
    out = ni.collect(source="A", limit=2, fetch=lambda: articles)
    assert len(out["rows"]) == 2
    assert all(row["source"] == "A" for row in out["rows"])


def test_analog_evidence_aggregates_and_drops_nan():
    import engine.research.news_intel as ni

    row = ("AAPL", "up", float("nan"), 0.8)
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [row]
    with patch.object(ni, "DatabasePool") as pool_cls:
        ctx = pool_cls.return_value.get_session.return_value
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = False
        evidence = ni.analog_evidence(["AAPL"])
    assert evidence["AAPL"]["model_side"] == "up"
    assert evidence["AAPL"]["model_avg_move"] is None
    assert evidence["AAPL"]["realized_avg_move"] == 0.8
    assert evidence["AAPL"]["samples"] == 1


def test_analog_evidence_empty_without_tickers():
    import engine.research.news_intel as ni

    with patch.object(ni, "DatabasePool") as pool_cls:
        ni.analog_evidence([])
        pool_cls.assert_not_called()


def test_sector_board_blends_moves_and_ranks():
    from engine.research.news_intel import _sector_board

    items = [
        {"title": "A", "ai": {"sectors": [
            {"sector": "Energy", "direction": "up", "move_pct": 1.0}]}},
        {"title": "B", "ai": {"sectors": [
            {"sector": "Energy", "direction": "down", "move_pct": 2.0},
            {"sector": "Financials", "direction": "up", "move_pct": None}]}},
    ]
    board = _sector_board(items)
    assert board[0]["sector"] == "Energy"
    assert board[0]["mentions"] == 2
    assert board[0]["up"] == 1 and board[0]["down"] == 1
    assert board[0]["expected_move_pct"] == 1.3
    assert board[0]["driver"] == "A"
    assert board[1]["sector"] == "Financials"
    assert board[1]["expected_move_pct"] is None


def test_analyze_with_ai_parses_enriches_and_caches():
    import engine.research.news_intel as ni

    ni._analysis_cache.update({"key": None, "at": 0.0, "data": None})

    class FakeModel:
        model_name = "fake-1"

        def invoke(self, messages):
            content = json.dumps({"items": [{
                "i": 0,
                "sectors": [{"sector": "Technology", "direction": "up",
                             "move_pct": 1.5, "confidence": 0.8}],
                "tickers": ["AAPL"], "thesis": "Chip demand rising",
            }]})
            return type("Response", (), {"content": content})()

    rows = [{"title": "Chip rally", "url": "u1", "summary": "",
             "tickers": ["AAPL"], "sectors": ["Technology"]}]
    out = ni.analyze_with_ai(rows, model=FakeModel())
    assert out["model"] == "fake-1" and out["cached"] is False
    assert out["items"][0]["ai"]["thesis"] == "Chip demand rising"
    assert out["items"][0]["ai"]["sectors"][0]["direction"] == "up"
    assert out["sectors"][0]["sector"] == "Technology"
    assert ni.analyze_with_ai(rows, model=FakeModel())["cached"] is True

    ni._analysis_cache.update({"key": None, "at": 0.0, "data": None})


def test_parse_llm_json_extracts_object_from_prose():
    from engine.research.news_intel import _parse_llm_json

    assert _parse_llm_json('Sure! {"items": []} hope that helps') == {"items": []}
    try:
        _parse_llm_json("no json here")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_news_intelligence_routes_registered():
    import app
    paths = {getattr(route, "path", "") for route in app.app.routes}
    assert {"/research/api/news", "/research/api/news/analyze"} <= paths


def test_research_json_replaces_non_finite_database_values():
    assert _json_content({"value": float("nan"), "nested": [float("inf"), 1.5]}) == {
        "value": None, "nested": [None, 1.5],
    }
