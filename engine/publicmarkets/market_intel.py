"""Sector-performance intelligence — annual returns of the 11 SPDR sector ETFs.

Borrowed from liquidround (utils/market_intelligence.py); yfinance only, no DB.
Returns JSON-friendly data (heatmap matrix) so the page renders Plotly client-side,
plus a text insight summary for the chat tool.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

SECTOR_ETFS = {
    "Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Energy": "XLE",
    "Utilities": "XLU", "Materials": "XLB", "Industrials": "XLI",
    "Real Estate": "XLRE", "Communication": "XLC",
}


def sector_returns(years: int = 5) -> dict:
    """Annual % return per sector over the last `years`.

    Returns {"sectors":[...], "years":[...], "matrix":[[ret|None,...],...]} where
    matrix[i][j] is sector i's return in year j (None if missing).
    """
    import yfinance as yf
    end = datetime.now()
    start = end - timedelta(days=years * 365 + 10)
    per_sector: dict[str, dict[int, float]] = {}
    years_seen: set[int] = set()
    for sector, etf in SECTOR_ETFS.items():
        try:
            hist = yf.Ticker(etf).history(start=start, end=end)
            if hist.empty:
                continue
            hist = hist.copy()
            hist["Year"] = hist.index.year
            for yr, grp in hist.groupby("Year"):
                first, last = float(grp["Close"].iloc[0]), float(grp["Close"].iloc[-1])
                if first:
                    per_sector.setdefault(sector, {})[int(yr)] = round((last / first - 1) * 100, 1)
                    years_seen.add(int(yr))
        except Exception as e:  # noqa: BLE001
            log.warning("sector %s (%s) failed: %s", sector, etf, e)
    yr_list = sorted(years_seen)
    sectors = [s for s in SECTOR_ETFS if s in per_sector]
    matrix = [[per_sector.get(s, {}).get(y) for y in yr_list] for s in sectors]
    return {"sectors": sectors, "years": yr_list, "matrix": matrix}


def sector_insights(years: int = 5) -> str:
    """Markdown summary: best/worst sector this year and by average return."""
    data = sector_returns(years)
    sectors, yrs, matrix = data["sectors"], data["years"], data["matrix"]
    if not sectors or not yrs:
        return "# Sector performance\n\nNo sector data available right now."
    latest = yrs[-1]
    this_year = [(s, matrix[i][-1]) for i, s in enumerate(sectors) if matrix[i][-1] is not None]
    avg = [(s, round(sum(v for v in matrix[i] if v is not None) /
                     max(1, len([v for v in matrix[i] if v is not None])), 1))
           for i, s in enumerate(sectors)]
    md = [f"# Sector performance ({yrs[0]}–{latest})", ""]
    if this_year:
        this_year.sort(key=lambda x: x[1], reverse=True)
        md += [f"**{latest} so far** — best: **{this_year[0][0]} {this_year[0][1]:+.1f}%**, "
               f"worst: **{this_year[-1][0]} {this_year[-1][1]:+.1f}%**.", ""]
    avg.sort(key=lambda x: x[1], reverse=True)
    md += [f"**Avg annual return ({len(yrs)}y)** — leader **{avg[0][0]} {avg[0][1]:+.1f}%**, "
           f"laggard **{avg[-1][0]} {avg[-1][1]:+.1f}%**.", "",
           "| Sector | " + " | ".join(str(y) for y in yrs) + " |",
           "|---|" + "|".join(["---"] * len(yrs)) + "|"]
    for i, s in enumerate(sectors):
        md.append(f"| {s} | " + " | ".join(
            f"{matrix[i][j]:+.1f}%" if matrix[i][j] is not None else "—" for j in range(len(yrs))) + " |")
    return "\n".join(md)
