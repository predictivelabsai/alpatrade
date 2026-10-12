"""FCA National Storage Mechanism (public archive) -> ``rns_nsm`` rows.

Public data only: headline, company, type and the link to the public FCA artefact.
A noise filter drops filings with no news value (Form 8.x, holdings, voting rights,
buybacks, NAVs, Final Terms, ...). Companies are linked to FTSE 350 ``.L`` symbols
by name using ``config/uk_ftse350.json``. Ported from finespresso-admin
``tasks/publisher/uk_wires.py`` (PR #5).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

import requests

NSM_SEARCH = "https://api.data.fca.org.uk/search?index=nsm-search"
NSM_ARTEFACTS = "https://data.fca.org.uk/artefacts/"
_CONFIG = Path(__file__).resolve().parent / "config"

NOISE_TYPES = {
    "form 8.3", "form 8.5 (ept/ri)", "form 8.5 (ept/npm)", "form 8 (opening position disclosure)",
    "form 8 (dd)", "holding(s) in company", "total voting rights", "block listing",
    "block listing return", "blocklisting interim review", "transaction in own shares",
    "net asset value(s)", "frn variable rate fix", "final terms", "pricing supplement",
    "final announcement released", "publication of a prospectus",
    "publication of a supplementary prospectus", "base prospectus", "director declaration",
    "statement re suspension", "doc re", "doc re.", "annual financial report (esef)", "ftse",
    "miscellaneous", "notice of agm", "result of agm", "treasury stock", "irish takeover panel",
    "disclosure table (takeover panel use only)", "official list notice (fca use only)",
    "london stock exchange notice", "aquis exchange", "dividend declaration",
    "director/pdmr shareholding",
}
NOISE_HEADLINE = re.compile(
    r"^(form 8|transaction in own shares|total voting rights|holding\(s\) in company|net asset value|"
    r"block ?listing|frn variable rate|final terms|director/pdmr shareholding|price monitoring|"
    r"irish ?form|form 38)", re.I)
KEEP_SOURCES = {"RNS", "PRN", "BWI", "EQS", "GNW", "MFN", "Direct Upload"}


def tidm_to_yahoo(tidm: str | None) -> str | None:
    """LSE TIDM -> Yahoo: VOD -> VOD.L, BT.A -> BT-A.L, BP. -> BP.L."""
    t = (tidm or "").strip().upper()
    if t.endswith(".L"):
        t = t[:-2]
    t = t.rstrip(".").replace(".", "-")
    return f"{t}.L" if t else None


def is_noise(rec: dict) -> bool:
    typ = (rec.get("type") or "").strip().lower()
    if typ in NOISE_TYPES or typ.startswith("form 8"):
        return True
    if NOISE_HEADLINE.search((rec.get("headline") or "").strip()):
        return True
    return rec.get("source") not in KEEP_SOURCES


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and "))
    n = re.sub(r"\b(plc|p l c|group|holdings?|limited|ltd|the)\b", " ", n)
    return " ".join(n.split())


@lru_cache(maxsize=1)
def _ftse_index() -> dict[str, str]:
    try:
        rows = json.loads((_CONFIG / "uk_ftse350.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {_norm(r["name"]): r["yf_symbol"] for r in rows}


def ftse_symbol(company: str) -> str | None:
    return _ftse_index().get(_norm(company)) if company else None


def query(frm: datetime, to: datetime, size: int = 500, start: int = 0) -> dict:
    return {
        "from": start, "size": size, "sort": "publication_date", "sortorder": "desc",
        "criteriaObj": {
            "criteria": [{"name": "latest_flag", "value": "Y"}],
            "dateCriteria": [{"name": "publication_date", "value": {
                "from": frm.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": to.strftime("%Y-%m-%dT%H:%M:%SZ")}}],
        },
    }


def fetch_records(hours: int = 26, *, max_items: int = 3000, post: Callable | None = None,
                  headers: dict | None = None) -> list[dict]:
    def _post(body):
        r = requests.post(NSM_SEARCH, json=body, headers=headers or {}, timeout=30)
        r.raise_for_status()
        return r.json()
    post = post or _post
    to = datetime.now(timezone.utc)
    frm = to - timedelta(hours=hours)
    out, start = [], 0
    while start < max_items:
        hits = ((post(query(frm, to, 500, start)) or {}).get("hits") or {}).get("hits") or []
        out += [h.get("_source") or {} for h in hits]
        if len(hits) < 500:
            break
        start += 500
    return out


def rows(records: Iterable[dict], *, content: Callable[[str], str] | None = None) -> Iterable[dict]:
    """Noise-filtered records -> worker rows (content fetched lazily, per yielded row)."""
    seen = set()
    for r in records:
        if is_noise(r):
            continue
        rel = r.get("html_link") or r.get("download_link") or ""
        if not rel:
            continue
        link = rel if rel.startswith("http") else NSM_ARTEFACTS + rel.lstrip("/")
        if link in seen:
            continue
        seen.add(link)
        company = (r.get("company") or "").strip().rstrip(";").strip()
        sym = ftse_symbol(company) or ""
        headline = r.get("headline") or r.get("type") or "Regulatory announcement"
        summary = f"{company}: {headline} ({r.get('type') or ''}, via {r.get('source')})"
        body = content(link) if (content and r.get("html_link")) else ""
        yield {
            "title": headline, "content": body or summary, "link": link,
            "publisher": "rns_nsm", "publisher_job": "rns_nsm",
            "publisher_topic": r.get("type") or "",
            "published_date": r.get("publication_date") or datetime.now(timezone.utc),
            "company": company, "ticker": sym.rsplit(".", 1)[0] if sym else "", "yf_ticker": sym,
            "event": "", "language": "en", "industry": "country_uk",
        }
