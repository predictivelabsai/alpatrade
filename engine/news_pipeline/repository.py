"""The only AlpaTrade component authorized to mutate the shared news feed."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Any, Iterable

from sqlalchemy import text

from engine.news_pipeline.validation import REQUIRED_FIELDS

_MISSING_SQL = " OR ".join([
    "company IS NULL OR btrim(company)='' OR lower(btrim(company)) IN ('nan','n/a','error in summarization')",
    "language IS NULL OR btrim(language)=''",
    "title_en IS NULL OR btrim(title_en)=''",
    "content_en IS NULL OR btrim(content_en)=''",
    "predicted_side IS NULL OR upper(btrim(predicted_side)) NOT IN ('UP','DOWN','NEUTRAL')",
    "predicted_move IS NULL OR predicted_move::text IN ('NaN','Infinity','-Infinity')",
    "reason IS NULL OR btrim(reason)='' OR lower(btrim(reason)) IN ('nan','n/a','error in summarization')",
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
                AND mod(id,:count)=:shard AND event='press_releases'
                AND ({_MISSING_SQL}) ORDER BY id LIMIT :limit"""),
                {"after": after_id, "count": shard_count, "shard": shard_index, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def remaining(self, shard_index: int = 0, shard_count: int = 1) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM public.news WHERE mod(id,:count)=:shard AND event='press_releases' AND ({_MISSING_SQL})"),
                                    {"count": shard_count, "shard": shard_index}).scalar() or 0)

    def update_enriched(self, article_id: int, row: dict[str, Any]) -> None:
        values = {name: row[name] for name in REQUIRED_FIELDS}
        values.update({"id": article_id, "event": row.get("event_standardized") or row.get("event")})
        with self.engine.begin() as conn:
            conn.execute(text("""UPDATE public.news SET company=:company, language=:language,
                title_en=:title_en, content_en=:content_en, predicted_side=:predicted_side,
                predicted_move=:predicted_move, reason=:reason, event=:event
                WHERE id=:id"""), values)

    def insert_enriched(self, row: dict[str, Any]) -> int | None:
        values = dict(row)
        with self.engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO public.news(title, content, link, publisher, published_date, ticker, yf_ticker,
                    event, company, language, title_en, content_en, predicted_side, predicted_move, reason)
                SELECT :title,:content,:link,:publisher,:published_date,:ticker,:yf_ticker,:event_standardized,
                    :company,:language,:title_en,:content_en,:predicted_side,:predicted_move,:reason
                WHERE NOT EXISTS (SELECT 1 FROM public.news WHERE link=:link AND publisher=:publisher)
                RETURNING id
            """), values).scalar()
        return int(result) if result is not None else None

    def status(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text("SELECT * FROM alpatrade.news_worker_jobs ORDER BY updated_at DESC")).mappings()]
