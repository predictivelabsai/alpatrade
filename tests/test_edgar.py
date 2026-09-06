"""Regression tests for normalized SEC filing data and its default feed."""
from unittest.mock import MagicMock, patch


def test_search_filings_uses_actual_edgar_source_fields_and_sorts_latest():
    import engine.publicmarkets.edgar as edgar

    payload = {"hits": {"total": {"value": 2}, "hits": [
        {"_source": {"form": "8-K", "display_names": ["Example Corp  (EXM)  (CIK 0000123456)"],
                      "file_date": "2026-09-03", "ciks": ["0000123456"],
                      "adsh": "0000123456-26-000001"}},
        {"_source": {"form": "10-Q", "display_names": ["Earlier Corp  (CIK 0000000007)"],
                      "file_date": "2026-08-30", "ciks": ["0000000007"],
                      "adsh": "0000000007-26-000002"}},
    ]}}
    response = MagicMock()
    response.json.return_value = payload
    with patch.object(edgar, "_get", return_value=response):
        result = edgar.search_filings("results", limit=10)

    assert [row["form_type"] for row in result["results"]] == ["8-K", "10-Q"]
    assert result["results"][0]["entity_name"] == "Example Corp  (EXM)"
    assert result["results"][0]["file_url"].endswith("0000123456-26-000001-index.html")


def test_latest_filings_parses_current_atom_feed_and_filters_form():
    import engine.publicmarkets.edgar as edgar

    atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>8-K - New Corp (0000123456) (Issuer)</title>
       <link rel="alternate" href="https://example.test/new"/>
       <updated>2026-09-04T21:56:31-04:00</updated><category term="8-K"/></entry>
      <entry><title>10-Q - Old Corp (0000000007) (Issuer)</title>
       <link rel="alternate" href="https://example.test/old"/>
       <updated>2026-09-03T21:56:31-04:00</updated><category term="10-Q"/></entry>
    </feed>'''
    response = MagicMock(content=atom)
    edgar._latest_cache = None
    with patch.object(edgar, "_get", return_value=response):
        result = edgar.latest_filings(forms="8-K", limit=10)

    assert result["total"] == 1
    assert result["results"] == [{"form_type": "8-K", "entity_name": "New Corp",
                                   "filing_date": "2026-09-04", "file_url": "https://example.test/new"}]


def test_filings_page_has_latest_default_and_filter_controls(monkeypatch):
    from fastcore.xml import to_xml
    import engine.publicmarkets.edgar as edgar
    from engine.web.ph_filings import _page

    monkeypatch.setattr(edgar, "latest_filings", lambda **kwargs: {
        "total": 1, "results": [{"form_type": "8-K", "entity_name": "Example Corp",
                                   "filing_date": "2026-09-04", "file_url": "#"}]})
    html = to_xml(_page(None))
    assert "Latest SEC filings" in html
    assert 'name="start_date"' in html
    assert 'name="end_date"' in html
    assert 'name="sort"' in html
    assert "Example Corp" in html
