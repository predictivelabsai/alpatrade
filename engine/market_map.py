"""Finviz-style market-map data — S&P sector universe + batched period returns.

Powers the treemap ("market map of returns") in both the chat tool
(:func:`agui_app.show_market_map`) and the dedicated ``/map`` page
(:mod:`engine.web.ph_charts`). One batched yfinance download per call keeps it
fast; boxes are **sized by live dollar-volume** (avg volume × last close, a
liquidity proxy that never goes stale) and **coloured by period return**.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 11 GICS sectors → representative S&P 500 large caps (curated, ~90 names).
SECTORS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD",
                   "CSCO", "ACN", "QCOM", "TXN", "INTC", "IBM"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ",
                               "CMCSA", "T"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX",
                               "BKNG", "TJX"],
    "Consumer Staples": ["WMT", "PG", "COST", "KO", "PEP", "PM", "MO", "MDLZ", "CL"],
    "Financials": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP",
                   "SPGI", "BLK", "C"],
    "Health Care": ["LLY", "UNH", "JNJ", "MRK", "ABBV", "TMO", "ABT", "PFE",
                    "DHR", "AMGN", "ISRG"],
    "Industrials": ["GE", "CAT", "RTX", "HON", "UNP", "BA", "UPS", "DE", "LMT", "ADP"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX"],
    "Utilities": ["NEE", "SO", "DUK", "CEG", "AEP", "D"],
    "Materials": ["LIN", "SHW", "APD", "ECL", "FCX", "NEM"],
    "Real Estate": ["PLD", "AMT", "EQIX", "WELL", "SPG", "O"],
}

PERIODS = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "ytd")

# ticker → sector reverse index
_TICKER_SECTOR = {t: s for s, ts in SECTORS.items() for t in ts}


def _pct(first: float, last: float) -> float | None:
    if first is None or last is None or first == 0:
        return None
    return round((last - first) / first * 100.0, 2)


def market_map_data(period: str = "1mo") -> dict:
    """Return treemap-ready market-map data for the S&P sector universe.

    Structure::

        {"period": "1mo",
         "sectors": [{"name": "Technology", "return": 3.1}, ...],
         "stocks":  [{"ticker": "AAPL", "sector": "Technology",
                      "return": 4.2, "size": 1.2e10, "price": 316.4}, ...]}

    ``size`` is average daily dollar-volume (liquidity proxy); ``return`` is the
    percentage change over ``period``. Sector return is the size-weighted mean.
    """
    if period not in PERIODS:
        period = "1mo"
    tickers = [t for ts in SECTORS.values() for t in ts]

    import yfinance as yf

    dl_period = "5d" if period in ("1d", "5d") else period
    try:
        raw = yf.download(tickers, period=dl_period, interval="1d",
                          group_by="ticker", auto_adjust=True, progress=False,
                          threads=True)
    except Exception as e:  # noqa: BLE001
        logger.error("market_map download failed: %s", e)
        return {"period": period, "sectors": [], "stocks": [], "error": str(e)}

    stocks: list[dict] = []
    for t in tickers:
        try:
            sub = raw[t] if t in raw.columns.get_level_values(0) else None
        except Exception:  # noqa: BLE001
            sub = None
        if sub is None or sub.empty:
            continue
        closes = sub["Close"].dropna()
        vols = sub["Volume"].dropna() if "Volume" in sub else None
        if len(closes) < 2:
            continue
        first = float(closes.iloc[-2]) if period == "1d" else float(closes.iloc[0])
        last = float(closes.iloc[-1])
        ret = _pct(first, last)
        if ret is None:
            continue
        # dollar-volume proxy for box size (avg over window)
        if vols is not None and len(vols):
            size = float((closes.tail(len(vols)).mean()) * float(vols.mean()))
        else:
            size = last
        stocks.append({
            "ticker": t.replace("-", "."),  # display BRK.B
            "raw": t,
            "sector": _TICKER_SECTOR.get(t, "Other"),
            "return": ret,
            "size": round(size, 0),
            "price": round(last, 2),
        })

    # size-weighted sector returns
    sectors: list[dict] = []
    for s in SECTORS:
        rows = [x for x in stocks if x["sector"] == s]
        if not rows:
            continue
        tot = sum(x["size"] for x in rows) or 1.0
        wret = sum(x["return"] * x["size"] for x in rows) / tot
        sectors.append({"name": s, "return": round(wret, 2), "count": len(rows)})

    sectors.sort(key=lambda x: x["return"], reverse=True)
    return {"period": period, "sectors": sectors, "stocks": stocks}
