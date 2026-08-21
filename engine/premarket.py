"""Legacy premarket helpers retained behind the scheduler-owned reader.

New surfaces use :mod:`engine.research.premarket`. On-demand scans and local
persistence are intentionally blocked so Finespresso remains the sole writer.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")

US_SECTORS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "TSLA", "AMZN", "AMD", "NFLX", "CRM", "ADBE", "INTC", "QCOM", "CSCO", "ORCL"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "LLY", "MRK", "AZN", "AMGN", "GILD", "BIIB", "VRTX", "REGN", "ILMN", "BNTX", "MRNA"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "AXP", "SCHW", "ICE", "CME", "SPGI", "MCO", "NDAQ", "CBOE", "COIN"],
    "Industrials": ["BA", "CAT", "GE", "HON", "MMM", "LMT", "RTX", "NOC", "ETN", "EMR", "ITW", "ROK", "CARR", "OTIS", "IEX"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TJX", "LOW", "CMG", "LULU", "RCL", "CCL", "MAR", "HLT", "WYNN"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST", "MO", "PM", "CL", "KMB", "GIS", "ADM", "SJM", "KHC", "CPB", "HSY"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OKE", "KMI", "WMB", "FANG", "DVN", "MUR", "CTRA"],
    "Materials": ["NEM", "FCX", "SCCO", "AA", "CLF", "STLD", "NUE", "RS", "RIO", "VALE", "TECK", "ALB", "LIN", "APD", "ECL"],
    "Real Estate": ["PLD", "DLR", "EQIX", "SPG", "VTR", "WELL", "VICI", "PSA", "EQR", "AVB", "ARE", "MAA", "UMH", "STAG", "COLD"],
    "Utilities": ["NEE", "DUK", "SO", "D", "EXC", "AEP", "XEL", "PPL", "PEG", "ED", "AWK", "WEC", "CMS", "LNT", "EVRG"],
    "Communication Services": ["GOOGL", "META", "NFLX", "SATS", "CHTR", "CMCSA", "TMUS", "VZ", "T", "FOX", "FOXA", "DIS", "WBD", "FUTU", "BILI"],
}


def symbols() -> list[str]:
    """Return the de-duplicated symbols used for the batched market-data call."""
    return list(dict.fromkeys(ticker for names in US_SECTORS.values() for ticker in names))


def universe_entries() -> list[tuple[str, str]]:
    """Return all 165 Finespresso sector memberships, including cross-listings."""
    return [(sector, ticker) for sector, names in US_SECTORS.items() for ticker in names]


def _sector_for(ticker: str) -> str:
    return next((sector for sector, names in US_SECTORS.items() if ticker in names), "Unknown")


def _ticker_frame(download: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if download.empty:
        return pd.DataFrame()
    if isinstance(download.columns, pd.MultiIndex):
        for level in (0, 1):
            try:
                frame = download.xs(ticker, axis=1, level=level, drop_level=True)
                if not frame.empty:
                    return frame.dropna(how="all")
            except (KeyError, TypeError):
                pass
    return download.dropna(how="all")


def _movement(ticker: str, frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty or "Close" not in frame:
        return None
    idx = pd.DatetimeIndex(frame.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    local = idx.tz_convert(EASTERN)
    work = frame.copy()
    work.index = local
    dates = sorted(set(local.date), reverse=True)
    for trade_date in dates:
        same_day = work[work.index.date == trade_date]
        pre = same_day[(same_day.index.time >= datetime.strptime("04:00", "%H:%M").time())
                       & (same_day.index.time < datetime.strptime("09:30", "%H:%M").time())]
        previous = work[(work.index.date < trade_date)
                        & (work.index.time >= datetime.strptime("09:30", "%H:%M").time())
                        & (work.index.time <= datetime.strptime("16:00", "%H:%M").time())]
        if pre.empty or previous.empty:
            continue
        prev_close = float(previous["Close"].dropna().iloc[-1])
        closes = pre["Close"].dropna()
        if not prev_close or closes.empty:
            continue
        price = float(closes.iloc[-1])
        return {
            "ticker": ticker,
            "company_name": ticker,
            "sector": _sector_for(ticker),
            "industry": "",
            "prev_close": round(prev_close, 2),
            "premarket_open": round(float(pre["Open"].dropna().iloc[0]), 2),
            "premarket_close": round(price, 2),
            "premarket_high": round(float(pre["High"].max()), 2),
            "premarket_low": round(float(pre["Low"].min()), 2),
            "movement_abs": round(price - prev_close, 2),
            "movement_pct": round((price - prev_close) / prev_close * 100, 2),
            "history": [{"timestamp": stamp.isoformat(), "price": round(float(value), 2)}
                        for stamp, value in closes.items()],
            "data_source": "yfinance",
            "scan_date": trade_date.isoformat(),
            "timestamp": datetime.now(EASTERN).isoformat(),
        }
    return None


def _attach_catalysts(movers: Iterable[dict[str, Any]]) -> None:
    """Attach the latest shared Finespresso press-release catalyst in-place."""
    try:
        from engine.publicmarkets.news import search_news
        for mover in movers:
            rows = search_news(ticker=mover["ticker"], limit=3)
            mover["catalysts"] = rows
            mover["ai_reasoning"] = rows[0]["summary"] if rows else ""
            mover["ai_sources"] = [
                {"title": row["title"], "url": row["link"], "source": row["publisher"]}
                for row in rows if row.get("link")
            ]
    except Exception as exc:  # noqa: BLE001
        logger.info("Premarket catalyst enrichment unavailable: %s", exc)
        for mover in movers:
            mover.setdefault("catalysts", [])
            mover.setdefault("ai_reasoning", "")
            mover.setdefault("ai_sources", [])


def build_report(movements: list[dict[str, Any]], top_n: int = 10) -> dict[str, Any]:
    sectors: dict[str, dict[str, Any]] = {}
    for sector in US_SECTORS:
        items = [row for row in movements if row["sector"] == sector]
        gainers = sorted((row for row in items if row["movement_pct"] > 0),
                         key=lambda row: row["movement_pct"], reverse=True)
        losers = sorted((row for row in items if row["movement_pct"] < 0),
                        key=lambda row: row["movement_pct"])
        sectors[sector] = {
            "up": gainers[:top_n], "down": losers[:top_n],
            "total_scanned": len(items), "total_gainers": len(gainers),
            "total_losers": len(losers),
        }
    leaders = sorted(movements, key=lambda row: abs(row["movement_pct"]), reverse=True)[:20]
    _attach_catalysts(leaders)
    return {
        "run_id": str(uuid.uuid4()),
        "scan_timestamp": datetime.now(EASTERN).isoformat(),
        "scan_type": "single",
        "status": "complete",
        "sectors": sectors,
        "summary": {
            "total_sectors": len(US_SECTORS),
            "total_stocks_attempted": len(universe_entries()),
            "total_stocks_failed": len(universe_entries()) - len(movements),
            "total_stocks_scanned": len(movements),
            "total_up_movements": sum(row["movement_pct"] > 0 for row in movements),
            "total_down_movements": sum(row["movement_pct"] < 0 for row in movements),
        },
    }


def scan_premarket(top_n: int = 10) -> dict[str, Any]:
    """Reject legacy on-demand scans; the external scheduler owns refreshes."""
    from engine.research.premarket import SchedulerManagedError

    raise SchedulerManagedError()


def save_report(report: dict[str, Any]) -> None:
    """Reject legacy persistence; retained only as an import compatibility hook."""
    from engine.research.premarket import SchedulerManagedError

    raise SchedulerManagedError()


def latest_report() -> dict[str, Any] | None:
    """Return the latest normalized scheduler snapshot for legacy callers."""
    try:
        from engine.research.premarket import read_premarket

        result = read_premarket()
        return result if result.get("status") == "complete" else None
    except Exception as exc:  # noqa: BLE001
        logger.info("Premarket database read unavailable: %s", exc)
        return None


def flatten(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    if "rows" in report:
        return list(report.get("rows") or [])
    rows = []
    for sector, bucket in report.get("sectors", {}).items():
        for direction in ("up", "down"):
            for row in bucket.get(direction, []):
                rows.append({"sector": sector, **row})
    seen = set()
    return [row for row in rows if not (row["ticker"] in seen or seen.add(row["ticker"]))]


def top_movers(report: dict[str, Any] | None = None, limit: int = 10) -> dict[str, list[dict]]:
    value = report or latest_report()
    if value and value.get("top"):
        return {key: list(value["top"].get(key, []))[:limit]
                for key in ("gainers", "fallers", "movers")}
    rows = flatten(value)
    return {
        "gainers": sorted((row for row in rows if row.get("movement_pct", 0) > 0),
                          key=lambda row: row["movement_pct"], reverse=True)[:limit],
        "fallers": sorted((row for row in rows if row.get("movement_pct", 0) < 0),
                          key=lambda row: row["movement_pct"])[:limit],
        "movers": sorted(rows, key=lambda row: abs(row.get("movement_pct", 0)),
                         reverse=True)[:limit],
    }


def summary_markdown(limit: int = 8) -> str:
    from engine.research.premarket import PremarketReader, report_markdown

    return report_markdown(PremarketReader().read(top_n=limit), chart="none")
