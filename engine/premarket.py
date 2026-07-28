"""Premarket intelligence engine ported from Finespresso.

The public contract intentionally retains the Finespresso report shape:
``summary`` plus sector buckets containing ``up`` and ``down`` movers.  Fetching
is batched to keep an on-demand web scan practical; persisted database reports
and legacy JSON reports remain readable.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
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
    """Run a batched extended-hours scan and return a Finespresso-shaped report."""
    import yfinance as yf
    universe = symbols()
    data = yf.download(
        " ".join(universe), period="5d", interval="5m", prepost=True,
        group_by="ticker", auto_adjust=False, threads=True, progress=False,
    )
    movements = []
    for sector, ticker in universe_entries():
        row = _movement(ticker, _ticker_frame(data, ticker))
        if row is not None:
            row["sector"] = sector
            movements.append(row)
    report = build_report(movements, top_n=top_n)
    save_report(report)
    return report


def _report_dir() -> Path:
    return Path(os.getenv("PREMARKET_REPORTS_DIR", "data/premarket"))


def save_report(report: dict[str, Any]) -> Path:
    directory = _report_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"premarket-screener_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    try:
        _save_database(report)
    except Exception as exc:  # noqa: BLE001
        logger.info("Premarket database persistence unavailable: %s", exc)
    return path


def _save_database(report: dict[str, Any]) -> None:
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    summary = report["summary"]
    with DatabasePool().get_session() as session:
        session.execute(text("""
            INSERT INTO alpatrade.premarket_scan_runs
              (run_id, scan_timestamp, scan_type, status, total_sectors,
               total_stocks_attempted, total_stocks_failed, total_stocks_scanned,
               total_up_movements, total_down_movements, report)
            VALUES (:run_id, :scan_timestamp, :scan_type, :status, :total_sectors,
              :total_stocks_attempted, :total_stocks_failed, :total_stocks_scanned,
              :total_up_movements, :total_down_movements, CAST(:report AS jsonb))
            ON CONFLICT (run_id) DO UPDATE SET report = EXCLUDED.report
        """), report | summary | {"report": json.dumps(report, default=str)})


def latest_report() -> dict[str, Any] | None:
    """Load the newest database report, falling back to compatible JSON."""
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            value = session.execute(text("""
                SELECT report FROM alpatrade.premarket_scan_runs
                ORDER BY scan_timestamp DESC LIMIT 1
            """)).scalar()
            if value:
                return value if isinstance(value, dict) else json.loads(value)
    except Exception as exc:  # noqa: BLE001
        logger.info("Premarket database read unavailable: %s", exc)
    files = sorted(_report_dir().glob("premarket-screener_*.json"),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def flatten(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    rows = []
    for sector, bucket in report.get("sectors", {}).items():
        for direction in ("up", "down"):
            for row in bucket.get(direction, []):
                rows.append({"sector": sector, **row})
    seen = set()
    return [row for row in rows if not (row["ticker"] in seen or seen.add(row["ticker"]))]


def top_movers(report: dict[str, Any] | None = None, limit: int = 10) -> dict[str, list[dict]]:
    rows = flatten(report or latest_report())
    return {
        "gainers": sorted((row for row in rows if row.get("movement_pct", 0) > 0),
                          key=lambda row: row["movement_pct"], reverse=True)[:limit],
        "fallers": sorted((row for row in rows if row.get("movement_pct", 0) < 0),
                          key=lambda row: row["movement_pct"])[:limit],
        "movers": sorted(rows, key=lambda row: abs(row.get("movement_pct", 0)),
                         reverse=True)[:limit],
    }


def summary_markdown(limit: int = 8) -> str:
    report = latest_report()
    if not report:
        return ("# Premarket movers\n\nNo scan is available yet. Open **Premarket** "
                "and run a scan during or after the 04:00–09:30 ET session.")
    top = top_movers(report, limit)
    summary = report.get("summary", {})
    lines = [
        "# Premarket movers",
        "",
        f"Scan: {str(report.get('scan_timestamp', ''))[:19]} ET · "
        f"{summary.get('total_stocks_scanned', 0)} stocks · "
        f"{summary.get('total_up_movements', 0)} up / "
        f"{summary.get('total_down_movements', 0)} down",
        "",
        "| Gainers | Move | Fallers | Move |",
        "|---|---:|---|---:|",
    ]
    for index in range(max(len(top["gainers"]), len(top["fallers"]))):
        up = top["gainers"][index] if index < len(top["gainers"]) else {}
        down = top["fallers"][index] if index < len(top["fallers"]) else {}
        lines.append(
            f"| {up.get('ticker', '')} | {up.get('movement_pct', 0):+.2f}% | "
            f"{down.get('ticker', '')} | {down.get('movement_pct', 0):+.2f}% |"
        )
    return "\n".join(lines)
