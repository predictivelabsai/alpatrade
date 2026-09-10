"""Browserless HTTP journeys; production visual acceptance is a separate gate."""
from datetime import date
from unittest.mock import Mock

import pytest
from fasthtml.common import fast_app
from starlette.testclient import TestClient

from engine import premarket_data as data, premarket_jobs as jobs
from engine.web import ph_premarket, ph_premarket_v2


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("PREMARKET_V2_ENABLED", "true")
    monkeypatch.setattr(ph_premarket, "_user", lambda session: None)
    app, rt = fast_app(secret_key="test-session-secret")
    ph_premarket.register(app, rt)
    return TestClient(app)


def report():
    row = {"ticker": "AAA", "company_id": 1, "company_name": "A Incorporated", "sector": "Technology",
        "available": True, "movement_pct": 2, "premarket_close": 102, "prev_close": 100,
        "scan_date": "2026-08-07", "analysis_preview": "Saved explanation"}
    return data.rank_report([row], date(2026, 8, 7))


@pytest.mark.parametrize("path", ["/premarket", "/premarket/sectors?sector=Technology",
    "/premarket/history?date=2026-08-07", "/premarket/stocks?q=AAA", "/premarket/stocks/AAA?date=2026-08-07"])
def test_new_pages_share_four_navigation_entries(web, path):
    response = web.get(path)
    assert response.status_code == 200
    for label in ["Overview", "Sector Details", "Historical Data", "Find a Stock"]:
        assert label in response.text
    assert "/static/premarket.js" in response.text


def test_overview_to_sector_and_stock_http_journey(web, monkeypatch):
    dashboard = Mock(return_value=report())
    monkeypatch.setattr(data, "dashboard", dashboard)
    response = web.get("/premarket/data?date=2026-08-07&sector=Technology&limit=3")
    assert response.status_code == 200
    dashboard.assert_called_once_with("2026-08-07", "Technology", 3)
    payload = response.json()
    assert set(payload) >= {"summary", "sectors", "top"}
    assert payload["top"]["gainers"][0]["analysis_preview"] == "Saved explanation"
    monkeypatch.setattr(data, "stock_detail", lambda *args: {"stock": report()["rows"][0], "analyses": [
        {"provider": "gemini", "text": "**Saved** <script>bad</script>", "sources": []}], "history": []})
    detail = web.get("/premarket/stocks/AAA/data?date=2026-08-07").json()
    assert detail["stock"]["prev_close"] == 100
    assert detail["analyses"][0]["provider"] == "gemini"
    assert "<script>" not in detail["analyses"][0]["html"]


def test_company_search_endpoint(web, monkeypatch):
    search = Mock(return_value=[{"ticker": "AAA", "company_name": "A Incorporated"}])
    monkeypatch.setattr(data, "search_companies", search)
    assert web.get("/premarket/companies?q=incorporated").json()["rows"][0]["ticker"] == "AAA"
    search.assert_called_once_with("incorporated")


def test_historical_default_selects_latest_saved_date(web, monkeypatch):
    monkeypatch.setattr(data, "available_dates", lambda: ["2026-08-07"])
    dashboard = Mock(return_value=report())
    monkeypatch.setattr(data, "dashboard", dashboard)
    assert web.get("/premarket/data?historical=true").status_code == 200
    dashboard.assert_called_once_with("2026-08-07", "", 10)


def test_invalid_date_and_missing_ticker_return_actionable_status(web, monkeypatch):
    monkeypatch.setattr(data, "dashboard", Mock(side_effect=ValueError("Select today or an earlier trading date.")))
    assert web.get("/premarket/data?date=2999-01-01").status_code == 400
    monkeypatch.setattr(data, "stock_detail", Mock(side_effect=LookupError("Stock not found.")))
    assert web.get("/premarket/stocks/INVALID/data").status_code == 404


def test_generation_requires_session_and_reuses_or_polls_job(web, monkeypatch):
    url = "/premarket/stocks/AAA/analysis"
    assert web.post(url, json={"date": "2026-08-07"}).status_code == 401
    monkeypatch.setattr(ph_premarket, "_user", lambda session: {"user_id": "test-user"})
    # register captured the original resolver, so use a fresh app for the signed-in session
    app, rt = fast_app(secret_key="test-session-secret")
    ph_premarket.register(app, rt)
    client = TestClient(app)
    request = Mock(return_value={"job_id": "test-job", "status": "queued"})
    monkeypatch.setattr(jobs, "request_analysis", request)
    response = client.post(url, json={"date": "2026-08-07"})
    assert response.status_code == 202
    request.assert_called_once_with("AAA", "2026-08-07", "test-user")
    request.return_value = {"status": "completed", "analysis": {"text": "Saved"}}
    assert client.post(url, json={"date": "2026-08-07"}).status_code == 200
    assert client.post(url, json={"date": "2026-08-07"}, headers={"Origin": "https://foreign.example"}).status_code == 403
    assert client.post(url, data={"date": "2026-08-07"}).status_code == 415
    assert client.post(url, json={}).status_code == 400
    monkeypatch.setattr(jobs, "public_job", lambda _: {"status": "completed"})
    assert client.get("/premarket/jobs/test-job").json()["status"] == "completed"


def test_existing_run_links_and_scan_endpoint_remain_readable(web, monkeypatch):
    saved = report()
    saved["rows"][0]["history"] = [{"timestamp": "2026-08-07T08:59:00-04:00", "price": 102}]
    monkeypatch.setattr(data, "report_by_run", lambda _: saved)
    assert web.get("/premarket/data?run_id=saved").json()["top"]["gainers"][0]["ticker"] == "AAA"
    detail = web.get("/premarket/stocks/AAA/data?run_id=saved").json()
    assert detail["stock"]["premarket_close"] == 102 and len(detail["history"]) == 1
    assert not detail["can_analyze"]
    monkeypatch.setattr("engine.premarket.scan_premarket", lambda: saved)
    assert web.post("/premarket/scan").json()["summary"]["total_stocks_scanned"] == 1


def test_flag_rollback_preserves_legacy_page(web, monkeypatch):
    monkeypatch.setenv("PREMARKET_V2_ENABLED", "false")
    response = web.get("/premarket")
    assert response.status_code == 200
    assert "/static/premarket.js" not in response.text
    assert web.get("/premarket/companies").status_code == 404
    assert web.get("/premarket/history", follow_redirects=False).status_code == 302
