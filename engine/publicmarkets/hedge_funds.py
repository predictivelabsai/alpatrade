"""Hedge-fund / institutional 13F tools — reads the shared hedgefolio schema.

This DB has fund-level 13F data (coverpage + summarypage: manager, total portfolio
value, #holdings) and an activist-filings table — but NOT the per-security infotable,
so 'who owns TICKER' isn't available here. We surface: top managers by AUM, fund
search, and activist filings (13D/activist positions by subject ticker).
"""
from __future__ import annotations

from functools import lru_cache
import re

from sqlalchemy import text

from engine.db.pool import DatabasePool


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def top_funds(limit: int = 40) -> list[dict]:
    """Largest institutional managers by latest-quarter 13F portfolio value."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (cp.filingmanager_name)
                   cp.filingmanager_name, sp.table_value_total, sp.table_entry_total,
                   cp.report_calendar_or_quarter
            FROM hedgefolio.coverpage cp
            JOIN hedgefolio.summarypage sp USING (accession_number)
            WHERE sp.table_value_total IS NOT NULL AND sp.table_value_total > 0
            ORDER BY cp.filingmanager_name, cp.report_calendar_or_quarter DESC
        """)).fetchall()
    funds = [{"name": r[0], "value": _f(r[1]), "holdings": int(r[2] or 0), "period": str(r[3] or "")}
             for r in rows]
    funds.sort(key=lambda f: f["value"], reverse=True)
    return funds[:limit]


def fund_search(query: str, limit: int = 20) -> list[dict]:
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (cp.filingmanager_name)
                   cp.filingmanager_name, sp.table_value_total, sp.table_entry_total,
                   cp.report_calendar_or_quarter
            FROM hedgefolio.coverpage cp
            JOIN hedgefolio.summarypage sp USING (accession_number)
            WHERE cp.filingmanager_name ILIKE :q AND sp.table_value_total IS NOT NULL
            ORDER BY cp.filingmanager_name, cp.report_calendar_or_quarter DESC
            LIMIT :lim
        """), {"q": f"%{query}%", "lim": limit}).fetchall()
    return [{"name": r[0], "value": _f(r[1]), "holdings": int(r[2] or 0), "period": str(r[3] or "")}
            for r in rows]


def _ticker_for_cik(cik: str | None) -> str:
    """Resolve a subject CIK through the SEC's cached company ticker list."""
    if not cik:
        return ""
    try:
        from engine.publicmarkets.edgar import _ticker_to_cik_map
        normalized = str(int(cik)).zfill(10)
        return next((ticker for ticker, value in _ticker_to_cik_map().items()
                     if value == normalized), "")
    except Exception:  # noqa: BLE001 - a missing ticker must not hide the filing
        return ""


_SUBJECT_NAME_RE = re.compile(
    r"SUBJECT COMPANY:.*?COMPANY CONFORMED NAME:\s*(?P<name>[^\r\n]+)", re.DOTALL)
_SUBJECT_CIK_RE = re.compile(
    r"SUBJECT COMPANY:.*?CENTRAL INDEX KEY:\s*(?P<cik>\d+)", re.DOTALL)
_FILER_NAME_RE = re.compile(
    r"FILED BY:.*?COMPANY CONFORMED NAME:\s*(?P<name>[^\r\n]+)", re.DOTALL)
_ACCEPTED_RE = re.compile(r"ACCEPTANCE-DATETIME(?:>|:)\s*(?P<value>\d{14})")


@lru_cache(maxsize=512)
def _filing_metadata(url: str) -> dict[str, str]:
    """Read only an EDGAR document header for missing subject/time metadata."""
    if not url:
        return {}
    try:
        from engine.publicmarkets.edgar import _get
        response = _get(url, headers={"Accept": "text/plain", "Range": "bytes=0-16383"})
        header = response.content.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - surface the database row even if EDGAR is busy
        return {}
    name = _SUBJECT_NAME_RE.search(header)
    cik = _SUBJECT_CIK_RE.search(header)
    filer = _FILER_NAME_RE.search(header)
    accepted = _ACCEPTED_RE.search(header)
    timestamp = accepted.group("value") if accepted else ""
    return {"subject": name.group("name").strip() if name else "",
            "subject_cik": cik.group("cik") if cik else "",
            "filer": filer.group("name").strip() if filer else "",
            "filed_at": (f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} "
                         f"{timestamp[8:10]}:{timestamp[10:12]} ET") if timestamp else ""}


def activist_filings(ticker: str = "", form: str = "", limit: int = 25,
                     sort: str = "latest") -> list[dict]:
    """Recent activist / 13D filings, enriched from their SEC document headers."""
    where = "WHERE is_activist = TRUE"
    # Fetch extra candidates for ticker filtering because legacy rows often have
    # no populated subject_ticker.  The document-header cache makes repeats cheap.
    params: dict = {"lim": max(50, min(limit * 4 if ticker else limit, 100))}
    if form:
        where += " AND form_type = :form"
        params["form"] = form
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT filer_name, subject_name, subject_ticker, subject_cik, form_type, filing_date, filing_url
            FROM hedgefolio.activist_filing {where}
            ORDER BY filing_date DESC LIMIT :lim
        """), params).fetchall()
    filings = []
    for row in rows:
        metadata = _filing_metadata(row[6])
        subject_cik = row[3] or metadata.get("subject_cik", "")
        subject = row[1] or metadata.get("subject", "")
        subject_ticker = row[2] or _ticker_for_cik(subject_cik)
        filings.append({"filer": metadata.get("filer") or row[0], "subject": subject, "ticker": subject_ticker,
                        "form": row[4], "date": str(row[5] or ""),
                        "filed_at": metadata.get("filed_at") or str(row[5] or ""), "url": row[6]})
    if ticker:
        filings = [filing for filing in filings if filing["ticker"] == ticker.upper().strip()]
    if sort == "oldest":
        filings.sort(key=lambda filing: filing["filed_at"])
    elif sort == "target":
        filings.sort(key=lambda filing: (filing["subject"] or "").lower())
    elif sort == "filer":
        filings.sort(key=lambda filing: (filing["filer"] or "").lower())
    else:
        filings.sort(key=lambda filing: filing["filed_at"], reverse=True)
    return filings[:limit]


def _b(v: float) -> str:
    return f"${v/1e12:.2f}T" if v >= 1e12 else (f"${v/1e9:.1f}B" if v >= 1e9 else f"${v/1e6:.0f}M")


def top_funds_summary(limit: int = 15) -> str:
    funds = top_funds(limit)
    if not funds:
        return "# Hedge funds\n\nNo 13F data available."
    md = ["# Top institutional managers (13F AUM)", "",
          "| # | Manager | Portfolio value | Holdings | Period |",
          "|---|---|---|---|---|"]
    for i, f in enumerate(funds, 1):
        md.append(f"| {i} | {f['name'][:38]} | {_b(f['value'])} | {f['holdings']:,} | {f['period'][:10]} |")
    return "\n".join(md)


def activist_summary(ticker: str = "", limit: int = 15) -> str:
    rows = activist_filings(ticker, limit)
    if not rows:
        return f"# Activist filings{f' — {ticker.upper()}' if ticker else ''}\n\nNone found."
    md = [f"# Activist filings{f' — {ticker.upper()}' if ticker else ''}", "",
          "| Date | Filer | Target | Ticker | Form |", "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['date'][:10]} | {(r['filer'] or '')[:30]} | {(r['subject'] or '')[:26]} | "
                  f"{r['ticker'] or ''} | {r['form'] or ''} |")
    return "\n".join(md)
