"""The only AlpaTrade component authorized to mutate the shared news feed."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Any
import json

from sqlalchemy import text

from news_scheduler.validation import REQUIRED_FIELDS, finite_move, invalid_text

_MISSING_SQL = " OR ".join([
    "company IS NULL OR btrim(company)='' OR lower(btrim(company)) IN ('nan','n/a','error in summarization')",
    "language IS NULL OR btrim(language)=''",
    "title_en IS NULL OR btrim(title_en)=''",
    "content_en IS NULL OR btrim(content_en)=''",
    "predicted_side IS NULL OR upper(btrim(predicted_side)) NOT IN ('UP','DOWN','NEUTRAL')",
    "predicted_move IS NULL OR predicted_move::text IN ('NaN','Infinity','-Infinity')",
    "reason IS NULL OR btrim(reason)='' OR lower(btrim(reason)) IN ('nan','n/a','error in summarization')",
    "company_type IS NULL OR company_type NOT IN ('public','private')",
])


class NewsRepository:
    def __init__(self, engine):
        self.engine = engine

    def article_exists(self, publisher: str, link: str) -> bool:
        if not link:
            return False
        with self.engine.connect() as conn:
            return bool(conn.execute(text(
                "SELECT 1 FROM public.news WHERE publisher=:publisher AND link=:link LIMIT 1"
            ), {"publisher": publisher, "link": link}).scalar())

    def record_event(self, job_name: str, shard_index: int, event_name: str,
                     status: str, *, news_id: int | None = None,
                     publisher: str | None = None, details: dict | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO alpatrade.news_worker_events
                    (job_name, shard_index, event_name, status, news_id, publisher, details)
                VALUES (:job, :shard, :event, :status, :news_id, :publisher,
                        CAST(:details AS jsonb))
            """), {"job": job_name, "shard": shard_index, "event": event_name,
                    "status": status, "news_id": news_id, "publisher": publisher,
                    "details": json.dumps(details or {})})

    @staticmethod
    def lock_key(job_name: str, shard_index: int) -> int:
        return int.from_bytes(hashlib.sha256(f"{job_name}:{shard_index}".encode()).digest()[:8], "big", signed=True)

    @contextmanager
    def lock(self, job_name: str, shard_index: int):
        conn = self.engine.connect()
        key = self.lock_key(job_name, shard_index)
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            conn.close()

    def checkpoint(self, job_name: str, shard_index: int, shard_count: int) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO alpatrade.news_worker_jobs(job_name, shard_index, shard_count, status)
                VALUES (:job, :shard, :count, 'stopped')
                ON CONFLICT(job_name, shard_index, shard_count) DO UPDATE SET updated_at=NOW()
                RETURNING *
            """), {"job": job_name, "shard": shard_index, "count": shard_count}).mappings().one()
        return dict(row)

    def update_checkpoint(self, job_name: str, shard_index: int, shard_count: int, **values):
        allowed = {"last_processed_news_id", "last_inserted_news_id", "processed_count", "failed_count",
                   "last_error", "status", "last_successful_cycle", "started_at"}
        values = {k: v for k, v in values.items() if k in allowed}
        if not values:
            return
        setters = ", ".join(f"{key}=:{key}" for key in values)
        with self.engine.begin() as conn:
            conn.execute(text(f"""UPDATE alpatrade.news_worker_jobs SET {setters}, updated_at=NOW()
                WHERE job_name=:job AND shard_index=:shard AND shard_count=:count"""),
                {**values, "job": job_name, "shard": shard_index, "count": shard_count})

    def incomplete(self, after_id: int, limit: int, shard_index: int, shard_count: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(f"""SELECT * FROM public.news WHERE id>:after
                AND mod(id,:count)=:shard
                AND ({_MISSING_SQL}) ORDER BY id LIMIT :limit"""),
                {"after": after_id, "count": shard_count, "shard": shard_index, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def remaining(self, shard_index: int = 0, shard_count: int = 1) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM public.news WHERE mod(id,:count)=:shard AND ({_MISSING_SQL})"),
                                    {"count": shard_count, "shard": shard_index}).scalar() or 0)

    def incomplete_company_type(self, after_id: int, limit: int, shard_index: int,
                                shard_count: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT * FROM public.news WHERE id>:after
                AND mod(id,:count)=:shard
                AND (company_type IS NULL OR company_type NOT IN ('public','private'))
                ORDER BY id LIMIT :limit"""), {
                    "after": after_id, "count": shard_count,
                    "shard": shard_index, "limit": limit,
                }).mappings().all()
        return [dict(row) for row in rows]

    def remaining_company_type(self, shard_index: int = 0,
                               shard_count: int = 1) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text("""SELECT count(*) FROM public.news
                WHERE mod(id,:count)=:shard
                  AND (company_type IS NULL OR company_type NOT IN ('public','private'))"""), {
                    "count": shard_count, "shard": shard_index,
                }).scalar() or 0)

    def update_enriched(self, article_id: int, row: dict[str, Any]) -> None:
        values = {name: row[name] for name in REQUIRED_FIELDS}
        values.update({"id": article_id, "event": row.get("event_standardized") or row.get("event"),
                       "company_type": row.get("company_type")})
        with self.engine.begin() as conn:
            conn.execute(text("""UPDATE public.news SET company=:company, language=:language,
                title_en=:title_en, content_en=:content_en, predicted_side=:predicted_side,
                predicted_move=:predicted_move, reason=:reason, event=:event,
                company_type=:company_type
                WHERE id=:id"""), values)

    def insert_enriched(self, row: dict[str, Any]) -> int | None:
        values = dict(row)
        with self.engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO public.news(title, content, link, publisher, published_date, ticker, yf_ticker,
                    event, company, company_type, language, title_en, content_en, predicted_side, predicted_move, reason)
                SELECT :title,:content,:link,:publisher,:published_date,:ticker,:yf_ticker,:event_standardized,
                    :company,:company_type,:language,:title_en,:content_en,:predicted_side,:predicted_move,:reason
                WHERE NOT EXISTS (SELECT 1 FROM public.news WHERE link=:link AND publisher=:publisher)
                RETURNING id
            """), values).scalar()
        return int(result) if result is not None else None

    @staticmethod
    def _values(row: dict[str, Any]) -> dict[str, Any]:
        values = {name: row.get(name) for name in (
            "title", "content", "link", "publisher", "published_date", "ticker",
            "yf_ticker", "company", "company_type", "language", "title_en", "content_en", "reason",
        )}
        for name, value in list(values.items()):
            if isinstance(value, str) and invalid_text(value):
                values[name] = None
        values["event"] = row.get("event_standardized") or row.get("event")
        side = str(row.get("predicted_side") or "").strip().upper()
        values["predicted_side"] = side if side in ("UP", "DOWN", "NEUTRAL") else None
        values["predicted_move"] = finite_move(row.get("predicted_move"))
        return values

    @staticmethod
    def dedupe_key(publisher: str | None, link: str | None) -> str:
        """Same advisory-lock key as CityTicker's news_worker (``publisher|link``)."""
        return f"{publisher or ''}|{link or ''}"

    def insert_pending(self, row: dict[str, Any]) -> int | None:
        """Persist a unique raw article before optional enrichment can fail.

        public.news has no unique index on (publisher, link). CityTicker's
        news_worker writes the same table with the same NOT EXISTS guard under
        ``pg_advisory_xact_lock(hashtext(publisher|link))``; taking the identical
        lock here serialises the two workers on one article, so they can never
        both insert it.
        """
        values = self._values(row)
        if not values.get("link") or not values.get("publisher"):
            return None
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                         {"k": self.dedupe_key(values["publisher"], values["link"])})
            result = conn.execute(text("""
                INSERT INTO public.news(title, content, link, publisher, published_date,
                    ticker, yf_ticker, event, company, company_type, language, title_en, content_en,
                    predicted_side, predicted_move, reason, status)
                SELECT :title,:content,:link,:publisher,:published_date,:ticker,:yf_ticker,
                    :event,:company,:company_type,:language,:title_en,:content_en,:predicted_side,
                    :predicted_move,:reason,'pending_enrichment'
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.news WHERE link=:link AND publisher=:publisher)
                RETURNING id
            """), values).scalar()
        return int(result) if result is not None else None

    def update_partial(self, article_id: int, row: dict[str, Any], missing: list[str]) -> None:
        """Keep every successful field and mark the row for backfill if needed."""
        values = {**self._values(row), "id": article_id,
                  "status": "retryable" if missing else "enriched"}
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE public.news SET
                    company=COALESCE(:company,company),
                    company_type=COALESCE(:company_type,company_type),
                    language=COALESCE(:language,language),
                    title_en=COALESCE(:title_en,title_en), content_en=COALESCE(:content_en,content_en),
                    ticker=COALESCE(:ticker,ticker), yf_ticker=COALESCE(:yf_ticker,yf_ticker),
                    event=COALESCE(:event,event), predicted_side=COALESCE(:predicted_side,predicted_side),
                    predicted_move=COALESCE(:predicted_move,predicted_move),
                    reason=COALESCE(:reason,reason), status=:status
                WHERE id=:id
            """), values)

    # --- guarded enrichment backlog (mode "backfill") ---------------------------
    _BACKLOG_SQL = """FROM public.news n
        WHERE n.status IN ('pending_enrichment','retryable') AND mod(n.id,:count)=:shard
          AND NOT EXISTS (SELECT 1 FROM alpatrade.news_worker_events ev
                          WHERE ev.news_id=n.id AND ev.job_name=:job
                            AND ev.created_at > NOW() - make_interval(hours => :cooldown))"""

    def backlog(self, job_name: str, limit: int, shard_index: int = 0, shard_count: int = 1,
                cooldown_hours: int = 24) -> list[dict]:
        """Newest pending/retryable rows first; a row tried in the last
        ``cooldown_hours`` is skipped so a permanently failing row can't eat the
        daily budget."""
        with self.engine.connect() as conn:
            rows = conn.execute(text(f"SELECT n.* {self._BACKLOG_SQL} ORDER BY n.id DESC LIMIT :limit"), {
                "job": job_name, "limit": limit, "count": shard_count, "shard": shard_index,
                "cooldown": cooldown_hours}).mappings().all()
        return [dict(row) for row in rows]

    def backlog_remaining(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text(
                "SELECT count(*) FROM public.news WHERE status IN ('pending_enrichment','retryable')"
            )).scalar() or 0)

    def attempts_today(self, job_name: str) -> int:
        """Rows this job tried since 00:00 UTC (the daily run limit's counter)."""
        with self.engine.connect() as conn:
            return int(conn.execute(text("""SELECT count(*) FROM alpatrade.news_worker_events
                WHERE job_name=:job AND event_name IN ('backfill_enriched','backfill_retryable','backfill_failed')
                  AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"""),
                {"job": job_name}).scalar() or 0)

    def status(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text("SELECT * FROM alpatrade.news_worker_jobs ORDER BY updated_at DESC")).mappings()]
