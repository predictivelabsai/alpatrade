"""SEC EDGAR API client — full-text search, company filings, XBRL facts.

Borrowed from liquidround (utils/edgar.py); no DB, no API key — free SEC endpoints
with a User-Agent + 8 req/s throttle. Set SEC_USER_AGENT in .env to your contact.
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

USER_AGENT = os.getenv("SEC_USER_AGENT", "AlpaTrade/1.0 (info@predictivelabs.co.uk)")
_RATE_INTERVAL = 0.125  # 8 req/s
_last_request = 0.0


def _throttle():
    global _last_request
    now = time.monotonic()
    wait = _RATE_INTERVAL - (now - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _get(url: str, **kwargs) -> requests.Response:
    _throttle()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    headers.update(kwargs.pop("headers", {}))
    r = requests.get(url, headers=headers, timeout=30, **kwargs)
    r.raise_for_status()
    return r


@lru_cache(maxsize=1)
def _ticker_to_cik_map() -> dict[str, str]:
    r = _get("https://www.sec.gov/files/company_tickers.json")
    data = r.json()
    mapping = {}
    for entry in data.values():
        ticker = (entry.get("ticker") or "").upper()
        cik = str(entry.get("cik_str", "")).zfill(10)
        if ticker:
            mapping[ticker] = cik
    return mapping


def ticker_to_cik(ticker: str) -> Optional[str]:
    return _ticker_to_cik_map().get(ticker.upper().strip())


def search_filings(query: str, forms: str = "", ticker: str = "",
                   start_date: str = "", end_date: str = "", limit: int = 20) -> dict:
    """Full-text search of the EDGAR filing index."""
    params = {"q": query, "from": 0, "size": min(limit, 40)}
    if forms:
        params["forms"] = forms
    if ticker:
        cik = ticker_to_cik(ticker)
        if cik:
            params["ciks"] = cik
    if start_date:
        params["dateRange"] = "custom"; params["startdt"] = start_date
    if end_date:
        params["dateRange"] = "custom"; params["enddt"] = end_date
    try:
        r = _get(f"https://efts.sec.gov/LATEST/search-index?{urlencode(params)}")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "total": 0, "results": []}
    data = r.json()
    hits = data.get("hits", {})
    results = []
    for h in hits.get("hits", []):
        src = h.get("_source", {})
        results.append({
            "form_type": src.get("form_type", ""),
            "entity_name": src.get("entity_name", ""),
            "filing_date": src.get("file_date", ""),
            "accession_number": src.get("file_num", ""),
            "description": (src.get("display_names") or [""])[0],
            "file_url": (f"https://www.sec.gov/Archives/edgar/data/"
                         f"{(src.get('ciks') or [''])[0]}/{src.get('adsh', '').replace('-', '')}/"
                         f"{src.get('file_name', '')}"),
        })
    return {"total": hits.get("total", {}).get("value", 0), "results": results}


def get_company_filings(ticker: str, form_type: str = "", limit: int = 20) -> dict:
    """Filing history for a company by ticker."""
    cik = ticker_to_cik(ticker)
    if not cik:
        return {"error": f"Ticker '{ticker}' not found in SEC database", "filings": []}
    try:
        r = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "filings": []}
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    filings = []
    for i in range(len(forms)):
        if form_type and forms[i] != form_type:
            continue
        acc = accessions[i].replace("-", "")
        filings.append({
            "form_type": forms[i], "filing_date": dates[i], "accession_number": accessions[i],
            "description": descriptions[i] if i < len(descriptions) else "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary_docs[i]}",
        })
        if len(filings) >= limit:
            break
    return {"company_name": data.get("name", ""), "cik": cik, "filings": filings}


def get_financial_facts(ticker: str) -> dict:
    """Structured XBRL financial data for a company (recent 10-K/10-Q values)."""
    cik = ticker_to_cik(ticker)
    if not cik:
        return {"error": f"Ticker '{ticker}' not found"}
    try:
        r = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    data = r.json()
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    key_metrics = {}
    for tag in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "NetIncomeLoss", "Assets", "StockholdersEquity",
                "EarningsPerShareBasic", "OperatingIncomeLoss"):
        if tag in us_gaap:
            units = us_gaap[tag].get("units", {})
            usd = units.get("USD", units.get("USD/shares", []))
            if usd:
                recent = [d for d in usd if d.get("form") in ("10-K", "10-Q")]
                recent.sort(key=lambda x: x.get("end", ""), reverse=True)
                key_metrics[tag] = recent[:8]
    return {"company_name": data.get("entityName", ""), "cik": cik, "metrics": key_metrics}
