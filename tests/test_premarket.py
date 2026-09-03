import json
from unittest.mock import MagicMock, patch

import pandas as pd

from agents.premarket_agent import PremarketAgent
from engine.premarket import (
    US_SECTORS,
    _json_safe,
    _movement,
    build_report,
    flatten,
    latest_report,
    scan_premarket,
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


def test_json_safe_replaces_non_finite_floats():
    payload = _json_safe({"a": float("nan"), "b": [1.5, float("inf")],
                          "c": {"d": float("-inf")}, "e": "x", "f": 3})
    assert payload == {"a": None, "b": [1.5, None], "c": {"d": None}, "e": "x", "f": 3}


def test_movement_survives_non_finite_bars():
    index = pd.to_datetime([
        "2026-07-27 19:55:00+00:00",
        "2026-07-28 08:00:00+00:00",
        "2026-07-28 13:25:00+00:00",
    ])
    frame = pd.DataFrame({
        "Open": [100.0, float("nan"), 104.0],
        "High": [101.0, float("nan"), float("inf")],
        "Low": [99.0, float("nan"), float("nan")],
        "Close": [100.0, float("nan"), 105.0],
        "Volume": [1, 2, 3],
    }, index=index)

    result = _movement("AAPL", frame)

    assert result["prev_close"] == 100.0
    assert result["premarket_close"] == 105.0
    assert result["premarket_open"] == 104.0
    assert result["premarket_high"] == 105.0
    assert result["premarket_low"] == 105.0
    assert json.dumps(result, allow_nan=False)


def test_movement_skips_day_without_finite_premarket_close():
    index = pd.to_datetime([
        "2026-07-27 19:55:00+00:00",
        "2026-07-28 08:00:00+00:00",
    ])
    frame = pd.DataFrame({
        "Open": [100.0, float("nan")], "High": [101.0, float("nan")],
        "Low": [99.0, float("nan")], "Close": [100.0, float("nan")],
        "Volume": [1, 2],
    }, index=index)
    assert _movement("AAPL", frame) is None


def test_scan_premarket_returns_json_compliant_report():
    cols = pd.MultiIndex.from_product([["AAPL"], ["Open", "High", "Low", "Close", "Volume"]])
    index = pd.to_datetime([
        "2026-07-27 19:55:00+00:00",
        "2026-07-28 08:00:00+00:00",
        "2026-07-28 13:25:00+00:00",
    ])
    data = pd.DataFrame(
        [[100.0, 101.0, 99.0, 100.0, 10],
         [float("nan"), float("nan"), float("nan"), float("nan"), 20],
         [float("nan"), float("inf"), float("nan"), 105.0, 30]],
        columns=cols, index=index)
    with patch("yfinance.download", return_value=data), \
            patch("engine.premarket._attach_catalysts"), \
            patch("engine.premarket.save_report"):
        report = scan_premarket()

    json.dumps(report, allow_nan=False)
    tech = report["sectors"]["Technology"]
    assert any(row["ticker"] == "AAPL" for row in tech["up"] + tech["down"])


def test_attach_catalysts_with_nan_news_rows_stays_json_safe():
    with patch("engine.publicmarkets.news.search_news") as search:
        search.return_value = [{
            "title": "t", "link": "http://x", "publisher": "p", "summary": "s",
            "event": "e", "predicted_side": "NaN", "predicted_move": float("nan"),
        }]
        report = build_report([_row("AAPL", "Technology", 1)])
    json.dumps(report, allow_nan=False)


def test_search_news_nulls_non_finite_values_from_feed():
    import engine.publicmarkets.news as news_mod
    row = ("Feed title", "https://link", "AAPL", "Apple", None, "earnings",
           "GlobeNewswire", "summary text", "NaN", float("nan"), "en")
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [row]
    with patch.object(news_mod, "DatabasePool") as pool_cls:
        session_ctx = pool_cls.return_value.get_session.return_value
        session_ctx.__enter__.return_value = session
        session_ctx.__exit__.return_value = False
        rows = news_mod.search_news(ticker="AAPL", limit=3)
    assert rows[0]["predicted_move"] is None
    assert rows[0]["predicted_side"] is None


def test_latest_report_sanitizes_legacy_nan_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("PREMARKET_REPORTS_DIR", str(tmp_path))
    (tmp_path / "premarket-screener_20260903_080000.json").write_text(json.dumps(
        {"summary": {}, "sectors": {"Technology": {"up": [{
            "ticker": "AAPL", "movement_pct": float("nan"),
            "premarket_high": float("inf"),
            "catalysts": [{"predicted_move": float("nan")}],
        }], "down": []}}}), )
    with patch("engine.db.pool.DatabasePool", side_effect=RuntimeError("no db")):
        report = latest_report()

    json.dumps(report, allow_nan=False)
    top = top_movers(report, 5)
    assert top["movers"][0]["movement_pct"] == 0.0


def test_ui_payload_survives_nan_rows_through_starlette():
    from starlette.responses import JSONResponse
    report = {"scan_timestamp": "2026-09-03", "summary": {}, "sectors": {
        "Technology": {"up": [_row("AAPL", "Technology", float("nan"))], "down": []}}}
    body = JSONResponse(_payload(report, 10)).body
    assert json.loads(body)["sectors"]["Technology"]["up"][0]["movement_pct"] is None
