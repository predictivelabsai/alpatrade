import json
from unittest.mock import patch

import pandas as pd

from agents.premarket_agent import PremarketAgent
from engine.premarket import (
    US_SECTORS,
    _movement,
    build_report,
    flatten,
    top_movers,
    universe_entries,
)
from engine.publicmarkets.news import news_category
from engine.web.ph_premarket import _payload


def _row(ticker, sector, move):
    return {
        "ticker": ticker, "company_name": ticker, "sector": sector,
        "prev_close": 100.0, "premarket_close": 100.0 + move,
        "premarket_high": 102.0, "premarket_low": 98.0,
        "movement_abs": move, "movement_pct": move, "history": [],
    }


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
def test_report_ranks_gainers_fallers_and_sector_breadth(enrich):
    report = build_report([
        _row("AAPL", "Technology", 5),
        _row("MSFT", "Technology", 2),
        _row("PFE", "Healthcare", -4),
    ])
    top = top_movers(report, 2)

    assert report["summary"]["total_stocks_attempted"] == 165
    assert report["summary"]["total_up_movements"] == 2
    assert [row["ticker"] for row in top["gainers"]] == ["AAPL", "MSFT"]
    assert [row["ticker"] for row in top["fallers"]] == ["PFE"]
    assert report["sectors"]["Technology"]["total_gainers"] == 2
    enrich.assert_called_once()


def test_flatten_deduplicates_cross_sector_tickers():
    report = {"sectors": {
        "Technology": {"up": [_row("AMZN", "Technology", 2)], "down": []},
        "Consumer Discretionary": {
            "up": [_row("AMZN", "Consumer Discretionary", 2)], "down": []},
    }}
    assert [row["ticker"] for row in flatten(report)] == ["AMZN"]


def test_ui_payload_contains_all_three_rankings():
    report = {"scan_timestamp": "2026-07-28", "summary": {}, "sectors": {
        "Technology": {"up": [_row("AAPL", "Technology", 3)], "down": []},
        "Healthcare": {"up": [], "down": [_row("PFE", "Healthcare", -2)]},
    }}
    assert set(_payload(report, 10)["top"]) == {"gainers", "fallers", "movers"}


def test_news_categories_cover_main_premarket_catalysts():
    assert news_category("earnings releases", "") == "Earnings & guidance"
    assert news_category("", "Company receives FDA approval") == "Clinical & regulatory"
    assert news_category("partnerships", "") == "M&A & partnerships"


def test_agent_uses_latest_report_without_refresh():
    report = {"scan_timestamp": "2026-07-28", "summary": {}, "sectors": {}}
    with patch("agents.premarket_agent.latest_report", return_value=report):
        result = PremarketAgent().run()
    assert result["agent"] == "Premarket Agent"
    assert result["status"] == "complete"


def test_chat_tool_returns_agent_report():
    with patch.object(PremarketAgent, "report", return_value="# Premarket movers") as report:
        from agui_app import get_premarket_movers
        result = get_premarket_movers(limit=5)
    assert result == "# Premarket movers"
    report.assert_called_once_with(limit=5)


def test_report_is_json_serializable():
    with patch("engine.premarket._attach_catalysts"):
        report = build_report([_row("AAPL", "Technology", 1)])
    assert json.loads(json.dumps(report))["status"] == "complete"


def test_premarket_routes_are_registered():
    import app
    paths = {getattr(route, "path", "") for route in app.app.routes}
    assert {"/premarket", "/premarket/data", "/premarket/scan"} <= paths
