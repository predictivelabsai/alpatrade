import json
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from agents.premarket_agent import PremarketAgent
from engine.premarket import (
    US_SECTORS,
    _movement,
    build_report,
    flatten,
    scan_premarket,
    top_movers,
    universe_entries,
)
from engine.publicmarkets.news import news_category
from engine.research.premarket import (
    PremarketReader,
    PremarketValidationError,
    SchedulerManagedError,
    build_chart_payload,
    chart_marker,
    commentary_markdown,
    legacy_archive_snapshot,
)
from engine.web.ph_premarket import _payload

ET = ZoneInfo("America/New_York")


def _row(ticker, sector, move):
    return {
        "ticker": ticker, "company_name": ticker, "sector": sector,
        "prev_close": 100.0, "premarket_close": 100.0 + move,
        "premarket_high": 102.0, "premarket_low": 98.0,
        "movement_abs": move, "movement_pct": move, "history": [],
    }


class _NormalizedFixture:
    def __init__(self):
        self.snapshot_dates = []

    def __call__(self, sql, params=None):
        params = params or {}
        if "premarket:context" in sql:
            return [{
                "latest_date": date(2026, 8, 7),
                "available_sectors": ["Healthcare", "Technology"],
                "latest_completed_session": date(2026, 8, 20),
                "stale_sessions": 9,
            }]
        if "premarket:latest_date" in sql:
            return [{"latest_date": date(2026, 8, 7)}]
        if "premarket:sectors" in sql:
            return [{"sector": "Healthcare"}, {"sector": "Technology"}]
        if "premarket:latest_completed_session" in sql:
            return [{"session_date": date(2026, 8, 20)}]
        if "premarket:stale_sessions" in sql:
            return [{"session_count": 9}]
        if "premarket:validate_sector" in sql:
            return ([{"sector": "Technology"}]
                    if params.get("sector", "").lower() == "technology" else [])
        if "premarket:validate_ticker" in sql:
            return ([{"ticker": "AAPL"}]
                    if params.get("ticker") == "AAPL" else [])
        if "premarket:snapshot" in sql:
            self.snapshot_dates.append(params["effective_date"])
            if params["effective_date"] != date(2026, 8, 7):
                return []
            rows = [
                {"ticker": "AAPL", "company_name": "Apple", "sector": "Technology",
                 "industry": "Hardware", "prev_close": 100, "premarket_close": 105,
                 "volume": 123456, "ai_reasoning": "Earnings exceeded expectations."},
                {"ticker": "PFE", "company_name": "Pfizer", "sector": "Healthcare",
                 "industry": "Drug Manufacturers", "prev_close": 100,
                 "premarket_close": 96, "volume": 5000, "ai_reasoning": ""},
                {"ticker": "KO", "company_name": "Coca-Cola", "sector": "Technology",
                 "industry": "Beverages", "prev_close": 100, "premarket_close": 100,
                 "volume": 300, "ai_reasoning": ""},
                {"ticker": "BAD", "company_name": "Bad Price", "sector": "Technology",
                 "industry": "Software", "prev_close": 0, "premarket_close": 10,
                 "volume": 1, "ai_reasoning": ""},
            ]
            if params.get("sector"):
                rows = [row for row in rows if row["sector"] == params["sector"]]
            if params.get("ticker"):
                rows = [row for row in rows if row["ticker"] == params["ticker"]]
            return rows
        raise AssertionError(f"Unexpected SQL: {sql}")


def _snapshot(top_n=10):
    return PremarketReader(_NormalizedFixture()).read(
        top_n=top_n,
        now_et=datetime(2026, 8, 21, 8, tzinfo=ET),
    )


def test_finespresso_universe_keeps_165_sector_memberships():
    assert len(US_SECTORS) == 11
    assert len(universe_entries()) == 165


def test_movement_uses_premarket_and_previous_regular_close():
    index = pd.to_datetime([
        "2026-07-27 19:55:00+00:00",
        "2026-07-28 08:00:00+00:00",
        "2026-07-28 13:25:00+00:00",
    ])
    frame = pd.DataFrame({
        "Open": [99, 101, 104], "High": [101, 102, 106],
        "Low": [98, 100, 103], "Close": [100, 101, 105],
        "Volume": [100, 200, 300],
    }, index=index)

    result = _movement("AAPL", frame)

    assert result["prev_close"] == 100
    assert result["premarket_close"] == 105
    assert result["movement_pct"] == 5
    assert len(result["history"]) == 2


@patch("engine.premarket._attach_catalysts")
def test_legacy_report_helpers_remain_read_compatible(enrich):
    report = build_report([
        _row("AAPL", "Technology", 5),
        _row("MSFT", "Technology", 2),
        _row("PFE", "Healthcare", -4),
    ])
    top = top_movers(report, 2)

    assert [row["ticker"] for row in top["gainers"]] == ["AAPL", "MSFT"]
    assert [row["ticker"] for row in top["fallers"]] == ["PFE"]
    assert report["sectors"]["Technology"]["total_gainers"] == 2
    assert json.loads(json.dumps(report))["status"] == "complete"
    enrich.assert_called_once()


def test_flatten_deduplicates_cross_sector_tickers():
    report = {"sectors": {
        "Technology": {"up": [_row("AMZN", "Technology", 2)], "down": []},
        "Consumer Discretionary": {
            "up": [_row("AMZN", "Consumer Discretionary", 2)], "down": [],
        },
    }}
    assert [row["ticker"] for row in flatten(report)] == ["AMZN"]


def test_normalized_reader_resolves_latest_ranks_and_reports_freshness():
    snapshot = _snapshot(top_n=2)

    assert snapshot["effective_date"] == "2026-08-07"
    assert snapshot["as_of"] == "2026-08-07T09:00:00-04:00"
    assert snapshot["freshness"]["state"] == "stale"
    assert snapshot["freshness"]["stale_sessions"] == 9
    assert snapshot["summary"] == {
        "total_sectors": 2,
        "total_stocks_scanned": 3,
        "total_up_movements": 1,
        "total_down_movements": 1,
        "total_unchanged": 1,
    }
    assert [row["ticker"] for row in snapshot["top"]["movers"]] == ["AAPL", "PFE"]
    assert snapshot["top"]["gainers"][0]["volume"] == 123456
    assert snapshot["top"]["gainers"][0]["ai_reasoning"] == "Earnings exceeded expectations."
    assert "BAD" not in {row["ticker"] for row in snapshot["rows"]}


def test_explicit_historical_date_never_falls_back():
    fixture = _NormalizedFixture()
    snapshot = PremarketReader(fixture).read(
        selected_date="2026-08-06",
        now_et=datetime(2026, 8, 21, 8, tzinfo=ET),
    )

    assert snapshot["status"] == "no_data"
    assert snapshot["effective_date"] == "2026-08-06"
    assert snapshot["as_of"] is None
    assert fixture.snapshot_dates == [date(2026, 8, 6)]


def test_sector_ticker_and_unknown_filter_validation():
    reader = PremarketReader(_NormalizedFixture())
    with pytest.raises(PremarketValidationError, match="mutually exclusive"):
        reader.read(sector="Technology", ticker="AAPL")
    with pytest.raises(PremarketValidationError, match="Unknown premarket sector"):
        reader.read(sector="Not A Sector")
    with pytest.raises(PremarketValidationError, match="Unknown premarket ticker"):
        reader.read(ticker="ZZZZ")

    ticker = reader.read(ticker="aapl", now_et=datetime(2026, 8, 21, 8, tzinfo=ET))
    assert ticker["filters"] == {"sector": None, "ticker": "AAPL"}
    assert [row["ticker"] for row in ticker["rows"]] == ["AAPL"]


def test_chart_payload_supports_both_panels_modes_and_marker():
    snapshot = _snapshot()
    auto = build_chart_payload(snapshot, "auto")
    breadth = build_chart_payload(snapshot, "breadth")
    movers = build_chart_payload(snapshot, "movers")

    assert auto["type"] == "premarket_overview"
    assert auto["breadth"] and auto["gainers"] and auto["fallers"]
    assert breadth["mode"] == "breadth"
    assert movers["mode"] == "movers"
    assert build_chart_payload(snapshot, "none") is None
    assert chart_marker(auto).startswith("__CHART_DATA__")
    assert chart_marker(auto).endswith("__END_CHART__")


def test_legacy_archive_remains_readable_and_filterable():
    rows = [_row("AAPL", "Technology", 3), _row("PFE", "Healthcare", -2)]
    snapshot = legacy_archive_snapshot(
        rows,
        {"run_id": "legacy", "timestamp": datetime(2026, 1, 20, 9, tzinfo=ET)},
        sector="technology",
    )

    assert snapshot["source"] == "public.premarket_scan_results"
    assert snapshot["effective_date"] == "2026-01-20"
    assert snapshot["freshness"]["state"] == "legacy_archive"
    assert [row["ticker"] for row in snapshot["rows"]] == ["AAPL"]


def test_commentary_separates_evidence_watch_conditions_and_risks():
    snapshot = _snapshot()
    snapshot["rows"][0]["ai_reasoning"] = (
        "Buy now. Entry 102. Stop 99. Target 110. Earnings exceeded expectations."
    )

    commentary = commentary_markdown(snapshot)

    assert "## Observed facts" in commentary
    assert "## Stored catalyst evidence" in commentary
    assert "## Watch conditions" in commentary
    assert "## Liquidity and gap-reversal risks" in commentary
    assert "Earnings exceeded expectations." in commentary
    for phrase in ("buy now", "entry 102", "stop 99", "target 110"):
        assert phrase not in commentary.lower()


def test_agent_uses_shared_reader_and_exposes_additive_fields():
    snapshot = _snapshot()
    with patch("agents.premarket_agent.read_premarket", return_value=snapshot):
        result = PremarketAgent().run(limit=5, chart="movers")

    assert result["agent"] == "Premarket Agent"
    assert result["status"] == "complete"
    assert result["effective_date"] == "2026-08-07"
    assert result["freshness"]["stale"] is True
    assert result["commentary"].startswith("# Premarket screening")
    assert result["chart"]["type"] == "premarket_overview"


def test_refresh_is_scheduler_managed_everywhere():
    with pytest.raises(SchedulerManagedError):
        PremarketAgent().run(refresh=True)
    with pytest.raises(SchedulerManagedError):
        scan_premarket()


def test_chat_tool_returns_agent_report_with_requested_filters():
    with patch.object(PremarketAgent, "report", return_value="# Premarket screening") as report:
        from agui_app import get_premarket_movers
        result = get_premarket_movers(
            limit=5, date="2026-08-07", ticker="AAPL", chart="movers",
        )
    assert result == "# Premarket screening"
    report.assert_called_once_with(
        limit=5,
        refresh=False,
        date="2026-08-07",
        sector=None,
        ticker="AAPL",
        chart="movers",
    )


def test_ui_payload_contains_all_three_rankings():
    snapshot = _snapshot()
    assert set(_payload(snapshot, 10)["top"]) == {"gainers", "fallers", "movers"}


def test_news_categories_cover_main_premarket_catalysts():
    assert news_category("earnings releases", "") == "Earnings & guidance"
    assert news_category("", "Company receives FDA approval") == "Clinical & regulatory"
    assert news_category("partnerships", "") == "M&A & partnerships"


def test_premarket_routes_redirect_and_block_scans():
    import app

    client = TestClient(app.app, follow_redirects=False)
    redirect = client.get("/premarket")
    blocked = client.post("/premarket/scan")

    assert redirect.status_code == 308
    assert redirect.headers["location"] == "/research/premarket"
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "scheduler_managed"
    paths = {getattr(route, "path", "") for route in app.app.routes}
    assert {"/premarket", "/premarket/data", "/premarket/scan"} <= paths
