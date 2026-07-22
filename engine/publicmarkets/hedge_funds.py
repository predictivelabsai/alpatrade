"""Hedge-fund / institutional 13F tools — reads the shared hedgefolio schema.

This DB has fund-level 13F data (coverpage + summarypage: manager, total portfolio
value, #holdings) and an activist-filings table — but NOT the per-security infotable,
so 'who owns TICKER' isn't available here. We surface: top managers by AUM, fund
search, and activist filings (13D/activist positions by subject ticker).
"""
from __future__ import annotations

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


def activist_filings(ticker: str = "", limit: int = 25) -> list[dict]:
    """Recent activist / 13D filings, optionally by subject ticker."""
    where = "WHERE is_activist = TRUE"
    params: dict = {"lim": limit}
    if ticker:
        where += " AND subject_ticker = :tk"
        params["tk"] = ticker.upper()
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT filer_name, subject_name, subject_ticker, form_type, filing_date, filing_url
            FROM hedgefolio.activist_filing {where}
            ORDER BY filing_date DESC LIMIT :lim
        """), params).fetchall()
    return [{"filer": r[0], "subject": r[1], "ticker": r[2], "form": r[3],
             "date": str(r[4] or ""), "url": r[5]} for r in rows]


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
