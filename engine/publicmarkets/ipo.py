"""IPO tools — priced-IPO map + pre-IPO/upcoming pipeline.

Reads the shared Postgres (liquidround.ipo_data / ipo_pipeline) populated by
liquidround's scrapers — AlpaTrade consumes it read-only.
"""
from __future__ import annotations

import math

from sqlalchemy import text

from engine.db.pool import DatabasePool

# Compact exchange → region (most IPOs here are US; extend as needed).
_EXCHANGE_REGION = {
    "NASDAQ": "US", "NYSE": "US", "AMEX": "US", "NYSEAMERICAN": "US", "BATS": "US", "CBOE": "US",
    "LSE": "Europe", "AIM": "Europe", "EURONEXT": "Europe", "XETRA": "Europe", "SIX": "Europe",
    "HKEX": "Asia", "SSE": "Asia", "SZSE": "Asia", "TSE": "Asia", "KRX": "Asia", "NSE": "Asia", "BSE": "Asia",
    "TSX": "Americas", "ASX": "Oceania", "JSE": "Africa",
}


def _region(exchange: str) -> str:
    return _EXCHANGE_REGION.get((exchange or "").upper().strip(), "Other")


def _f(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def ipo_map_data(limit: int = 300) -> dict:
    """Priced IPOs for a treemap (region → sector → ticker), sized by market cap,
    coloured by % change since IPO. Returns {"ipos": [...], "count": n}."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT ticker, company_name, sector, exchange, ipo_date, ipo_price,
                   current_price, market_cap, price_change_since_ipo
            FROM liquidround.ipo_data
            ORDER BY market_cap DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()
    ipos = []
    for r in rows:
        mc = _f(r[7])
        ipos.append({
            "ticker": r[0], "company": r[1], "sector": r[2] or "Other",
            "exchange": r[3] or "", "region": _region(r[3]),
            "ipo_date": str(r[4]) if r[4] else "", "ipo_price": _f(r[5]),
            "price": _f(r[6]), "market_cap": mc,
            "return_pct": _f(r[8]), "size": mc or 1.0,
        })
    return {"ipos": ipos, "count": len(ipos)}


def ipo_summary(limit: int = 12) -> str:
    """Markdown: recent priced IPOs and best/worst performers since listing."""
    ipos = ipo_map_data(300)["ipos"]
    if not ipos:
        return "# IPOs\n\nNo IPO data available."
    perf = [i for i in ipos if i["return_pct"] is not None]
    perf.sort(key=lambda i: i["return_pct"], reverse=True)
    md = [f"# Recent IPOs ({len(ipos)} tracked)", ""]
    if perf:
        md += [f"**Best since IPO:** {perf[0]['ticker']} ({perf[0]['company']}) "
               f"{perf[0]['return_pct']:+.1f}% · **Worst:** {perf[-1]['ticker']} "
               f"{perf[-1]['return_pct']:+.1f}%", ""]
    md += ["| Ticker | Company | Sector | Exchange | IPO date | Since IPO |",
           "|---|---|---|---|---|---|"]
    for i in ipos[:limit]:
        ret = f"{i['return_pct']:+.1f}%" if i["return_pct"] is not None else "—"
        md.append(f"| {i['ticker']} | {(i['company'] or '')[:28]} | {i['sector']} | "
                  f"{i['exchange']} | {i['ipo_date'][:10]} | {ret} |")
    return "\n".join(md)


def ipo_pipeline_data(limit: int = 100) -> list[dict]:
    """Pre-IPO / upcoming companies (private mega-caps + filed/upcoming)."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT company_name, ticker, kind, sector, country, exchange,
                   last_valuation, last_round, last_round_date, last_amount_raised
            FROM liquidround.ipo_pipeline
            ORDER BY last_valuation DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()
    return [{"company": r[0], "ticker": r[1], "kind": r[2], "sector": r[3],
             "country": r[4], "exchange": r[5], "valuation": _f(r[6]),
             "last_round": r[7], "last_round_date": str(r[8]) if r[8] else "",
             "amount_raised": _f(r[9])} for r in rows]


def ipo_pipeline_summary(limit: int = 15) -> str:
    rows = ipo_pipeline_data(100)
    if not rows:
        return "# IPO pipeline\n\nNo pipeline data available."
    def _b(v):
        return f"${v/1e9:.1f}B" if v else "—"
    md = ["# IPO pipeline — pre-IPO & upcoming", "",
          "| Company | Kind | Sector | Country | Valuation | Last round |",
          "|---|---|---|---|---|---|"]
    for r in rows[:limit]:
        md.append(f"| {(r['company'] or '')[:30]} | {r['kind'] or ''} | {r['sector'] or ''} | "
                  f"{r['country'] or ''} | {_b(r['valuation'])} | {r['last_round'] or ''} |")
    return "\n".join(md)
