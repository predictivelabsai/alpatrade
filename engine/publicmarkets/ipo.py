"""IPO tools — priced-IPO map + pre-IPO/upcoming pipeline.

Reads the shared Postgres (liquidround.ipo_data / ipo_pipeline) populated by
liquidround's scrapers — AlpaTrade consumes it read-only.

Two gaps in the shared dataset are bridged here instead:

* ``ipo_data`` often lacks ``current_price`` / ``price_change_since_ipo`` for
  recent listings — those are enriched from live market quotes (one batched
  Yahoo download, cached) so the map's performance views stay meaningful.
* ``ipo_pipeline`` never demotes ``filed`` rows once they price, so the
  pipeline reclassifies them itself: a ``filed`` ticker that appears in
  ``ipo_data`` is completed with the priced record, and one that only quotes
  live on the market is completed as market-verified.  "Recently completed"
  is built from the priced-IPO table (most recent first) rather than the
  pipeline's own (nearly empty) completed bucket.
"""
from __future__ import annotations

import math
import time
from datetime import date

from sqlalchemy import text

from engine.db.pool import DatabasePool

# Compact exchange → region (most IPOs here are US; extend as needed).
_EXCHANGE_REGION = {
    "NASDAQ": "US", "NYSE": "US", "AMEX": "US", "NYSEAMERICAN": "US", "BATS": "US", "CBOE": "US",
    "LSE": "Europe", "AIM": "Europe", "EURONEXT": "Europe", "XETRA": "Europe", "SIX": "Europe",
    "HKEX": "Asia", "SSE": "Asia", "SZSE": "Asia", "TSE": "Asia", "KRX": "Asia", "NSE": "Asia", "BSE": "Asia",
    "TSX": "Americas", "ASX": "Oceania", "JSE": "Africa",
}

_RECENT_COMPLETED_LIMIT = 12
_QUOTE_TTL = 900  # seconds
_quote_cache: dict = {"at": 0.0, "prices": {}}


def _region(exchange: str) -> str:
    return _EXCHANGE_REGION.get((exchange or "").upper().strip(), "Other")


def _f(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _quote_map(tickers: list[str]) -> dict[str, float]:
    """Last close per ticker via one batched Yahoo download (cached)."""
    wanted = sorted({(t or "").strip().upper() for t in tickers if t})
    if not wanted:
        return {}
    now = time.time()
    if _quote_cache["prices"] and now - _quote_cache["at"] < _QUOTE_TTL:
        return {t: _quote_cache["prices"][t] for t in wanted
                if t in _quote_cache["prices"]}
    try:
        import yfinance as yf
        data = yf.download(" ".join(wanted), period="5d", interval="1d",
                           group_by="ticker", auto_adjust=False, progress=False)
    except Exception:  # noqa: BLE001 — degrade to un-enriched data
        return {}
    prices = _quote_cache.setdefault("prices", {})
    if data is not None and not data.empty:
        for ticker in wanted:
            try:
                frame = data.xs(ticker, axis=1, level=0, drop_level=True)["Close"].dropna()
                if frame.empty:
                    continue
                price = float(frame.iloc[-1])
                if math.isfinite(price) and price > 0:
                    prices[ticker] = price
            except (KeyError, TypeError, IndexError, ValueError):
                continue
    _quote_cache["at"] = now
    return {t: prices[t] for t in wanted if t in prices}


def _return_pct(price: float | None, ipo_price: float | None) -> float | None:
    if not price or not ipo_price:
        return None
    return round((price / ipo_price - 1) * 100, 1)


def ipo_map_data(limit: int = 300) -> dict:
    """Priced IPOs for a treemap (region → sector → ticker), sized by market cap,
    coloured by % change since IPO. Returns {"ipos": [...], "count": n}."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT ticker, company_name, sector, exchange, ipo_date, ipo_price,
                   current_price, market_cap, price_change_since_ipo,
                   country, region
            FROM liquidround.ipo_data
            ORDER BY market_cap DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    ipos = []
    for r in rows:
        mc = _f(r[7])
        ipos.append({
            "ticker": r[0], "company": r[1], "sector": r[2] or "Other",
            "exchange": r[3] or "", "country": r[9] or "United States",
            "region": r[10] or _region(r[3]),
            "ipo_date": str(r[4]) if r[4] else "", "ipo_price": _f(r[5]),
            "price": _f(r[6]), "market_cap": mc,
            "return_pct": _f(r[8]), "size": mc or 1.0,
        })

    # Enrich listings the source never repriced: fetch live quotes once and
    # derive the return since the IPO price ourselves.
    missing = [i["ticker"] for i in ipos
               if i["price"] is None and i["ipo_price"] is not None]
    quotes = _quote_map(missing)
    for item in ipos:
        if item["price"] is None and item["ticker"].upper() in quotes:
            item["price"] = quotes[item["ticker"].upper()]
        if item["return_pct"] is None:
            item["return_pct"] = _return_pct(item["price"], item["ipo_price"])
    return {"ipos": ipos, "count": len(ipos)}


def _priced_index(s) -> dict[str, dict]:
    """All priced IPOs keyed by upper ticker, most recent first."""
    rows = s.execute(text("""
        SELECT upper(ticker), company_name, exchange, ipo_date, ipo_price,
               market_cap, price_change_since_ipo, current_price
        FROM liquidround.ipo_data
        ORDER BY ipo_date DESC
    """)).fetchall()
    index: dict[str, dict] = {}
    for r in rows:
        price = _f(r[7])
        ipo_price = _f(r[4])
        # The source's return is only meaningful when it actually has a
        # current price; otherwise it is recomputed once a quote is fetched.
        index[r[0]] = {
            "company": r[1], "exchange": r[2], "ipo_date": r[3],
            "ipo_price": ipo_price, "market_cap": _f(r[5]),
            "return_pct": _f(r[6]) if price is not None else None,
            "price": price, "needs_quote": price is None,
        }
    return index


def ipo_pipeline_data(limit: int = 100) -> list[dict]:
    """Pre-IPO / upcoming companies (private mega-caps + filed/upcoming), with
    filed rows that have already priced reclassified as completed."""
    with DatabasePool().get_session() as s:
        rows = s.execute(text("""
            SELECT company_name, ticker, kind, sector, country, exchange,
                   last_valuation, last_round, last_round_date, last_amount_raised,
                   funding_to_date, total_rounds, proposed_price, shares_offered,
                   deal_value, expected_date, employees, website, summary, status
            FROM liquidround.ipo_pipeline
            ORDER BY last_valuation DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()
        priced = _priced_index(s)

    filed_tickers = [(r[1] or "").strip().upper() for r in rows if r[2] == "filed"]
    # Recent priced rows the source never repriced need a live quote too.
    recent_needing_quote = [t for t, pr in priced.items()
                            if pr["needs_quote"]][:_RECENT_COMPLETED_LIMIT]
    quotes = _quote_map(filed_tickers + recent_needing_quote)
    for ticker in recent_needing_quote:
        if ticker in quotes:
            priced[ticker]["price"] = quotes[ticker]
            priced[ticker]["return_pct"] = _return_pct(
                quotes[ticker], priced[ticker]["ipo_price"])
    today = date.today()

    def _row(r) -> dict:
        return {"company": r[0], "ticker": r[1], "kind": r[2], "sector": r[3],
                "country": r[4], "exchange": r[5], "valuation": _f(r[6]),
                "last_round": r[7], "last_round_date": str(r[8]) if r[8] else "",
                "amount_raised": _f(r[9]), "funding_to_date": _f(r[10]),
                "total_rounds": r[11], "proposed_price": _f(r[12]),
                "shares_offered": _f(r[13]), "deal_value": _f(r[14]),
                "expected_date": str(r[15]) if r[15] else "", "employees": r[16],
                "website": r[17], "summary": r[18], "status": r[19],
                "market_cap": None, "return_pct": None}

    completed: dict[str, dict] = {}
    upcoming: list[dict] = []
    private: list[dict] = []

    for r in rows:
        row = _row(r)
        ticker = (row["ticker"] or "").strip().upper()
        if row["kind"] == "filed":
            priced_row = priced.get(ticker)
            if priced_row:
                # Priced — the pipeline record is stale; adopt the priced record.
                row.update(kind="ipo_completed", status="priced",
                           exchange=priced_row["exchange"] or row["exchange"],
                           proposed_price=priced_row["ipo_price"] or row["proposed_price"],
                           expected_date=(str(priced_row["ipo_date"])
                                          if priced_row["ipo_date"] else row["expected_date"]),
                           market_cap=priced_row["market_cap"],
                           return_pct=priced_row["return_pct"])
            elif ticker in quotes:
                # Quoting live but not yet in the priced dataset.
                row.update(kind="ipo_completed", status="priced (market-verified)",
                           proposed_price=row["proposed_price"] or quotes[ticker])
            else:
                try:
                    if (row["expected_date"]
                            and date.fromisoformat(row["expected_date"][:10]) < today):
                        row["status"] = "overdue"
                except ValueError:
                    pass
        elif row["kind"] == "ipo_completed" and priced.get(ticker):
            # Enrich source-completed rows with the priced record's fields.
            priced_row = priced[ticker]
            row.update(status="priced",
                       exchange=priced_row["exchange"] or row["exchange"],
                       proposed_price=priced_row["ipo_price"] or row["proposed_price"],
                       expected_date=(str(priced_row["ipo_date"])
                                      if priced_row["ipo_date"] else row["expected_date"]),
                       market_cap=priced_row["market_cap"],
                       return_pct=priced_row["return_pct"])
        if row["kind"] == "ipo_completed":
            completed.setdefault(ticker or row["company"], row)
        elif row["kind"] == "private":
            private.append(row)
        else:
            upcoming.append(row)

    # "Recently completed" comes from the priced-IPO table so it reflects
    # reality instead of the pipeline's nearly-empty completed bucket.
    for ticker, pr in priced.items():
        if len(completed) >= _RECENT_COMPLETED_LIMIT:
            break
        if ticker in completed:
            continue
        completed[ticker] = {
            "company": pr["company"], "ticker": ticker, "kind": "ipo_completed",
            "sector": None, "country": None, "exchange": pr["exchange"],
            "valuation": None, "last_round": None, "last_round_date": "",
            "amount_raised": None, "funding_to_date": None, "total_rounds": None,
            "proposed_price": pr["ipo_price"], "shares_offered": None,
            "deal_value": None, "expected_date": (str(pr["ipo_date"])
                                                  if pr["ipo_date"] else ""),
            "employees": None, "website": None, "summary": None,
            "status": "priced", "market_cap": pr["market_cap"],
            "return_pct": pr["return_pct"],
        }

    def _completed_key(row):
        return row.get("expected_date") or "", (row.get("ticker") or "")

    def _upcoming_key(row):
        has_date = 0 if row.get("expected_date") else 1
        return has_date, row.get("expected_date") or "", -(row.get("deal_value") or 0)

    result = sorted(completed.values(), key=_completed_key, reverse=True)
    result += sorted(upcoming, key=_upcoming_key)
    result += sorted(private, key=lambda r: -(r.get("valuation") or 0))
    return result


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
