"""DB-free tests for the IPO map + pipeline data layer (liquidround source)."""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

import engine.publicmarkets.ipo as ipo


def setup_function(function):
    # Reset the module-level quote cache between tests.
    ipo._quote_cache.update({"at": 0.0, "prices": {}})


def _session_with(results_by_table):
    """A DatabasePool mock whose execute() routes on the queried table name."""
    session = MagicMock()

    def execute(sql, params=None):
        sql_text = str(sql)
        for table, rows in results_by_table.items():
            if table in sql_text:
                result = MagicMock()
                result.fetchall.return_value = rows
                return result
        raise AssertionError(f"unexpected query: {sql_text[:80]}")

    session.execute.side_effect = execute
    pool_cls = MagicMock()
    pool_cls.return_value.get_session.return_value.__enter__.return_value = session
    pool_cls.return_value.get_session.return_value.__exit__.return_value = False
    return pool_cls


def test_f_maps_nan_and_junk_to_none():
    assert ipo._f(float("nan")) is None
    assert ipo._f(None) is None
    assert ipo._f("12.5") == 12.5
    assert ipo._f("junk") is None


def test_quote_map_parses_batched_closes():
    cols = pd.MultiIndex.from_product([["SPCX", "CAES"], ["Close"]])
    data = pd.DataFrame([[135.0, 10.0], [149.08, 0.0], [150.0, 10.08]], columns=cols)
    with patch("yfinance.download", return_value=data):
        quotes = ipo._quote_map(["SPCX", "CAES"])
    assert quotes == {"SPCX": 150.0, "CAES": 10.08}


def test_quote_map_caches_and_dedupes():
    cols = pd.MultiIndex.from_product([["SPCX"], ["Close"]])
    data = pd.DataFrame([[150.0]], columns=cols)
    with patch("yfinance.download", return_value=data) as dl:
        first = ipo._quote_map(["SPCX", "SPCX"])
        second = ipo._quote_map(["SPCX"])
    assert first == second == {"SPCX": 150.0}
    assert dl.call_count == 1


def test_ipo_map_data_enriches_missing_prices():
    rows = [
        ("PBLS", "Parabilis Medicines", "Healthcare", "NASDAQ", date(2026, 6, 10),
         20.0, float("nan"), 3_161_776_896, float("nan"), "United States", None),
        ("OLD2", "Old Listed Co", "Technology", "NYSE", date(2025, 11, 4),
         10.0, 12.0, 1_000_000, 20.0, "United States", "US"),
    ]
    with patch.object(ipo, "DatabasePool", _session_with({"ipo_data": rows})), \
            patch.object(ipo, "_quote_map", return_value={"PBLS": 39.6}):
        data = ipo.ipo_map_data()

    by_ticker = {i["ticker"]: i for i in data["ipos"]}
    assert by_ticker["PBLS"]["price"] == 39.6
    assert by_ticker["PBLS"]["return_pct"] == 98.0
    assert by_ticker["OLD2"]["return_pct"] == 20.0  # untouched


def test_ipo_map_data_degrades_without_quotes():
    rows = [("PBLS", "Parabilis Medicines", "Healthcare", "NASDAQ", date(2026, 6, 10),
             20.0, float("nan"), 3_161_776_896, float("nan"), "United States", None)]
    with patch.object(ipo, "DatabasePool", _session_with({"ipo_data": rows})), \
            patch.object(ipo, "_quote_map", return_value={}):
        data = ipo.ipo_map_data()
    item = data["ipos"][0]
    assert item["price"] is None and item["return_pct"] is None


def _pipeline_rows():
    return [
        ("SpaceX", "SPCX", "ipo_completed", "Aerospace", "US", "NASDAQ", None,
         None, None, None, None, None, None, None, None, date(2026, 6, 12),
         None, None, None, "ipo_completed"),
        ("SomeCo Holdings", "SMCO", "filed", "Technology", "US", "NASDAQ", None,
         "IPO", None, None, None, 1, None, None, 50_000_000, None, None, None,
         None, "filed"),
        ("UnitCo", "CGCFU", "filed", "SPAC", "US", "UNKNOWN", None, "IPO", None,
         None, None, 1, None, None, 86_250_000, None, None, None, None, "filed"),
        ("Orion180 Insurance Group", "OIG", "filed", "Insurance", "US",
         "UNKNOWN", None, "IPO", None, None, None, 1, None, None, 100_000_000,
         date(2026, 7, 15), None, None, None, "filed"),
        ("MegaPrivate", None, "private", "AI", "US", None, 40e9, "Series X",
         date(2026, 6, 1), 2e9, 5e9, 8, None, None, None, None, 3000,
         "https://example.com", "summary", "private"),
    ]


def _priced_rows():
    return [
        ("SPCX", "SPACE EXPLORATION TECH", "NASDAQ", date(2026, 6, 12), 135.0,
         2437224595456, float("nan"), float("nan")),
        ("SMCO", "SomeCo Holdings", "NASDAQ", date(2026, 8, 28), 14.0,
         900_000_000, 12.0, 15.68),
        ("OLD1", "Old Priced Co", "NYSE", date(2025, 12, 3), 10.0,
         500_000_000, 5.0, 10.5),
    ]


def _pipeline_data(quotes):
    with patch.object(ipo, "DatabasePool", _session_with(
            {"ipo_pipeline": _pipeline_rows(), "ipo_data": _priced_rows()})), \
            patch.object(ipo, "_quote_map", return_value=quotes):
        return ipo.ipo_pipeline_data()


def test_pipeline_reclassifies_priced_and_market_verified_filings():
    rows = _pipeline_data({"CGCFU": 9.97})
    completed = [r for r in rows if r["kind"] == "ipo_completed"]

    # SMCO: filed in the pipeline but priced in ipo_data → completed, adopted.
    smco = next(r for r in completed if r["ticker"] == "SMCO")
    assert smco["status"] == "priced"
    assert smco["expected_date"].startswith("2026-08-28")
    assert smco["proposed_price"] == 14.0
    assert smco["return_pct"] == 12.0

    # SpaceX: source-completed row enriched from the priced index.
    spcx = next(r for r in completed if r["ticker"] == "SPCX")
    assert spcx["proposed_price"] == 135.0
    assert spcx["expected_date"].startswith("2026-06-12")

    # CGCFU: not in the priced dataset but quoting live → market-verified.
    cgcfu = next(r for r in completed if r["ticker"] == "CGCFU")
    assert cgcfu["status"] == "priced (market-verified)"
    assert cgcfu["proposed_price"] == 9.97

    # Completed is ordered most-recent first and topped up from ipo_data.
    dates = [r["expected_date"] for r in completed if r["expected_date"]]
    assert dates == sorted(dates, reverse=True)
    assert any(r["ticker"] == "OLD1" for r in completed)

    # No completed row leaks back into the upcoming table.
    upcoming = [r for r in rows if r["kind"] not in ("private", "ipo_completed")]
    assert {r["ticker"] for r in upcoming} == {"OIG"}


def test_pipeline_flags_overdue_filings_without_pricing_evidence():
    rows = _pipeline_data({})
    oig = next(r for r in rows if r["ticker"] == "OIG")
    assert oig["kind"] == "filed"
    assert oig["status"] == "overdue"  # expected date in the past, never priced
    cgcfu = next(r for r in rows if r["ticker"] == "CGCFU")
    assert cgcfu["kind"] == "filed"  # no quote available → stays upcoming


def test_pipeline_private_rows_unchanged():
    rows = _pipeline_data({})
    private = [r for r in rows if r["kind"] == "private"]
    assert len(private) == 1 and private[0]["valuation"] == 40e9


def test_pipeline_js_uses_date_and_since_ipo_for_completed_table():
    from engine.web.ph_ipomap import _PIPELINE_JS

    assert "<th>IPO date</th>" in _PIPELINE_JS
    assert "<th>Since IPO</th>" in _PIPELINE_JS
    assert "completedTable('pipeline-completed',completed)" in _PIPELINE_JS
    assert "upcomingTable('pipeline-upcoming',upcoming)" in _PIPELINE_JS
    # UNKNOWN exchange is displayed as an em dash, not the raw string.
    assert "toUpperCase()==='UNKNOWN'" in _PIPELINE_JS
