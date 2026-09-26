"""13F-HR ingestion (SEC EDGAR), CUSIP -> ticker mapping (OpenFIGI), and the
13F-implied performance job for a curated fund set.

SEC fair access: every request carries a descriptive User-Agent with a contact
(``SEC_USER_AGENT``) and we stay well under the 10 req/s limit (engine.publicmarkets.
edgar._get throttles to 8 req/s; this module adds its own 5 req/s pacing on top).
OpenFIGI's keyless tier allows 25 mapping requests/min with 10 CUSIPs each; set
``OPENFIGI_API_KEY`` for the higher keyed limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)

# Well-known 13F filers used as the starter set for 13F-implied performance.
STARTER_FUNDS: list[tuple[str, str]] = [
    ("0001067983", "Berkshire Hathaway"),
    ("0001350694", "Bridgewater Associates"),
    ("0001037389", "Renaissance Technologies"),
    ("0001336528", "Pershing Square Capital Mgmt"),
    ("0001649339", "Scion Asset Management"),
    ("0001656456", "Appaloosa"),
    ("0001167483", "Tiger Global Management"),
    ("0001040273", "Third Point"),
    ("0001061768", "Baupost Group"),
    ("0001536411", "Duquesne Family Office"),
]

METHODS = ("quarter_end", "follow_filing")
METHOD_LABELS = {"quarter_end": "13F-implied (held from quarter end)",
                 "follow_filing": "Follow-the-filing (bought after filing date)"}

# --------------------------------------------------------------------------- CUSIP

_CUSIP_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*@#"


def normalize_cusip(raw: str | None) -> str | None:
    """Upper-case, strip separators and left-pad to 9 chars (filers often drop
    leading zeros, e.g. Apple ``37833100`` -> ``037833100``). None if unusable."""
    if not raw:
        return None
    c = re.sub(r"[^0-9A-Za-z*@#]", "", str(raw)).upper()
    if not c or len(c) > 9 or len(c) < 6:
        return None
    return c.zfill(9)


def cusip_check_digit_ok(cusip: str) -> bool:
    """Validate the 9th-character CUSIP check digit (modulus 10 double-add-double)."""
    if not cusip or len(cusip) != 9 or not cusip[8].isdigit():
        return False
    total = 0
    for i, ch in enumerate(cusip[:8]):
        if ch not in _CUSIP_CHARS:
            return False
        v = _CUSIP_CHARS.index(ch)
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(cusip[8])


def yahoo_ticker(figi_ticker: str | None) -> str | None:
    """OpenFIGI/Bloomberg share-class tickers use '/' (BRK/B); Yahoo uses '-'."""
    if not figi_ticker:
        return None
    t = figi_ticker.strip().upper().replace("/", "-").replace(" ", "-")
    return t or None


_EQUITY_TYPES_SKIP = {"Option", "Warrant", "Right", "Equity Option", "Index Option"}


def pick_figi_match(data: list[dict] | None) -> dict | None:
    """Choose the listed US equity line from an OpenFIGI mapping result."""
    if not data:
        return None
    for row in data:
        if (row.get("marketSector") == "Equity" and row.get("ticker")
                and row.get("securityType") not in _EQUITY_TYPES_SKIP):
            return row
    return None


def map_cusips_openfigi(cusips: list[str], sleep: float | None = None) -> dict[str, dict]:
    """Resolve CUSIPs via OpenFIGI. Returns cusip -> {ticker,name,security_type,status}."""
    key = os.getenv("OPENFIGI_API_KEY")
    batch = 100 if key else 10
    pause = sleep if sleep is not None else (0.25 if key else 2.5)  # 25 req/min keyless
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    out: dict[str, dict] = {}
    for i in range(0, len(cusips), batch):
        chunk = cusips[i:i + batch]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        for attempt in range(5):
            try:
                r = requests.post("https://api.openfigi.com/v3/mapping", json=body,
                                  headers=headers, timeout=30)
            except requests.RequestException as exc:  # noqa: PERF203
                log.warning("openfigi error %s", exc)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(int(r.headers.get("ratelimit-reset", "10") or 10) + 1)
                continue
            if r.status_code != 200:
                log.warning("openfigi HTTP %s", r.status_code)
                time.sleep(5 * (attempt + 1))
                continue
            for cusip, res in zip(chunk, r.json()):
                m = pick_figi_match(res.get("data"))
                if m:
                    out[cusip] = {"ticker": yahoo_ticker(m.get("ticker")), "name": m.get("name"),
                                  "security_type": m.get("securityType"), "status": "mapped"}
                else:
                    out[cusip] = {"ticker": None, "name": None, "security_type": None,
                                  "status": "unmapped"}
            break
        time.sleep(pause)
    return out

# --------------------------------------------------------------------------- EDGAR


@dataclass
class FilingRef:
    cik: str
    accession: str
    form_type: str
    period_of_report: date
    filing_date: date


def _sec_get(url: str, accept: str = "application/json") -> requests.Response:
    from engine.publicmarkets.edgar import _get
    time.sleep(0.2)  # extra pacing: <= 5 req/s from this job
    return _get(url, headers={"Accept": accept})


def _d(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def list_13f_filings(cik: str, since: date) -> tuple[str, list[FilingRef]]:
    """13F-HR and 13F-HR/A filings with period >= since. Returns (filer name, refs)."""
    cik10 = str(int(cik)).zfill(10)
    d = _sec_get(f"https://data.sec.gov/submissions/CIK{cik10}.json").json()
    blocks = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        if f.get("filingTo", "9999") >= since.isoformat():
            blocks.append(_sec_get(f"https://data.sec.gov/submissions/{f['name']}").json())
    refs: list[FilingRef] = []
    for b in blocks:
        for i, form in enumerate(b["form"]):
            if form not in ("13F-HR", "13F-HR/A") or not b["reportDate"][i]:
                continue
            period = _d(b["reportDate"][i])
            if period < since:
                continue
            refs.append(FilingRef(cik10, b["accessionNumber"][i], form, period,
                                  _d(b["filingDate"][i])))
    return d.get("name", ""), sorted(refs, key=lambda r: (r.period_of_report, r.filing_date))


def _strip_ns(tree: ET.Element) -> ET.Element:
    for el in tree.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return tree


def parse_amendment_type(primary_doc_xml: bytes) -> str | None:
    root = _strip_ns(ET.fromstring(primary_doc_xml))
    el = root.find(".//coverPage/amendmentInfo/amendmentType")
    return el.text.strip().upper() if el is not None and el.text else None


def parse_info_table(xml_bytes: bytes) -> list[dict]:
    """Parse a 13F information table XML into row dicts (namespace-agnostic)."""
    root = _strip_ns(ET.fromstring(xml_bytes))
    rows = []
    for it in root.iter("infoTable"):
        def g(path: str) -> str | None:
            el = it.find(path)
            return el.text.strip() if el is not None and el.text else None
        def num(path: str) -> float | None:
            v = g(path)
            try:
                return float(v.replace(",", "")) if v else None
            except ValueError:
                return None
        rows.append({"issuer": g("nameOfIssuer"), "title_of_class": g("titleOfClass"),
                     "cusip": normalize_cusip(g("cusip")), "value": num("value"),
                     "shares": num("shrsOrPrnAmt/sshPrnamt"),
                     "sh_prn_type": (g("shrsOrPrnAmt/sshPrnamtType") or "SH").upper(),
                     "put_call": (g("putCall") or None) and g("putCall").upper()})
    return [r for r in rows if r["cusip"] and r["value"] is not None]


def infer_value_multiplier(rows: list[dict], filing_date: date) -> int:
    """13F values are in dollars for filings from 2023-01-03 and in $ thousands
    before. Some filers kept reporting thousands afterwards, so check the implied
    share price (value/shares) of share rows: a median below $0.50 means thousands."""
    prices = sorted(r["value"] / r["shares"] for r in rows
                    if r.get("sh_prn_type") == "SH" and not r.get("put_call")
                    and r.get("shares") and r["shares"] > 0 and r.get("value"))
    if prices:
        median = prices[len(prices) // 2]
        return 1000 if median < 0.5 else 1
    return 1000 if filing_date < date(2023, 1, 3) else 1


def fetch_filing(ref: FilingRef) -> tuple[str | None, str | None, list[dict]]:
    """(amendment_type, info table url, rows) for one filing."""
    cik = str(int(ref.cik))
    acc = ref.accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"
    items = _sec_get(f"{base}/index.json").json()["directory"]["item"]
    xmls = [it["name"] for it in items if it["name"].lower().endswith(".xml")]
    amendment_type = None
    if ref.form_type.endswith("/A") and "primary_doc.xml" in xmls:
        try:
            amendment_type = parse_amendment_type(
                _sec_get(f"{base}/primary_doc.xml", accept="application/xml").content)
        except ET.ParseError:
            amendment_type = None
    info = [n for n in xmls if n.lower() != "primary_doc.xml"]
    if not info:
        return amendment_type, None, []
    # Largest non-primary XML is the information table.
    sizes = {it["name"]: int(it.get("size") or 0) for it in items}
    name = max(info, key=lambda n: sizes.get(n, 0))
    url = f"{base}/{name}"
    return amendment_type, url, parse_info_table(
        _sec_get(url, accept="application/xml").content)


def effective_holdings(filings: list[dict], as_of: date | None = None) -> list[dict]:
    """Holdings rows for one fund/period after applying amendments.

    ``filings``: dicts with form_type, amendment_type, filing_date, rows. The latest
    RESTATEMENT (or the original) is the base; later NEW HOLDINGS amendments append.
    ``as_of`` limits to filings known by that date (follow-the-filing)."""
    fs = sorted((f for f in filings if as_of is None or f["filing_date"] <= as_of),
                key=lambda f: f["filing_date"])
    base_idx = None
    for i, f in enumerate(fs):
        if f["form_type"] == "13F-HR" or (f.get("amendment_type") or "") == "RESTATEMENT":
            base_idx = i
    if base_idx is None:
        return []
    rows = list(fs[base_idx]["rows"])
    for f in fs[base_idx + 1:]:
        if (f.get("amendment_type") or "") == "NEW HOLDINGS":
            rows.extend(f["rows"])
    return rows
