"""Read-only access to the scheduler-owned premarket screener dataset.

Finespresso remains the only writer.  This module deliberately uses
schema-qualified SQL and never calls a market-data provider or creates analysis.
It is the shared data boundary for the FastHTML dashboard, chat tools, and typed
Premarket Agent API.
"""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text

from engine.db.pool import get_pool

EASTERN = ZoneInfo("America/New_York")
CHART_CHOICES = {"auto", "breadth", "movers", "none"}
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")
_PRESCRIPTIVE_RE = re.compile(
    r"\b(?:buy|sell|entry|entries|stop(?:-loss)?|target|orders?|go long|go short)\b",
    re.IGNORECASE,
)


class PremarketError(ValueError):
    """Base error for user-correctable premarket requests."""


class PremarketValidationError(PremarketError):
    """Raised when a date, filter, or chart option is invalid."""


class SchedulerManagedError(PremarketError):
    """Raised when a caller requests an AlpaTrade-owned refresh."""

    code = "scheduler_managed"

    def __init__(self) -> None:
        super().__init__(
            "Premarket snapshots are refreshed only by the Finespresso scheduler."
        )


RowsFn = Callable[[str, dict[str, Any] | None], list[dict[str, Any]]]


def _db_rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_pool().get_session() as session:
        result = session.execute(text(sql), params or {}).mappings()
        return [dict(row) for row in result]


def _date_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value)
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except (TypeError, ValueError) as exc:
            raise PremarketValidationError("date must use YYYY-MM-DD") from exc


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_analysis_excerpt(value: str) -> str:
    clean = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
    if not clean:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    safe = [sentence for sentence in sentences if not _PRESCRIPTIVE_RE.search(sentence)]
    if not safe:
        return "Stored scheduler analysis was withheld because it contained prescriptive language."
    excerpt = " ".join(safe)
    return excerpt if len(excerpt) <= 420 else excerpt[:417].rstrip() + "…"


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _as_of(trading_date: date | None) -> str | None:
    if trading_date is None:
        return None
    return datetime.combine(trading_date, time(9), tzinfo=EASTERN).isoformat()


def _normalise_row(raw: dict[str, Any], as_of: str | None) -> dict[str, Any] | None:
    previous = _finite_number(raw.get("prev_close"))
    current = _finite_number(raw.get("premarket_close", raw.get("latest_close")))
    if previous is None or current is None or previous <= 0 or current <= 0:
        return None
    movement_abs = current - previous
    movement_pct = movement_abs / previous * 100
    volume = _finite_number(raw.get("volume", raw.get("accumulated_volume")))
    premarket_open = _finite_number(raw.get("premarket_open"))
    premarket_high = _finite_number(raw.get("premarket_high"))
    premarket_low = _finite_number(raw.get("premarket_low"))
    analysis = str(raw.get("ai_reasoning") or raw.get("analysis") or "").strip()
    return {
        "ticker": str(raw.get("ticker") or "").upper(),
        "company_name": str(raw.get("company_name") or ""),
        "sector": str(raw.get("sector") or "Unknown"),
        "industry": str(raw.get("industry") or ""),
        "prev_close": round(previous, 4),
        "premarket_close": round(current, 4),
        "premarket_open": round(premarket_open, 4) if premarket_open is not None else None,
        "premarket_high": round(premarket_high, 4) if premarket_high is not None else None,
        "premarket_low": round(premarket_low, 4) if premarket_low is not None else None,
        "movement_abs": round(movement_abs, 4),
        "movement_pct": round(movement_pct, 4),
        "volume": int(volume) if volume is not None and volume >= 0 else None,
        "ai_reasoning": analysis,
        "analysis_excerpt": _safe_analysis_excerpt(analysis) if analysis else "",
        "analysis_provider": "grok" if analysis else None,
        "ai_sources": raw.get("ai_sources") or [],
        "history": raw.get("history") or [],
        "timestamp": _as_iso(raw.get("timestamp")) or as_of,
        "data_source": str(raw.get("data_source") or "premarket_screener.snapshots"),
    }


def _empty_top() -> dict[str, list[dict[str, Any]]]:
    return {"gainers": [], "fallers": [], "movers": []}


def _assemble_snapshot(
    rows: list[dict[str, Any]],
    *,
    effective_date: date | None,
    as_of: str | None,
    freshness: dict[str, Any],
    top_n: int,
    sector: str | None,
    ticker: str | None,
    available_sectors: list[str],
    source: str = "premarket_screener",
) -> dict[str, Any]:
    normalised = [row for raw in rows if (row := _normalise_row(raw, as_of))]
    normalised.sort(key=lambda row: abs(row["movement_pct"]), reverse=True)

    gainers = sorted(
        (row for row in normalised if row["movement_pct"] > 0),
        key=lambda row: row["movement_pct"], reverse=True,
    )
    fallers = sorted(
        (row for row in normalised if row["movement_pct"] < 0),
        key=lambda row: row["movement_pct"],
    )
    unchanged = [row for row in normalised if row["movement_pct"] == 0]

    sector_groups: dict[str, list[dict[str, Any]]] = {}
    for row in normalised:
        sector_groups.setdefault(row["sector"], []).append(row)

    breadth: list[dict[str, Any]] = []
    sectors: dict[str, dict[str, Any]] = {}
    for name, items in sector_groups.items():
        sector_gainers = sorted(
            (row for row in items if row["movement_pct"] > 0),
            key=lambda row: row["movement_pct"], reverse=True,
        )
        sector_fallers = sorted(
            (row for row in items if row["movement_pct"] < 0),
            key=lambda row: row["movement_pct"],
        )
        sector_unchanged = [row for row in items if row["movement_pct"] == 0]
        total = len(items)
        item = {
            "sector": name,
            "total": total,
            "gainers": len(sector_gainers),
            "fallers": len(sector_fallers),
            "unchanged": len(sector_unchanged),
            "gainers_pct": round(len(sector_gainers) / total * 100, 2) if total else 0,
            "fallers_pct": round(len(sector_fallers) / total * 100, 2) if total else 0,
            "unchanged_pct": round(len(sector_unchanged) / total * 100, 2) if total else 0,
        }
        breadth.append(item)
        sectors[name] = {
            "up": sector_gainers[:top_n],
            "down": sector_fallers[:top_n],
            "unchanged": sector_unchanged[:top_n],
            "total_scanned": total,
            "total_gainers": len(sector_gainers),
            "total_losers": len(sector_fallers),
            "total_unchanged": len(sector_unchanged),
        }
    breadth.sort(key=lambda item: (-item["gainers_pct"], item["sector"]))

    top = {
        "gainers": gainers[:top_n],
        "fallers": fallers[:top_n],
        "movers": normalised[:top_n],
    }
    summary = {
        "total_sectors": len(sector_groups),
        "total_stocks_scanned": len(normalised),
        "total_up_movements": len(gainers),
        "total_down_movements": len(fallers),
        "total_unchanged": len(unchanged),
    }
    return {
        "status": "complete" if normalised else "no_data",
        "source": source,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "as_of": as_of,
        "scan_timestamp": as_of,
        "freshness": freshness,
        "filters": {"sector": sector, "ticker": ticker},
        "available_sectors": available_sectors,
        "summary": summary,
        "sector_breadth": breadth,
        "sectors": sectors,
        "rows": normalised,
        "top": top,
    }


class PremarketReader:
    """Query and aggregate normalized premarket snapshots without writing data."""

    def __init__(self, rows_fn: RowsFn | None = None) -> None:
        self._rows_fn = rows_fn or _db_rows

    def _rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._rows_fn(sql, params)

    def _context(self, selected_date: date | None, now_et: datetime) -> dict[str, Any]:
        rows = self._rows("""/* premarket:context */
            WITH metadata AS (
              SELECT (
                SELECT DISTINCT s.date
                FROM premarket_screener.snapshots AS s
                ORDER BY s.date DESC
                LIMIT 1
              ) AS latest_date
            ), completed_sessions AS (
              SELECT DISTINCT cal.date AS session_date
              FROM premarket_screener.calendars AS cal
              JOIN premarket_screener.exchanges AS ex
                ON ex.exchange_id = cal.exchange_id
              JOIN premarket_screener.regions AS region
                ON region.region_id = ex.region_id
              WHERE region.abbrev = 'US'
                AND cal.is_open IS TRUE
                AND (
                  cal.date < :today
                  OR (
                    cal.date = :today
                    AND COALESCE(NULLIF(cal.close::text, ''), '16:00')::time <= :now_time
                  )
                )
            )
            SELECT
              metadata.latest_date,
              ARRAY(
                SELECT DISTINCT sec.name
                FROM premarket_screener.sectors AS sec
                ORDER BY sec.name
              ) AS available_sectors,
              (SELECT MAX(session_date) FROM completed_sessions) AS latest_completed_session,
              (
                SELECT COUNT(*)
                FROM completed_sessions
                WHERE session_date > COALESCE(:selected_date, metadata.latest_date)
              ) AS stale_sessions
            FROM metadata
        """, {
            "selected_date": selected_date,
            "today": now_et.date(),
            "now_time": now_et.time().replace(tzinfo=None),
        })
        row = rows[0] if rows else {}
        sectors = row.get("available_sectors") or []
        if isinstance(sectors, str):
            sectors = [item for item in sectors.strip("{}").split(",") if item]
        return {
            "latest_available": _date_value(row.get("latest_date")),
            "available_sectors": [str(item) for item in sectors],
            "latest_session": _date_value(row.get("latest_completed_session")),
            "stale_sessions": int(row.get("stale_sessions") or 0),
        }

    def _resolve_sector(self, sector: str | None) -> str | None:
        value = (sector or "").strip()
        if not value:
            return None
        rows = self._rows("""/* premarket:validate_sector */
            SELECT sec.name AS sector
            FROM premarket_screener.sectors AS sec
            WHERE LOWER(sec.name) = LOWER(:sector)
            LIMIT 1
        """, {"sector": value})
        if not rows:
            raise PremarketValidationError(f"Unknown premarket sector: {value}")
        return str(rows[0]["sector"])

    def _resolve_ticker(self, ticker: str | None) -> str | None:
        value = (ticker or "").strip().upper()
        if not value:
            return None
        if not _TICKER_RE.fullmatch(value):
            raise PremarketValidationError("ticker must be 1 to 16 letters, digits, dots, or dashes")
        rows = self._rows("""/* premarket:validate_ticker */
            SELECT c.primary_ticker AS ticker
            FROM premarket_screener.companies AS c
            WHERE UPPER(c.primary_ticker) = :ticker
            LIMIT 1
        """, {"ticker": value})
        if not rows:
            raise PremarketValidationError(f"Unknown premarket ticker: {value}")
        return str(rows[0]["ticker"]).upper()

    def _snapshot_rows(
        self, effective_date: date, sector: str | None, ticker: str | None,
    ) -> list[dict[str, Any]]:
        conditions = ["snap.date = :effective_date"]
        params: dict[str, Any] = {"effective_date": effective_date}
        if sector:
            conditions.append("sec.name = :sector")
            params["sector"] = sector
        if ticker:
            conditions.append("UPPER(company.primary_ticker) = :ticker")
            params["ticker"] = ticker
        where = " AND ".join(conditions)
        return self._rows(f"""/* premarket:snapshot */
            SELECT
              company.primary_ticker AS ticker,
              company.name AS company_name,
              sec.name AS sector,
              industry.name AS industry,
              previous.price AS prev_close,
              snap.premarket_price_at_nine AS premarket_close,
              snap.accumulated_volume AS volume,
              analysis.analysis AS ai_reasoning
            FROM premarket_screener.snapshots AS snap
            JOIN premarket_screener.companies AS company
              ON company.company_id = snap.company_id
            JOIN premarket_screener.previous_closes AS previous
              ON previous.company_id = snap.company_id
             AND previous.date = snap.date
            JOIN premarket_screener.industries AS industry
              ON industry.industry_id = company.industry_id
            JOIN premarket_screener.sectors AS sec
              ON sec.sector_id = industry.sector_id
            LEFT JOIN LATERAL (
              SELECT stored.analysis
              FROM premarket_screener.llm_analysis AS stored
              WHERE stored.company_id = snap.company_id
                AND stored.date = snap.date
                AND stored.model_provider::text = 'grok'
              ORDER BY stored.analysis_id DESC
              LIMIT 1
            ) AS analysis ON TRUE
            WHERE {where}
              AND snap.premarket_price_at_nine > 0
              AND snap.premarket_price_at_nine < 'Infinity'::float8
              AND previous.price > 0
              AND previous.price < 'Infinity'::float8
            ORDER BY company.primary_ticker
        """, params)

    @staticmethod
    def _freshness(
        effective_date: date | None,
        latest_available: date | None,
        latest_session: date | None,
        stale_sessions: int,
        has_data: bool,
    ) -> dict[str, Any]:
        if not has_data:
            state = "no_data"
            message = (
                f"No scheduler snapshot exists for {effective_date.isoformat()}."
                if effective_date else "No scheduler snapshot is available."
            )
        elif stale_sessions > 0:
            state = "stale"
            message = f"Snapshot trails the latest completed US session by {stale_sessions} session(s)."
        else:
            state = "current"
            message = "Snapshot is current with the latest completed US session."
        return {
            "state": state,
            "stale": state == "stale",
            "stale_sessions": stale_sessions,
            "latest_available_date": _as_iso(latest_available),
            "latest_completed_session": _as_iso(latest_session),
            "message": message,
        }

    def read(
        self,
        *,
        selected_date: date | str | None = None,
        sector: str | None = None,
        ticker: str | None = None,
        top_n: int = 10,
        now_et: datetime | None = None,
    ) -> dict[str, Any]:
        if sector and ticker:
            raise PremarketValidationError("sector and ticker are mutually exclusive")
        effective_request = _date_value(selected_date)
        now = now_et or datetime.now(EASTERN)
        if now.tzinfo is None:
            now = now.replace(tzinfo=EASTERN)
        else:
            now = now.astimezone(EASTERN)
        if effective_request and effective_request > now.date():
            raise PremarketValidationError("date cannot be in the future")

        limit = max(1, min(int(top_n), 50))
        resolved_sector = self._resolve_sector(sector)
        resolved_ticker = self._resolve_ticker(ticker)
        context = self._context(effective_request, now)
        latest_available = context["latest_available"]
        effective_date = effective_request or latest_available
        available_sectors = context["available_sectors"]
        latest_session = context["latest_session"]

        raw_rows = (
            self._snapshot_rows(effective_date, resolved_sector, resolved_ticker)
            if effective_date else []
        )
        has_valid_data = any(
            _finite_number(row.get("prev_close")) is not None
            and _finite_number(row.get("premarket_close")) is not None
            and float(row["prev_close"]) > 0
            and float(row["premarket_close"]) > 0
            for row in raw_rows
        )
        stale_sessions = context["stale_sessions"] if has_valid_data else 0
        freshness = self._freshness(
            effective_date, latest_available, latest_session, stale_sessions, has_valid_data,
        )
        return _assemble_snapshot(
            raw_rows,
            effective_date=effective_date,
            as_of=_as_of(effective_date) if has_valid_data else None,
            freshness=freshness,
            top_n=limit,
            sector=resolved_sector,
            ticker=resolved_ticker,
            available_sectors=available_sectors,
        )


def read_premarket(**kwargs: Any) -> dict[str, Any]:
    """Read a normalized premarket snapshot using the shared pool."""
    return PremarketReader().read(**kwargs)


def build_chart_payload(snapshot: dict[str, Any], chart: str = "auto") -> dict[str, Any] | None:
    mode = (chart or "auto").lower()
    if mode not in CHART_CHOICES:
        raise PremarketValidationError(
            f"chart must be one of {', '.join(sorted(CHART_CHOICES))}"
        )
    if mode == "none" or snapshot.get("status") != "complete":
        return None
    top = snapshot.get("top") or _empty_top()
    return {
        "type": "premarket_overview",
        "mode": mode,
        "title": f"Premarket overview · {snapshot.get('effective_date')}",
        "effective_date": snapshot.get("effective_date"),
        "as_of": snapshot.get("as_of"),
        "freshness": snapshot.get("freshness") or {},
        "breadth": snapshot.get("sector_breadth") or [],
        "gainers": [
            {key: row.get(key) for key in ("ticker", "sector", "movement_pct", "volume")}
            for row in top.get("gainers", [])
        ],
        "fallers": [
            {key: row.get(key) for key in ("ticker", "sector", "movement_pct", "volume")}
            for row in top.get("fallers", [])
        ],
    }


def chart_marker(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return f"__CHART_DATA__{json.dumps(payload, separators=(',', ':'), default=str)}__END_CHART__"


def commentary_markdown(snapshot: dict[str, Any]) -> str:
    """Create deterministic, non-prescriptive commentary from stored evidence."""
    effective = snapshot.get("effective_date") or "the requested date"
    summary = snapshot.get("summary") or {}
    freshness = snapshot.get("freshness") or {}
    lines = ["# Premarket screening", "", "## Observed facts", ""]
    if snapshot.get("status") != "complete":
        lines.append(f"No scheduler snapshot is available for **{effective}**.")
    else:
        lines.append(
            f"The scheduler's 09:00 ET snapshot for **{effective}** contains "
            f"**{summary.get('total_stocks_scanned', 0):,}** valid names: "
            f"**{summary.get('total_up_movements', 0):,}** higher, "
            f"**{summary.get('total_down_movements', 0):,}** lower, and "
            f"**{summary.get('total_unchanged', 0):,}** unchanged versus the prior close."
        )
        top = snapshot.get("top") or _empty_top()
        if top.get("gainers"):
            lines.append(
                "Leading moves higher: " + ", ".join(
                    f"**{row['ticker']} {row['movement_pct']:+.2f}%**"
                    for row in top["gainers"][:5]
                ) + "."
            )
        if top.get("fallers"):
            lines.append(
                "Leading moves lower: " + ", ".join(
                    f"**{row['ticker']} {row['movement_pct']:+.2f}%**"
                    for row in top["fallers"][:5]
                ) + "."
            )
    if freshness.get("message"):
        lines.append(f"Freshness: {freshness['message']}")

    lines.extend(["", "## Stored catalyst evidence", ""])
    evidence = [row for row in snapshot.get("rows", []) if row.get("ai_reasoning")]
    if evidence:
        for row in evidence[:3]:
            lines.append(f"- **{row['ticker']}:** {_safe_analysis_excerpt(row['ai_reasoning'])}")
    else:
        lines.append("No matching stored Grok catalyst analysis is available in this snapshot.")

    lines.extend([
        "",
        "## Watch conditions",
        "",
        "Watch whether the gap persists into the 09:30 ET opening auction, whether volume expands, "
        "and whether the move is confirmed by its sector breadth.",
        "",
        "## Liquidity and gap-reversal risks",
        "",
        "Premarket prints can reflect thin liquidity and wide spreads. Opening-auction gaps can "
        "reverse quickly, and stale scheduler data should be treated as historical context only.",
    ])
    return "\n".join(lines)


def report_markdown(snapshot: dict[str, Any], chart: str = "auto") -> str:
    marker = chart_marker(build_chart_payload(snapshot, chart))
    return commentary_markdown(snapshot) + (f"\n\n{marker}" if marker else "")


def legacy_archive_snapshot(
    rows: list[dict[str, Any]],
    run: dict[str, Any] | None,
    *,
    top_n: int = 10,
    sector: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Normalize one immutable ``public.premarket_scan_*`` archive run."""
    if sector and ticker:
        raise PremarketValidationError("sector and ticker are mutually exclusive")
    selected = rows
    resolved_sector = (sector or "").strip() or None
    resolved_ticker = (ticker or "").strip().upper() or None
    available = sorted({str(row.get("sector")) for row in rows if row.get("sector")})
    if resolved_sector:
        resolved_sector = next(
            (name for name in available if name.lower() == resolved_sector.lower()),
            resolved_sector,
        )
        selected = [row for row in selected if str(row.get("sector", "")).lower() == resolved_sector.lower()]
    if resolved_ticker:
        selected = [row for row in selected if str(row.get("ticker", "")).upper() == resolved_ticker]
    timestamp = (run or {}).get("timestamp")
    effective = _date_value(timestamp) if timestamp else None
    freshness = {
        "state": "legacy_archive",
        "stale": True,
        "stale_sessions": None,
        "latest_available_date": effective.isoformat() if effective else None,
        "latest_completed_session": None,
        "message": "This is an immutable legacy scheduler archive, not the latest normalized snapshot.",
    }
    return _assemble_snapshot(
        selected,
        effective_date=effective,
        as_of=_as_iso(timestamp),
        freshness=freshness,
        top_n=max(1, min(int(top_n), 50)),
        sector=resolved_sector,
        ticker=resolved_ticker,
        available_sectors=available,
        source="public.premarket_scan_results",
    )
