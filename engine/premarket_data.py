"""Dated premarket research over the shared Finespresso catalog and history.

The original tables remain read-only. New observations belong to AlpaTrade;
one row per company/session overrides the legacy snapshot for that session.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time as clock
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text

from engine.db.pool import get_pool

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
AVAILABLE_AT = time(4, 16)
FINALIZE_AT = time(9, 16, 20)
OBSERVATION_AT = time(9, 0)
DELAY_MINUTES = 16
_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.RLock()


def enabled() -> bool:
    return os.getenv("PREMARKET_V2_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def now_et(value: datetime | None = None) -> datetime:
    value = value or datetime.now(ET)
    return value.replace(tzinfo=ET) if value.tzinfo is None else value.astimezone(ET)


def trading_date(value: str | date | None, now: datetime | None = None) -> date:
    today = now_et(now).date()
    try:
        result = date.fromisoformat(value) if isinstance(value, str) and value else value or today
    except ValueError:
        raise ValueError("Date must use YYYY-MM-DD.") from None
    if not isinstance(result, date) or isinstance(result, datetime):
        raise ValueError("Date must use YYYY-MM-DD.")
    if result > today:
        raise ValueError("Select today or an earlier trading date.")
    if result.year < 1970:
        raise ValueError("Select a date from 1970 onward.")
    return result


def cached(key: tuple, ttl: int, loader: Callable[[], Any]) -> Any:
    # The lock also coalesces concurrent full-market requests in this process.
    with _cache_lock:
        existing = _cache.get(key)
        if existing and clock.monotonic() - existing[0] < ttl:
            return existing[1]
        result = loader()
        if len(_cache) >= 256:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (clock.monotonic(), result)
        return result


def query(sql: str, params: dict | None = None) -> list[dict]:
    with get_pool().get_session() as session:
        return [dict(row) for row in session.execute(text(sql), params or {}).mappings()]


def table_exists(name: str) -> bool:
    return bool(query("SELECT to_regclass(:name) AS relation", {"name": name})[0]["relation"])


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None


def catalog() -> list[dict]:
    return cached(("catalog",), 300, lambda: query("""
        SELECT c.company_id, UPPER(c.primary_ticker) AS ticker, c.name AS company_name,
               c.exchange_id, e.name AS exchange, e.code AS exchange_code,
               s.name AS sector, i.name AS industry
        FROM premarket_screener.companies c
        JOIN premarket_screener.exchanges e ON e.exchange_id=c.exchange_id
        JOIN premarket_screener.regions r ON r.region_id=e.region_id
        JOIN premarket_screener.industries i ON i.industry_id=c.industry_id
        JOIN premarket_screener.sectors s ON s.sector_id=i.sector_id
        WHERE r.abbrev='US' ORDER BY c.primary_ticker, c.company_id
    """))


def company(ticker: str) -> dict:
    ticker = ticker.strip().upper()
    result = next((row for row in catalog() if row["ticker"] == ticker), None)
    if result is None:
        raise LookupError("Stock not found in the US company catalog.")
    return result


def search_companies(search: str = "", limit: int = 50) -> list[dict]:
    needle = search.strip().casefold()[:100]
    rows = [row for row in catalog() if not needle or needle in row["ticker"].casefold()
            or needle in row["company_name"].casefold()]
    rows.sort(key=lambda row: (row["ticker"].casefold() != needle,
                              not row["ticker"].casefold().startswith(needle), row["ticker"]))
    return rows[:min(max(limit, 1), 100)]


@lru_cache(maxsize=8)
def _exchange_calendar(year: int):
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS", start=f"{year - 1}-01-01", end=f"{year + 1}-12-31")


def session_hours(day: date, exchange_id: int | None = None) -> dict | None:
    """Prefer stored exchange hours; extend missing calendar coverage with XNYS."""
    if exchange_id is not None:
        rows = query("""SELECT is_open, open, close, after_hour_close
            FROM premarket_screener.calendars WHERE exchange_id=:exchange AND date=:day""",
                     {"exchange": exchange_id, "day": day})
        if rows:
            row = rows[0]
            if not row["is_open"]:
                return None
            return {key: datetime.combine(day, row[key], tzinfo=ET)
                    for key in ("open", "close", "after_hour_close")}
    cal = _exchange_calendar(day.year)
    if not cal.is_session(day.isoformat()):
        return None
    opened = cal.session_open(day.isoformat()).to_pydatetime().astimezone(ET)
    closed = cal.session_close(day.isoformat()).to_pydatetime().astimezone(ET)
    return {"open": opened, "close": closed, "after_hour_close": closed + timedelta(hours=4)}


def previous_session(day: date, exchange_id: int | None = None) -> date:
    for offset in range(1, 15):
        candidate = day - timedelta(days=offset)
        if session_hours(candidate, exchange_id):
            return candidate
    raise ValueError("The previous trading session is unavailable.")


def available_dates() -> list[str]:
    dates = {iso(row["date"]) for row in query(
        "SELECT DISTINCT date FROM premarket_screener.snapshots ORDER BY date DESC")}
    if table_exists("alpatrade.premarket_observations"):
        dates.update(iso(row["date"]) for row in query("""
            SELECT DISTINCT trading_date AS date FROM alpatrade.premarket_observations
            WHERE finalized ORDER BY trading_date DESC"""))
    return sorted((day for day in dates if day), reverse=True)


def observations(day: date) -> dict[int, dict]:
    """A conflicting legacy prior close becomes unavailable, never guessed."""
    rows = query("""
        WITH closes AS (
            SELECT company_id, CASE WHEN COUNT(DISTINCT price)=1 THEN MIN(price) END AS prev_close
            FROM premarket_screener.previous_closes WHERE date=:day GROUP BY company_id
        ), latest AS (
            SELECT DISTINCT ON (company_id) company_id, snapshot_id,
                   premarket_price_at_nine AS premarket_close, accumulated_volume
            FROM premarket_screener.snapshots WHERE date=:day
            ORDER BY company_id, snapshot_id DESC
        )
        SELECT COALESCE(l.company_id,c.company_id) AS company_id, l.snapshot_id,
               l.premarket_close,l.accumulated_volume,c.prev_close
        FROM latest l FULL OUTER JOIN closes c USING (company_id)
    """, {"day": day})
    result = {row["company_id"]: {**row, "data_source": "finespresso",
              "snapshot_id": f"legacy:{row['snapshot_id']}" if row["snapshot_id"] is not None else None,
              "finalized": row["snapshot_id"] is not None,
              "as_of": datetime.combine(day, OBSERVATION_AT, tzinfo=ET) if row["snapshot_id"] is not None else None,
              "quote_timestamp": None} for row in rows}
    if table_exists("alpatrade.premarket_observations"):
        for row in query("""SELECT *, observation_id::text AS snapshot_id
            FROM alpatrade.premarket_observations WHERE trading_date=:day""", {"day": day}):
            # A new previous-close-only record must not obscure a saved legacy quote.
            if row["finalized"] or not result.get(row["company_id"], {}).get("finalized"):
                result[row["company_id"]] = row
    return result


def normalize(meta: dict, observation: dict | None, day: date) -> dict:
    observation = observation or {}
    prior = finite(observation.get("prev_close"))
    price = finite(observation.get("premarket_close"))
    valid = prior is not None and prior > 0 and price is not None and price > 0
    move = finite((price - prior) / prior * 100) if valid else None
    valid = valid and move is not None
    return {**meta, "prev_close": prior, "premarket_close": price,
            "premarket_open": finite(observation.get("premarket_open")),
            "premarket_high": finite(observation.get("premarket_high")),
            "premarket_low": finite(observation.get("premarket_low")),
            "movement_pct": move if valid else None,
            "movement_abs": round(price - prior, 4) if valid else None,
            "accumulated_volume": finite(observation.get("accumulated_volume")),
            "scan_date": day.isoformat(), "as_of": iso(observation.get("as_of")),
            "quote_timestamp": iso(observation.get("quote_timestamp")),
            "data_source": observation.get("data_source", "unavailable"),
            "snapshot_id": observation.get("snapshot_id"), "available": valid,
            "history": [], "ai_reasoning": "", "ai_sources": [], "catalysts": []}


def rank_report(rows: list[dict], day: date, limit: int = 10) -> dict:
    """Count the complete unique universe, independently of the display limit."""
    unique = {row["ticker"]: row for row in rows}
    rows = list(unique.values())
    good = [row for row in rows if row["available"]]
    sectors = {}
    limit = min(max(limit, 1), 25)
    for sector in sorted({row["sector"] for row in rows}):
        selected = [row for row in rows if row["sector"] == sector]
        valid = [row for row in selected if row["available"]]
        up = sorted((row for row in valid if row["movement_pct"] > 0),
                    key=lambda row: (-row["movement_pct"], row["ticker"]))
        down = sorted((row for row in valid if row["movement_pct"] < 0),
                      key=lambda row: (row["movement_pct"], row["ticker"]))
        sectors[sector] = {"up": up[:limit], "down": down[:limit],
                           "total_scanned": len(valid), "total_attempted": len(selected),
                           "total_gainers": len(up), "total_losers": len(down),
                           "total_unchanged": sum(row["movement_pct"] == 0 for row in valid),
                           "total_unavailable": len(selected) - len(valid)}
    return {"schema_version": 2, "trading_date": day.isoformat(), "scan_type": "snapshot",
            "scan_timestamp": datetime.combine(day, OBSERVATION_AT, tzinfo=ET).isoformat(),
            "status": "complete" if len(good) == len(rows) and rows else "partial" if good else "no_data",
            "sectors": sectors, "rows": rows,
            "summary": {"total_sectors": len(sectors), "total_stocks_attempted": len(rows),
                        "total_stocks_scanned": len(good), "total_stocks_failed": len(rows) - len(good),
                        "total_up_movements": sum(row["movement_pct"] > 0 for row in good),
                        "total_down_movements": sum(row["movement_pct"] < 0 for row in good),
                        "total_unchanged": sum(row["movement_pct"] == 0 for row in good)}}


def dashboard(selected_date: str | date | None = None, sector: str = "", limit: int = 10,
              *, now: datetime | None = None, include_earnings: bool = True) -> dict:
    current = now_et(now)
    explicit = bool(selected_date)
    day = trading_date(selected_date, current)
    dates = available_dates()
    is_open = bool(session_hours(day))
    live = day == current.date() and is_open and AVAILABLE_AT <= current.time() < FINALIZE_AT
    notice = []
    if not explicit and not live and (not is_open or current.time() < AVAILABLE_AT):
        if dates:
            day = date.fromisoformat(dates[0])
        notice.append("Showing the latest stored session. Select a date to explore history.")
    metas = catalog()
    if sector and sector not in {row["sector"] for row in metas}:
        raise ValueError("Select a sector from the company catalog.")
    obs = observations(day)
    if live:
        try:
            from engine.premarket_providers import live_observations
            obs = live_observations(metas, current)
        except Exception as exc:
            log.warning("Premarket live feed unavailable (%s)", type(exc).__name__)
            notice.append("The delayed market feed is unavailable. Showing stored data for this date.")
            live = False
    if explicit and not is_open:
        notice.append("The market is closed on the selected date.")
    if day == current.date() and current.time() < AVAILABLE_AT:
        notice.append("Today's delayed premarket data is available from 04:16 ET.")
    rows = [normalize(meta, obs.get(meta["company_id"]), day) for meta in metas]
    if sector:
        rows = [row for row in rows if row["sector"] == sector]
    report = rank_report(rows, day, limit)
    report.update({"mode": "delayed" if live else "snapshot", "available_dates": dates,
                   "sector_names": sorted({row["sector"] for row in metas}), "sector": sector,
                   "delay_minutes": DELAY_MINUTES, "fetched_at": current.isoformat(),
                   "stale": day < current.date(), "notices": notice, "earnings": []})
    if live:
        report["scan_timestamp"] = max((row["as_of"] for row in rows if row.get("as_of")),
                                       default=None)
    if not report["summary"]["total_stocks_scanned"]:
        notice.append("No usable premarket snapshot is available for this date. Choose a stored date in History.")
    try:
        from engine.premarket_analysis import saved_for_date, preview
        analyses = saved_for_date(day)
        for row in rows:
            saved = analyses.get(row["company_id"], [])
            item = next((a for a in saved if a["provider"] == "grok"),
                        next((a for a in saved if a["provider"] == "gemini"), None))
            if item:
                row["ai_reasoning"] = item["text"]
                row["ai_sources"] = item.get("sources", [])
                row["analysis_preview"] = preview(item["text"])
                row["analysis_provider"] = item["provider"]
    except Exception as exc:
        log.warning("Premarket saved analysis unavailable (%s)", type(exc).__name__)
        notice.append("Saved commentary is temporarily unavailable.")
    if include_earnings:
        try:
            from engine.premarket_providers import earnings
            report["earnings"] = earnings(day, previous_session(day), metas)
        except Exception as exc:
            log.info("Premarket earnings unavailable (%s)", type(exc).__name__)
            notice.append("Earnings are unavailable. Market prices and saved commentary remain available.")
    return report


def stock_detail(ticker: str, selected_date: str | date | None = None, *, now: datetime | None = None) -> dict:
    current = now_et(now)
    day = trading_date(selected_date, current)
    meta = company(ticker)
    obs = observations(day)
    notices = []
    if session_hours(day, meta["exchange_id"]) and day == current.date() and AVAILABLE_AT <= current.time() < FINALIZE_AT:
        try:
            from engine.premarket_providers import live_observations
            obs = live_observations(catalog(), current)
        except Exception:
            notices.append("The delayed market feed is unavailable.")
    row = normalize(meta, obs.get(meta["company_id"]), day)
    from engine.premarket_analysis import saved_for_date
    try:
        analyses = saved_for_date(day, meta["company_id"]).get(meta["company_id"], [])
    except Exception:
        analyses = []
        notices.append("Saved commentary is temporarily unavailable.")
    history = []
    try:
        if not session_hours(day, meta["exchange_id"]):
            raise ValueError("The selected date is not a trading session.")
        from engine.premarket_providers import chart
        previous = previous_session(day, meta["exchange_id"])
        history = chart(meta["ticker"], day, session_hours(previous, meta["exchange_id"]), current)
        if not history:
            notices.append("Minute bars are unavailable for this session.")
    except Exception:
        notices.append("The chart is unavailable. Prices and saved commentary are shown below.")
    return {"stock": row, "trading_date": day.isoformat(), "history": history,
            "analyses": analyses, "notices": notices, "delay_minutes": DELAY_MINUTES,
            "can_analyze": bool(row["available"] and session_hours(day, meta["exchange_id"]) and
                                (day < current.date() or current.time() >= FINALIZE_AT)),
            "available_dates": available_dates()}


def observation_identity(row: dict) -> str:
    fields = {key: iso(row.get(key)) for key in (
        "company_id", "scan_date", "snapshot_id", "prev_close", "premarket_close", "as_of")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def report_by_run(run_id: str) -> dict:
    import uuid
    try:
        uuid.UUID(run_id)
    except (TypeError, ValueError, AttributeError):
        raise LookupError("Premarket scan not found.") from None
    rows = query("SELECT report FROM alpatrade.premarket_scan_runs WHERE run_id=:run", {"run": run_id})
    if not rows:
        raise LookupError("Premarket scan not found.")
    report = rows[0]["report"]
    return json.loads(report) if isinstance(report, str) else report


def persist_observations(day: date, records: list[dict], *, finalized: bool) -> None:
    """Atomic session write; absent/failed provider rows never delete history."""
    if not records:
        return
    values = [{"company_id": row["company_id"], "day": day, "prev_close": finite(row.get("prev_close")),
               "price": finite(row.get("premarket_close")), "volume": finite(row.get("accumulated_volume")),
               "as_of": row.get("as_of"), "quote": row.get("quote_timestamp"), "finalized": finalized}
              for row in records]
    with get_pool().get_session() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"premarket-observations:{day}"})
        session.execute(text("""
                INSERT INTO alpatrade.premarket_observations
                    (company_id,trading_date,prev_close,premarket_close,accumulated_volume,
                     as_of,quote_timestamp,data_source,finalized)
                VALUES (:company_id,:day,:prev_close,:price,:volume,:as_of,:quote,'massive',:finalized)
                ON CONFLICT (company_id,trading_date) DO UPDATE SET
                    prev_close=CASE WHEN premarket_observations.finalized AND premarket_observations.prev_close IS NOT NULL
                        THEN premarket_observations.prev_close ELSE COALESCE(EXCLUDED.prev_close,premarket_observations.prev_close) END,
                    premarket_close=CASE WHEN premarket_observations.finalized THEN premarket_observations.premarket_close
                        ELSE COALESCE(EXCLUDED.premarket_close,premarket_observations.premarket_close) END,
                    accumulated_volume=CASE WHEN premarket_observations.finalized THEN premarket_observations.accumulated_volume
                        ELSE COALESCE(EXCLUDED.accumulated_volume,premarket_observations.accumulated_volume) END,
                    as_of=CASE WHEN premarket_observations.finalized THEN premarket_observations.as_of
                        ELSE COALESCE(EXCLUDED.as_of,premarket_observations.as_of) END,
                    quote_timestamp=CASE WHEN premarket_observations.finalized THEN premarket_observations.quote_timestamp
                        ELSE COALESCE(EXCLUDED.quote_timestamp,premarket_observations.quote_timestamp) END,
                    finalized=premarket_observations.finalized OR EXCLUDED.finalized, updated_at=NOW()
            """), values)


def health_snapshot() -> list[dict]:
    """The operator can distinguish stale prices from an idle or failed worker."""
    dates = available_dates()
    latest = date.fromisoformat(dates[0]) if dates else None
    current = now_et()
    expected = current.date()
    if not session_hours(expected) or current.time() < FINALIZE_AT:
        expected = previous_session(expected)
    last = datetime.combine(latest, OBSERVATION_AT, tzinfo=ET) if latest else None
    total = sum(1 for row in observations(latest).values() if row.get("finalized")) if latest else 0
    pending, failed = 0, 0
    if table_exists("alpatrade.premarket_jobs"):
        counts = query("""SELECT status,kind,COUNT(*) AS count FROM alpatrade.premarket_jobs
            WHERE trading_date=:day GROUP BY status,kind""", {"day": expected})
        pending = sum(row["count"] for row in counts if row["status"] in {"queued", "running"})
        failed = sum(row["count"] for row in counts if row["status"] == "failed")
    else:
        counts = []
    commentary_failures = sum(row["count"] for row in counts if row["status"] == "failed" and row["kind"] == "analysis")
    missing = max(0, len(catalog()) - total)
    state = "critical" if latest is None or latest < expected or failed else "warning" if pending or missing else "healthy"
    return [{"key": "premarket", "label": "Premarket snapshots and commentary", "total": total,
             "last_updated": last, "age_hours": (current - last).total_seconds() / 3600 if last else None,
             "max_age_hours": 24, "status": state,
             "gaps": [{"label": "companies without snapshots", "count": missing},
                      {"label": "failed jobs", "count": failed}, {"label": "commentary failures", "count": commentary_failures},
                      {"label": "unfinished jobs", "count": pending}],
             "error": f"Expected session {expected}. Worker enabled: {os.getenv('PREMARKET_WORKER_ENABLED', 'false')}."}]
