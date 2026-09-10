"""Read-only health signals for shared public-market ingestion tables."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from engine.db.pool import DatabasePool


_SOURCES = (
    {
        "key": "press_releases", "label": "Press releases", "table": "public.news",
        "freshness": "downloaded_at", "max_age_hours": 24,
        "checks": (("ticker", "ticker IS NULL AND yf_ticker IS NULL"),),
    },
    {
        "key": "ipo_market", "label": "IPO market", "table": "liquidround.ipo_data",
        "freshness": "last_updated", "max_age_hours": 48,
        "checks": (("exchange", "exchange IS NULL OR btrim(exchange) = ''"),
                   ("price", "ipo_price IS NULL")),
    },
    {
        "key": "ipo_pipeline", "label": "IPO pipeline", "table": "liquidround.ipo_pipeline",
        "freshness": "last_updated", "max_age_hours": 48,
        "checks": (("exchange", "exchange IS NULL OR btrim(exchange) = ''"),
                   ("expected date", "expected_date IS NULL"),
                   ("proposed price", "proposed_price IS NULL")),
    },
    {
        "key": "spacs", "label": "SPACs", "table": "liquidround.spac_data",
        "freshness": "last_updated", "max_age_hours": 48,
        "checks": (("sponsor", "sponsor IS NULL OR btrim(sponsor) = ''"),
                   ("status", "status IS NULL OR btrim(status) = ''"),
                   ("trust", "trust_size IS NULL"),
                   ("target", "target_name IS NULL OR btrim(target_name) = ''")),
    },
    {
        "key": "activist_filings", "label": "Hedge-fund filings", "table": "hedgefolio.activist_filing",
        "freshness": "updated_at", "max_age_hours": 24,
        "checks": (("target", "subject_name IS NULL OR btrim(subject_name) = ''"),
                   ("ticker", "subject_ticker IS NULL OR btrim(subject_ticker) = ''")),
    },
)


def _age_hours(value: Any) -> float | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value).total_seconds() / 3600)


def _status(age_hours: float | None, max_age_hours: int, missing_rate: float) -> str:
    if age_hours is None or age_hours > max_age_hours * 2:
        return "critical"
    if age_hours > max_age_hours or missing_rate >= 0.30:
        return "warning"
    return "healthy"


def data_health_snapshot() -> list[dict]:
    """Snapshot freshness and required-field completeness for each shared feed.

    The dashboard intentionally reads source tables rather than app caches, so
    it diagnoses ingestion lag and incomplete upstream records independently of
    any UI-level enrichment.
    """
    health = []
    with DatabasePool().get_session() as session:
        for source in _SOURCES:
            checks = source["checks"]
            missing_sql = ", ".join(
                f"COUNT(*) FILTER (WHERE {condition}) AS missing_{index}"
                for index, (_label, condition) in enumerate(checks))
            try:
                row = session.execute(text(f"""
                    SELECT COUNT(*) AS total, MAX({source['freshness']}) AS last_updated,
                           {missing_sql}
                    FROM {source['table']}
                """)).mappings().one()
                total = int(row["total"] or 0)
                gaps = [{"label": label, "count": int(row[f"missing_{index}"] or 0)}
                        for index, (label, _condition) in enumerate(checks)]
                missing_rate = (max((gap["count"] for gap in gaps), default=0) / total
                                if total else 1.0)
                last_updated = row["last_updated"]
                age_hours = _age_hours(last_updated)
                health.append({
                    "key": source["key"], "label": source["label"], "total": total,
                    "last_updated": last_updated, "age_hours": age_hours,
                    "max_age_hours": source["max_age_hours"], "gaps": gaps,
                    "status": _status(age_hours, source["max_age_hours"], missing_rate),
                })
            except Exception as exc:  # noqa: BLE001 - one source must not hide the others
                health.append({"key": source["key"], "label": source["label"], "total": 0,
                               "last_updated": None, "age_hours": None,
                               "max_age_hours": source["max_age_hours"], "gaps": [],
                               "status": "critical", "error": str(exc)})
    from engine.premarket_data import enabled
    if enabled():
        try:
            from engine.premarket_data import health_snapshot
            health.extend(health_snapshot())
        except Exception:
            health.append({"key": "premarket", "label": "Premarket snapshots and commentary", "total": 0,
                           "last_updated": None, "age_hours": None, "max_age_hours": 24,
                           "gaps": [], "status": "critical", "error": "Premarket schema or database unavailable."})
    return health
