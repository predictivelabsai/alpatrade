"""DB-free coverage for SPAC market enrichment and screener controls."""
from unittest.mock import MagicMock, patch

from engine.publicmarkets import spacs


def _pool(rows):
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = rows
    pool = MagicMock()
    pool.return_value.get_session.return_value.__enter__.return_value = session
    pool.return_value.get_session.return_value.__exit__.return_value = False
    return pool


def test_spac_list_uses_ipo_price_as_nav_and_calculates_premium():
    row = ("DEALU", "Deal Acquisition", None, "searching", 100_000_000,
           None, None, None, None, None, None, 100_000_000, "NASDAQ", None,
           "NASDAQ", None, 10.0, None)
    with patch.object(spacs, "DatabasePool", _pool([row])), \
            patch.object(spacs, "_quote_map", return_value={"DEALU": 10.25}), \
            patch.object(spacs, "_provider_rows", return_value={}):
        result = spacs.spac_list()

    assert result[0]["trust_size"] == 100_000_000
    assert result[0]["trust_per_share"] == 10.0
    assert result[0]["price"] == 10.25
    assert result[0]["nav_premium_pct"] == 2.5
    assert result[0]["exchange"] == "NASDAQ"


def test_spac_list_uses_provider_sponsor_and_target_when_configured():
    row = ("DEALU", "Deal Acquisition", None, "searching", None, None,
           10.0, None, None, None, None, None, "NASDAQ", None, None, None,
           10.0, None)
    provider = {"DEALU": {"sponsors": "Example Sponsor", "targetName": "Target Co",
                            "stage": "3. Target Announced", "trustSharePrice": 10.0}}
    with patch.object(spacs, "DatabasePool", _pool([row])), \
            patch.object(spacs, "_quote_map", return_value={}), \
            patch.object(spacs, "_provider_rows", return_value=provider):
        result = spacs.spac_list()

    assert result[0]["sponsor"] == "Example Sponsor"
    assert result[0]["target"] == "Target Co"
    assert result[0]["status"] == "3. Target Announced"


def test_spac_page_exposes_search_filter_and_sort_controls():
    from engine.web import ph_spacs
    with patch("engine.publicmarkets.spacs.spac_list", return_value=[]):
        html = str(ph_spacs._page(None))
    assert 'name="q"' in html
    assert 'name="status"' in html
    assert 'name="sort"' in html
    assert "spac-table-wrap" in html
