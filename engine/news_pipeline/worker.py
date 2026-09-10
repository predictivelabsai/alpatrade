"""Dedicated, resumable Finespresso news worker (never imported by web/API)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.exc import DBAPIError, OperationalError
from openai import APIConnectionError, APITimeoutError, RateLimitError

from engine.db.pool import DatabasePool
from engine.news_pipeline.models import MissingEventModel, ModelRegistry
from engine.news_pipeline.pipeline import IncompleteArticle, NewsPipeline
from engine.news_pipeline.publishers import RSSPublishers
from engine.news_pipeline.repository import NewsRepository
from engine.news_pipeline.xai import XAIEnricher

log = logging.getLogger("alpatrade.news_worker")
STOP = threading.Event()
RETRYABLE = (OperationalError, DBAPIError, TimeoutError, ConnectionError,
             APIConnectionError, APITimeoutError, RateLimitError)


def _event(level: int, name: str, **data) -> None:
    # IDs/field names are safe; article content and credentials are never logged.
    log.log(level, json.dumps({"event": name, **data}, default=str, ensure_ascii=True))


def _safe_error(exc: Exception) -> str:
    """Persist a category without URLs, credentials, or article text."""
    return f"{type(exc).__name__}: operation failed; see sanitized structured logs"


class Worker:
    def __init__(self, mode: str, batch_size: int, interval: int, shard_index: int, shard_count: int,
                 repository=None, pipeline=None, publishers=None):
        pool = DatabasePool()
        self.mode, self.batch_size, self.interval = mode, batch_size, interval
        self.shard_index, self.shard_count = shard_index, shard_count
        self.job_name = f"news-{mode}"
        self.repo = repository or NewsRepository(pool.engine)
        self.pipeline = pipeline or NewsPipeline(ModelRegistry(pool.engine), XAIEnricher())
        self.publishers = publishers or RSSPublishers()

    def _retry(self, action, *, attempts: int = 4):
        for attempt in range(attempts):
            try:
                return action()
            except RETRYABLE:
                if attempt == attempts - 1:
                    raise
                delay = min(30.0, 2 ** attempt + random.random())
                _event(logging.WARNING, "transient_retry", attempt=attempt + 1, delay_seconds=round(delay, 2))
                STOP.wait(delay)

    def _backfill_cycle(self) -> bool:
        state = self.repo.checkpoint(self.job_name, self.shard_index, self.shard_count)
        rows = self._retry(lambda: self.repo.incomplete(int(state["last_processed_news_id"] or 0), self.batch_size,
                                                        self.shard_index, self.shard_count))
        if not rows:
            self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                                        status="stopped", last_successful_cycle=datetime.now(timezone.utc), last_error=None)
            return False
        processed, failed = int(state["processed_count"] or 0), int(state["failed_count"] or 0)
        last_id = int(state["last_processed_news_id"] or 0)
        for row in rows:
            if STOP.is_set():
                break
            candidate_id = int(row["id"])
            try:
                enriched = self._retry(lambda row=row: self.pipeline.enrich(row))
                self._retry(lambda: self.repo.update_enriched(candidate_id, enriched))
                processed += 1
                last_id = candidate_id
            except (IncompleteArticle, MissingEventModel, *RETRYABLE) as exc:
                failed += 1
                _event(logging.ERROR, "article_retryable", news_id=candidate_id, error_type=type(exc).__name__)
                # Never advance beyond a failed row: the next cycle/restart retries it.
                self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                    last_processed_news_id=last_id, processed_count=processed, failed_count=failed,
                    last_error=_safe_error(exc), status="running")
                return True
            self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                last_processed_news_id=last_id, processed_count=processed, failed_count=failed,
                last_error=None, status="running", last_successful_cycle=datetime.now(timezone.utc))
        return True

    def _realtime_cycle(self) -> bool:
        state = self.repo.checkpoint(self.job_name, self.shard_index, self.shard_count)
        processed, failed, inserted = int(state["processed_count"] or 0), int(state["failed_count"] or 0), None
        articles = list(self._retry(self.publishers.collect))[:self.batch_size]
        for article in articles:
            try:
                enriched = self._retry(lambda article=article: self.pipeline.enrich(article))
                inserted = self._retry(lambda: self.repo.insert_enriched(enriched)) or inserted
                processed += 1
            except (IncompleteArticle, MissingEventModel, *RETRYABLE) as exc:
                failed += 1
                _event(logging.ERROR, "article_retryable", source_link=bool(article.get("link")), error_type=type(exc).__name__)
        self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
            last_inserted_news_id=inserted, processed_count=processed, failed_count=failed,
            status="running", last_successful_cycle=datetime.now(timezone.utc), last_error=None)
        return True

    def run(self) -> int:
        self.repo.checkpoint(self.job_name, self.shard_index, self.shard_count)
        with self.repo.lock(self.job_name, self.shard_index) as acquired:
            if not acquired:
                _event(logging.WARNING, "duplicate_worker_rejected", mode=self.mode, shard=self.shard_index)
                return 2
            self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                                        status="running", started_at=datetime.now(timezone.utc), last_error=None)
            _event(logging.INFO, "worker_started", mode=self.mode, shard=self.shard_index, shard_count=self.shard_count)
            try:
                while not STOP.is_set():
                    has_more = self._backfill_cycle() if self.mode == "backfill" else self._realtime_cycle()
                    if self.mode == "backfill" and not has_more:
                        break
                    if self.mode == "realtime":
                        STOP.wait(self.interval)
            except Exception as exc:
                self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                                            status="error", last_error=_safe_error(exc))
                _event(logging.ERROR, "worker_failed", error_type=type(exc).__name__)
                return 1
            finally:
                if STOP.is_set():
                    self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count, status="stopped")
                _event(logging.INFO, "worker_stopped", mode=self.mode, shard=self.shard_index)
        return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("realtime", "backfill"), default=os.getenv("NEWS_WORKER_MODE", "realtime"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("NEWS_WORKER_BATCH_SIZE", "25")))
    parser.add_argument("--interval", type=int, default=int(os.getenv("NEWS_WORKER_INTERVAL_SECONDS", "3600")))
    parser.add_argument("--shard-index", type=int, default=int(os.getenv("NEWS_WORKER_SHARD_INDEX", "0")))
    parser.add_argument("--shard-count", type=int, default=int(os.getenv("NEWS_WORKER_SHARD_COUNT", "1")))
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.interval < 1 or args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("positive batch/interval/shard-count required; shard-index must be in range")
    return args


def main(argv=None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    args = parse_args(argv)
    return Worker(args.mode, args.batch_size, args.interval, args.shard_index, args.shard_count).run()


if __name__ == "__main__":
    raise SystemExit(main())
