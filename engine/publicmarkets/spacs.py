"""SPAC screener — reads the shared liquidround.spac_data table.

Trust size, NAV premium, target, status per SPAC. AlpaTrade consumes it read-only.
"""
from __future__ import annotations

import math
import os
import time

import requests
from sqlalchemy import text

from engine.db.pool import DatabasePool

_QUOTE_TTL = 900
_quote_cache: dict = {"at": 0.0, "prices": {}}
_SPAC_API_TTL = 3_600
_spac_api_cache: dict = {"at": 0.0, "rows": []}
_SPAC_API_URL = "https://api-v1-get-all-companies.spactrax.workers.dev"


def _f(v):
    try:
        result = float(v)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _quote_map(tickers: list[str]) -> dict[str, float]:
    """Batched current prices for active SPAC common/unit symbols."""
    wanted = sorted({(ticker or "").replace("'", "").strip().upper()
                     for ticker in tickers if ticker})
    if not wanted:
        return {}
    now = time.time()
    if _quote_cache["prices"] and now - _quote_cache["at"] < _QUOTE_TTL:
        return {ticker: _quote_cache["prices"][ticker] for ticker in wanted
                if ticker in _quote_cache["prices"]}
    try:
        import yfinance as yf
        data = yf.download(" ".join(wanted), period="5d", interval="1d",
                           group_by="ticker", auto_adjust=False, progress=False)
    except Exception:  # noqa: BLE001
        return {}
    prices = _quote_cache.setdefault("prices", {})
    if data is not None and not data.empty:
        for ticker in wanted:
            try:
                close = data.xs(ticker, axis=1, level=0, drop_level=True)["Close"].dropna()
                price = _f(close.iloc[-1]) if not close.empty else None
                if price and price > 0:
                    prices[ticker] = price
            except (KeyError, TypeError, IndexError, ValueError):
                continue
    _quote_cache["at"] = now
    return {ticker: prices[ticker] for ticker in wanted if ticker in prices}


def _provider_rows() -> dict[str, dict]:
    """Optional licensed SPAC API enrichment for sponsor/target data.

    The app remains useful without this key by relying on its shared dataset
    and public-market prices. Provider-only fields are intentionally not
    guessed from company names or filings.
    """
    key = os.getenv("SPAC_API_KEY")
    if not key:
        return {}
    now = time.time()
    if _spac_api_cache["rows"] and now - _spac_api_cache["at"] < _SPAC_API_TTL:
        return _spac_api_cache["rows"]
    try:
        response = requests.get(_SPAC_API_URL, headers={"X-Spactrax": key}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        indexed = {}
        for row in rows:
            symbols = (row.get("symbols") or row.get("symbol_shares") or "")
            if isinstance(symbols, str):
                symbols = [symbols]
            for symbol in symbols:
                ticker = str(symbol or "").replace("'", "").strip().upper()
                if ticker:
                    indexed[ticker] = row
        _spac_api_cache.update({"at": now, "rows": indexed})
        return indexed
    except (requests.RequestException, TypeError, ValueError):
        return _spac_api_cache["rows"]


def spac_list(status: str = "", limit: int = 100) -> list[dict]:
    """SPACs with snapshot fields refreshed from priced-IPO and quote data."""
    where, params = ["1=1"], {"lim": limit}
    if status:
        where.append("status ILIKE :st")
        params["st"] = f"%{status}%"
    with DatabasePool().get_session() as s:
        rows = s.execute(text(f"""
            SELECT s.ticker, s.company_name, s.sponsor, s.status, s.trust_size,
                   s.trust_per_share, s.current_price, s.nav_premium_pct,
                   s.target_name, s.target_sector, s.warrant_ticker, s.ipo_size,
                   s.exchange, s.ipo_date, i.exchange, i.ipo_date, i.ipo_price,
                   i.current_price
            FROM liquidround.spac_data s
            LEFT JOIN liquidround.ipo_data i
              ON upper(replace(s.ticker, '''', '')) = upper(replace(i.ticker, '''', ''))
            WHERE {' AND '.join(where)}
            ORDER BY coalesce(s.trust_size, s.ipo_size) DESC NULLS LAST, s.ipo_date DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    quotes = _quote_map([r[0] for r in rows if r[6] is None and r[17] is None])
    provider = _provider_rows()
    result = []
    for r in rows:
        ticker = (r[0] or "").replace("'", "").upper()
        enriched = provider.get(ticker, {})
        trust = _f(r[4]) or _f(r[11])
        nav = (_f(r[5]) or _f(enriched.get("trustSharePrice"))
               or _f(enriched.get("estimatedCashInTrustPerShare")) or _f(r[16]))
        price = _f(r[6]) or _f(r[17]) or quotes.get(ticker)
        premium = _f(r[7])
        if premium is None and price and nav:
            premium = round((price / nav - 1) * 100, 2)
        status_value = enriched.get("stage") or r[3] or "unknown"
        target = enriched.get("target") or enriched.get("targetName") or r[8]
        result.append({
            "ticker": r[0], "company": r[1],
            "sponsor": enriched.get("sponsors") or r[2], "status": status_value,
            "trust_size": trust, "trust_per_share": nav, "price": price,
            "nav_premium_pct": premium, "target": target,
            "target_sector": enriched.get("mergerSectorTag") or r[9],
            "warrant": r[10], "exchange": enriched.get("exchange") or r[12] or r[14],
            "ipo_date": str(r[13] or r[15] or ""),
            "source": "spac-api" if enriched else "market-enriched",
        })
    return result


def spac_summary(limit: int = 15) -> str:
    rows = spac_list(limit=limit)
    if not rows:
        return "# SPACs\n\nNo SPAC data available."

    def _b(v):
        return f"${v/1e6:.0f}M" if v else "—"
    md = ["# SPACs — trust, status, targets", "",
          "| Ticker | Sponsor | Status | Trust | NAV prem. | Target |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        prem = f"{r['nav_premium_pct']:+.1f}%" if r["nav_premium_pct"] is not None else "—"
        md.append(f"| {r['ticker'] or ''} | {(r['sponsor'] or '')[:20]} | {r['status'] or ''} | "
                  f"{_b(r['trust_size'])} | {prem} | {(r['target'] or '—')[:24]} |")
    return "\n".join(md)
