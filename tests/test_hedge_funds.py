"""Regression tests for activist filing target/timestamp enrichment."""
from unittest.mock import MagicMock, patch


def test_filing_metadata_reads_subject_filer_and_acceptance_time():
    import engine.publicmarkets.hedge_funds as hedge_funds

    document = b'''<SEC-HEADER>
ACCEPTANCE-DATETIME>20260904164032
SUBJECT COMPANY:
  COMPANY DATA:
    COMPANY CONFORMED NAME: Example Target Inc.
    CENTRAL INDEX KEY: 0000123456
FILED BY:
  COMPANY DATA:
    COMPANY CONFORMED NAME: Example Capital LP
'''
    response = MagicMock(content=document)
    hedge_funds._filing_metadata.cache_clear()
    with patch("engine.publicmarkets.edgar._get", return_value=response):
        metadata = hedge_funds._filing_metadata("https://example.test/filing.txt")

    assert metadata == {"subject": "Example Target Inc.", "subject_cik": "0000123456",
                        "filer": "Example Capital LP", "filed_at": "2026-09-04 16:40 ET"}


def test_activist_filings_enriches_empty_target_and_ticker():
    import engine.publicmarkets.hedge_funds as hedge_funds

    row = ("Old parser name", None, None, None, "SCHEDULE 13D", "2026-09-04", "https://example.test/a")
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [row]
    with patch.object(hedge_funds, "DatabasePool") as pool_cls, \
         patch.object(hedge_funds, "_filing_metadata", return_value={
             "filer": "Example Capital", "subject": "Example Target", "subject_cik": "0000123456",
             "filed_at": "2026-09-04 16:40 ET"}), \
         patch.object(hedge_funds, "_ticker_for_cik", return_value="EXMP"):
        ctx = pool_cls.return_value.get_session.return_value
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = False
        filings = hedge_funds.activist_filings(limit=10)

    assert filings == [{"filer": "Example Capital", "subject": "Example Target", "ticker": "EXMP",
                        "form": "SCHEDULE 13D", "date": "2026-09-04",
                        "filed_at": "2026-09-04 16:40 ET", "url": "https://example.test/a"}]


def test_hedge_fund_page_exposes_filing_filter_and_sort_controls(monkeypatch):
    from fastcore.xml import to_xml
    import engine.publicmarkets.hedge_funds as hedge_funds
    from engine.web.ph_hedgefunds import _page

    monkeypatch.setattr(hedge_funds, "activist_filings", lambda **kwargs: [])
    html = to_xml(_page(None))
    assert 'name="ticker"' in html
    assert 'name="form"' in html
    assert 'name="sort"' in html
    assert "Filed (ET)" in html
