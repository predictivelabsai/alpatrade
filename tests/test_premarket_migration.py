"""DB-free parity and time tests for the shared premarket service."""
from datetime import date, datetime, time, timedelta
from unittest.mock import Mock

import pytest

from engine import premarket_data as data, premarket_providers as provider
from engine import premarket_analysis as analysis
from engine.premarket import flatten, top_movers

DAY = date(2026, 8, 7)


def meta(number=1, ticker="AAA", sector="Technology"):
    return {"company_id": number, "ticker": ticker, "company_name": f"{ticker} Incorporated",
            "sector": sector, "industry": "Software", "exchange_id": 1, "exchange": "Nasdaq"}


def quote(price=105, prior=100):
    return {"prev_close": prior, "premarket_close": price, "accumulated_volume": 1000,
            "as_of": datetime.combine(DAY, time(9), data.ET), "snapshot_id": "legacy:10"}


@pytest.fixture
def source(monkeypatch):
    companies = [meta(), meta(2, "BBB"), meta(3, "CCC", "Energy"), meta(4, "DDD", "Energy"),
                 meta(5, "EEE", "Energy"), meta(6, "FFF", "Technology")]
    observations = {1: quote(110), 2: quote(99), 3: quote(100), 4: quote(None),
                    5: quote(105, None), 6: quote(float("nan"))}
    monkeypatch.setattr(data, "catalog", lambda: companies)
    monkeypatch.setattr(data, "available_dates", lambda: [DAY.isoformat()])
    monkeypatch.setattr(data, "observations", lambda day: observations if day == DAY else {})
    monkeypatch.setattr(analysis, "saved_for_date", lambda *args: {
        1: [{"provider": "grok", "text": "Observed earnings catalyst.", "sources": []}]})
    return companies, observations


def test_complete_universe_counts_are_independent_of_top_limit_and_duplicates(source):
    companies, observations = source
    rows = [data.normalize(company, observations[company["company_id"]], DAY) for company in companies]
    report = data.rank_report(rows + [rows[0]], DAY, limit=1)
    assert report["summary"] == {"total_sectors": 2, "total_stocks_attempted": 6,
        "total_stocks_scanned": 3, "total_stocks_failed": 3, "total_up_movements": 1,
        "total_down_movements": 1, "total_unchanged": 1}
    assert report["sectors"]["Energy"]["total_unchanged"] == 1
    assert report["sectors"]["Energy"]["total_unavailable"] == 2
    assert len(flatten(report)) == 3
    assert [row["ticker"] for row in top_movers(report, 1)["gainers"]] == ["AAA"]
    assert [row["ticker"] for row in top_movers(report, 1)["fallers"]] == ["BBB"]


@pytest.mark.parametrize("price,prior", [(float("inf"), 1), (1, float("nan")), (1, 0),
    (0, 1), (-1, 1), (1, -1), (1e308, 1e-308), (None, 1), ("bad", 1)])
def test_invalid_prices_never_enter_rankings(price, prior):
    row = data.normalize(meta(), quote(price, prior), DAY)
    assert row["available"] is False
    assert row["movement_pct"] is None


def test_small_positive_move_is_not_counted_as_unchanged():
    row = data.normalize(meta(), quote(100.000001), DAY)
    assert data.rank_report([row], DAY)["summary"]["total_up_movements"] == 1


def test_fixed_snapshot_sector_and_saved_preview(source):
    report = data.dashboard(DAY, "Technology", limit=1, now=datetime(2026, 8, 10, tzinfo=data.ET),
                            include_earnings=False)
    assert report["summary"]["total_stocks_attempted"] == 3
    assert report["stale"]
    assert report["sectors"]["Technology"]["up"][0]["analysis_preview"].startswith("Observed")
    assert report["sectors"]["Technology"]["up"][0]["prev_close"] == 100


def test_search_matches_company_and_ticker_without_case_sensitivity(source):
    assert data.search_companies("bbb")[0]["ticker"] == "BBB"
    assert len(data.search_companies("incorporated")) == 6
    assert data.search_companies("no such company") == []
    assert len(data.search_companies("", 1)) == 1


def test_overview_preserves_gemini_preview_when_no_grok_exists(source, monkeypatch):
    monkeypatch.setattr(analysis, "saved_for_date", lambda *args: {
        1: [{"provider": "gemini", "text": "**Historic** [news](https://example.org)"}]})
    report = data.dashboard(DAY, include_earnings=False)
    row = report["sectors"]["Technology"]["up"][0]
    assert row["analysis_preview"] == "Historic news"
    assert row["analysis_provider"] == "gemini"


@pytest.mark.parametrize("day,is_open", [("2026-09-07", False), ("2026-08-08", False),
                                       ("2027-01-04", True), ("2027-01-01", False)])
def test_exchange_calendar_extends_beyond_source_coverage(day, is_open):
    assert bool(data.session_hours(date.fromisoformat(day))) is is_open


def test_calendar_handles_early_close_dst_and_previous_holiday():
    assert data.session_hours(date(2026, 11, 27))["close"].hour == 13
    assert data.previous_session(date(2026, 9, 8)) == date(2026, 9, 4)
    winter = data.session_hours(date(2026, 3, 6))["open"]
    summer = data.session_hours(date(2026, 3, 9))["open"]
    assert winter.hour == summer.hour == 9
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


@pytest.mark.parametrize("value", ["2026-99-01", "2030-01-01", "1969-01-01"])
def test_invalid_and_future_dates(value):
    with pytest.raises(ValueError):
        data.trading_date(value, datetime(2026, 8, 7, tzinfo=data.ET))


@pytest.mark.parametrize("at,live", [("04:15:59", False), ("04:16:00", True),
    ("09:16:19", True), ("09:16:20", False)])
def test_delayed_feed_boundaries(source, monkeypatch, at, live):
    snapshot = Mock(return_value={1: quote()})
    monkeypatch.setattr(provider, "live_observations", snapshot)
    report = data.dashboard(DAY, now=datetime.combine(DAY, time.fromisoformat(at), data.ET),
                            include_earnings=False)
    assert (report["mode"] == "delayed") is live
    assert snapshot.called is live


def test_missing_today_does_not_silently_show_stale_prices(source):
    report = data.dashboard(now=datetime(2026, 8, 10, 10, tzinfo=data.ET), include_earnings=False)
    assert report["trading_date"] == "2026-08-10"
    assert report["status"] == "no_data"
    assert "No usable" in " ".join(report["notices"])


def test_weekend_default_explicitly_shows_latest_session(source):
    report = data.dashboard(now=datetime(2026, 8, 8, 10, tzinfo=data.ET), include_earnings=False)
    assert report["trading_date"] == DAY.isoformat()
    assert "latest stored" in report["notices"][0]


def test_earnings_and_chart_failures_do_not_hide_prices_or_saved_commentary(source, monkeypatch):
    monkeypatch.setattr(provider, "earnings", Mock(side_effect=provider.ProviderUnavailable("offline")))
    monkeypatch.setattr(provider, "chart", Mock(side_effect=provider.ProviderUnavailable("offline")))
    monkeypatch.setattr(data, "session_hours", lambda *args: {"close": datetime(2026, 8, 6, 16, tzinfo=data.ET)})
    report = data.dashboard(DAY, now=datetime(2026, 8, 10, tzinfo=data.ET))
    detail = data.stock_detail("AAA", DAY, now=datetime(2026, 8, 10, tzinfo=data.ET))
    assert report["summary"]["total_stocks_scanned"] == 3
    assert detail["stock"]["premarket_close"] == 110
    assert detail["analyses"][0]["text"].startswith("Observed")
    assert detail["history"] == []


def bar(at, price=105, volume=10):
    return {"t": datetime.fromisoformat(at).timestamp() * 1000, "c": price, "v": volume}


def test_finalization_uses_completed_bars_at_cutoff_never_regular_session(monkeypatch):
    monkeypatch.setattr(provider, "minute_bars", lambda *args: [
        bar("2026-08-07T03:59:00-04:00", 1), bar("2026-08-07T04:00:00-04:00", 101),
        bar("2026-08-07T08:59:00-04:00", 110, 20), bar("2026-08-07T09:00:00-04:00", 500),
        bar("2026-08-07T09:30:00-04:00", 600)])
    result = provider.final_observation(meta(), DAY, 100)
    assert result["premarket_close"] == 110
    assert result["accumulated_volume"] == 30
    assert result["quote_timestamp"] == datetime(2026, 8, 7, 9, tzinfo=data.ET)


def test_snapshot_rejects_previous_day_and_post_cutoff(monkeypatch):
    tickers = [
        {"ticker": "AAA", "min": {**bar("2026-08-07T08:59:00-04:00"), "av": 33}, "prevDay": {"c": 100}},
        {"ticker": "BBB", "min": bar("2026-08-07T09:00:00-04:00"), "prevDay": {"c": 100}},
        {"ticker": "CCC", "min": bar("2026-08-06T08:59:00-04:00"), "prevDay": {"c": 100}}]
    monkeypatch.setattr(provider, "market_snapshot", lambda: tickers)
    result = provider.live_observations([meta(), meta(2, "BBB"), meta(3, "CCC")],
                                       datetime(2026, 8, 7, 11, tzinfo=data.ET))
    assert list(result) == [1]
    assert result[1]["accumulated_volume"] == 33


def test_chart_spans_previous_after_hours_and_selected_morning_only(monkeypatch):
    monkeypatch.setattr(provider, "cached", lambda key, ttl, load: load())
    monkeypatch.setattr(provider, "minute_bars", lambda *args: [
        bar("2026-08-06T15:59:00-04:00"), bar("2026-08-06T16:00:00-04:00"),
        bar("2026-08-06T20:00:00-04:00"), bar("2026-08-07T08:59:00-04:00"),
        bar("2026-08-07T09:00:00-04:00")])
    result = provider.chart("AAA", DAY, {"close": datetime(2026, 8, 6, 16, tzinfo=data.ET),
        "after_hour_close": datetime(2026, 8, 6, 20, tzinfo=data.ET)},
        datetime(2026, 8, 8, tzinfo=data.ET))
    assert [row["session"] for row in result] == ["after_hours", "premarket"]


def test_earnings_selects_bmo_and_previous_session_amc(monkeypatch):
    monkeypatch.setattr(provider, "cached", lambda key, ttl, load: load())
    monkeypatch.setattr(provider, "_get", lambda *args: {"earningsCalendar": [
        {"symbol": "AAA", "date": "2026-08-07", "hour": "bmo"},
        {"symbol": "BBB", "date": "2026-08-06", "hour": "amc"},
        {"symbol": "CCC", "date": "2026-08-07", "hour": "amc"},
        {"symbol": "OUTSIDE", "date": "2026-08-07", "hour": "bmo"}]})
    result = provider.earnings(DAY, date(2026, 8, 6), [meta(), meta(2, "BBB"), meta(3, "CCC")])
    assert [(row["ticker"], row["session"]) for row in result] == [("AAA", "Premarket"), ("BBB", "After hours")]


def test_missing_credentials_fail_without_exposing_transport(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(provider.ProviderUnavailable, match="MASSIVE_API_KEY is not configured"):
        provider._get("massive", "/unused")


def test_full_market_fetch_is_cached_for_sixty_seconds(monkeypatch):
    data._cache.clear()
    getter = Mock(return_value={"tickers": [{"ticker": "AAA"}]})
    monkeypatch.setattr(provider, "_get", getter)
    assert provider.market_snapshot() == provider.market_snapshot()
    getter.assert_called_once()
    data._cache.clear()
