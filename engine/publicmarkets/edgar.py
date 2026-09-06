"""SEC EDGAR API client — full-text search, company filings, XBRL facts.

Borrowed from liquidround (utils/edgar.py); no DB, no API key — free SEC endpoints
with a User-Agent + 8 req/s throttle. Set SEC_USER_AGENT in .env to your contact.
"""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

USER_AGENT = os.getenv("SEC_USER_AGENT", "AlpaTrade/1.0 (info@predictivelabs.co.uk)")
_RATE_INTERVAL = 0.125  # 8 req/s
_last_request = 0.0
_latest_cache: tuple[float, list[dict]] | None = None


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


def _display_entity(value: str) -> str:
    """Remove EDGAR's CIK/role suffix from a full-text display name."""
    return re.sub(r"\s+\((?:CIK\s+)?\d+\)(?:\s+\([^)]*\))?$", "", value or "").strip()


def _sort_filings(rows: list[dict], sort: str) -> list[dict]:
    """Sort a normalized filing list; latest is the safe default."""
    if sort == "oldest":
        return sorted(rows, key=lambda row: row.get("filing_date", ""))
    if sort == "entity":
        return sorted(rows, key=lambda row: row.get("entity_name", "").lower())
    if sort == "form":
        return sorted(rows, key=lambda row: row.get("form_type", ""))
    return sorted(rows, key=lambda row: row.get("filing_date", ""), reverse=True)


def latest_filings(forms: str = "", limit: int = 30) -> dict:
    """Return the SEC's current filing feed, newest filing first.

    Unlike full-text search, the Atom feed is useful without a query.  Cache it
    briefly so opening or sorting the page does not repeatedly hit EDGAR.
    """
    global _latest_cache
    now = time.monotonic()
    if _latest_cache is None or now - _latest_cache[0] > 120:
        try:
            response = _get("https://www.sec.gov/cgi-bin/browse-edgar?"
                            "action=getcurrent&output=atom&count=100",
                            headers={"Accept": "application/atom+xml"})
            root = ET.fromstring(response.content)
            namespace = {"atom": "http://www.w3.org/2005/Atom"}
            rows = []
            for entry in root.findall("atom:entry", namespace):
                title = entry.findtext("atom:title", default="", namespaces=namespace)
                form = entry.find("atom:category", namespace)
                form_type = form.get("term", "") if form is not None else ""
                link = entry.find("atom:link[@rel='alternate']", namespace)
                filing_date = (entry.findtext("atom:updated", default="", namespaces=namespace)
                               [:10])
                entity = re.sub(r"^.+?\s-\s", "", title)
                rows.append({"form_type": form_type, "entity_name": _display_entity(entity),
                             "filing_date": filing_date,
                             "file_url": link.get("href", "") if link is not None else ""})
            _latest_cache = (now, rows)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "total": 0, "results": []}
    rows = _latest_cache[1]
    if forms:
        rows = [row for row in rows if row["form_type"] == forms]
    return {"total": len(rows), "results": _sort_filings(rows, "latest")[:min(limit, 40)]}


def search_filings(query: str, forms: str = "", ticker: str = "",
                   start_date: str = "", end_date: str = "", limit: int = 20,
                   sort: str = "latest") -> dict:
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
            "form_type": src.get("form") or src.get("file_type")
                         or (src.get("root_forms") or [""])[0],
            "entity_name": _display_entity((src.get("display_names") or [""])[0]),
            "filing_date": src.get("file_date", ""),
            "accession_number": src.get("adsh", ""),
            "description": (src.get("display_names") or [""])[0],
            "file_url": (f"https://www.sec.gov/Archives/edgar/data/"
                         f"{int((src.get('ciks') or ['0'])[0])}/"
                         f"{src.get('adsh', '').replace('-', '')}/"
                         f"{src.get('adsh', '')}-index.html"),
        })
    return {"total": hits.get("total", {}).get("value", 0),
            "results": _sort_filings(results, sort)[:min(limit, 40)]}


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
