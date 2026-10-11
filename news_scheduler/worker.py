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
from news_scheduler.models import ModelRegistry
from news_scheduler.pipeline import NewsPipeline
from news_scheduler.publishers import RSSPublishers
from news_scheduler.repository import NewsRepository
from news_scheduler.xai import XAIEnricher

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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class BacklogGuard:
    """Cost guards for the enrichment backlog, mirroring the 2026-09-28 autonomy
    LoopGuard: exponential back-off after a failed cycle, a pause after
    ``max_failures`` consecutive failed cycles, and a daily row limit that fails
    closed when the counter is unavailable."""

    def __init__(self, *, base_seconds: int, max_failures: int | None = None,
                 pause_seconds: int | None = None, max_backoff: int | None = None,
                 daily_limit: int | None = None, clock=time.monotonic):
        self.base_seconds = max(1, base_seconds)
        self.max_failures = max(1, max_failures if max_failures is not None
                                else _env_int("NEWS_BACKFILL_MAX_CONSECUTIVE_FAILURES", 3))
        self.pause_seconds = (pause_seconds if pause_seconds is not None
                              else _env_int("NEWS_BACKFILL_FAILURE_PAUSE_SECONDS", 6 * 3600))
        self.max_backoff = max(self.base_seconds, max_backoff if max_backoff is not None
                               else _env_int("NEWS_BACKFILL_MAX_BACKOFF_SECONDS", 4 * 3600))
        self.daily_limit = (daily_limit if daily_limit is not None
                            else _env_int("NEWS_BACKFILL_MAX_PER_DAY", 400))
        self.clock = clock
        self.failures = 0
        self.paused_until = 0.0

    def paused(self) -> bool:
        return self.clock() < self.paused_until

    def record(self, failed: bool) -> bool:
        """Returns True when this failure tripped the pause."""
        if not failed:
            self.failures = 0
            return False
        self.failures += 1
        if self.failures >= self.max_failures:
            self.paused_until = self.clock() + self.pause_seconds
            self.failures = 0
            return True
        return False

    def sleep_seconds(self) -> int:
        if self.paused():
            return int(max(1, self.paused_until - self.clock()))
        if not self.failures:
            return self.base_seconds
        return int(min(self.base_seconds * (2 ** (self.failures - 1)), self.max_backoff))

    def allowance(self, used_today) -> int:
        if self.daily_limit <= 0:
            return 0
        try:
            return max(0, self.daily_limit - int(used_today()))
        except Exception as exc:  # noqa: BLE001 — fail closed
            _event(logging.WARNING, "backfill_daily_limit_check_failed", error_type=type(exc).__name__)
            return 0


class Worker:
    def __init__(self, mode: str, batch_size: int, interval: int, shard_index: int, shard_count: int,
                 repository=None, pipeline=None, publishers=None):
        # Keep dependency injection genuinely DB-free for unit tests and local
        # tooling. Production constructs both defaults and therefore still
        # requires DATABASE_URL before the worker can start.
        pool = DatabasePool() if repository is None or pipeline is None else None
        self.mode, self.batch_size, self.interval = mode, batch_size, interval
        self.shard_index, self.shard_count = shard_index, shard_count
        self.job_name = f"news-{mode}"
        self.repo = repository or NewsRepository(pool.engine)
        self.pipeline = pipeline or NewsPipeline(ModelRegistry(pool.engine), XAIEnricher())
        self.publishers = publishers or RSSPublishers()
        self.guard = BacklogGuard(base_seconds=interval) if mode == "backfill" else None

    def _record(self, event_name: str, status: str, **values) -> None:
        try:
            self.repo.record_event(self.job_name, self.shard_index, event_name, status, **values)
        except Exception as exc:  # monitoring must never stop ingestion
            _event(logging.WARNING, "event_record_failed", error_type=type(exc).__name__)

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
        # "full-backfill" is the original id-ascending scan of every incomplete row
        # (~239k legacy rows, ~$300 of xAI): opt-in only, never the default.
        targeted = self.mode == "company-backfill"
        fetch = self.repo.incomplete_company_type if targeted else self.repo.incomplete
        count_remaining = (self.repo.remaining_company_type if targeted
                           else self.repo.remaining)
        rows = self._retry(lambda: fetch(int(state["last_processed_news_id"] or 0), self.batch_size,
                                         self.shard_index, self.shard_count))
        if not rows:
            remaining = count_remaining(self.shard_index, self.shard_count)
            if remaining:
                # A complete pass may leave retryable rows behind. Rewind the
                # durable cursor so a later bounded cycle can try them again.
                self.repo.update_checkpoint(
                    self.job_name, self.shard_index, self.shard_count,
                    last_processed_news_id=0, status="running",
                    last_successful_cycle=datetime.now(timezone.utc),
                    last_error=None,
                )
                return True
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
                enriched, missing, issues = self.pipeline.enrich_best_effort(row)
                self._retry(lambda: self.repo.update_partial(candidate_id, enriched, missing))
                processed += 1
                last_id = candidate_id
                if missing:
                    failed += 1
                    _event(logging.WARNING, "backfill_retryable", news_id=candidate_id,
                           missing_fields=missing, issue_types=issues)
                    self._record("backfill_retryable", "retryable", news_id=candidate_id,
                                 publisher=row.get("publisher"), details={
                                     "missing_fields": missing, "issue_types": issues})
                else:
                    self._record("backfill_enriched", "completed", news_id=candidate_id,
                                 publisher=row.get("publisher"))
            except RETRYABLE as exc:
                failed += 1
                _event(logging.ERROR, "article_retryable", news_id=candidate_id, error_type=type(exc).__name__)
                # Advance within this pass so one database/provider failure
                # cannot block every later row; the cursor rewinds after a pass.
                last_id = candidate_id
            self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                last_processed_news_id=last_id, processed_count=processed, failed_count=failed,
                last_error=None, status="running", last_successful_cycle=datetime.now(timezone.utc))
        return True

    def _backlog_cycle(self) -> bool:
        """Guarded enrichment of pending/retryable rows, newest first.

        Returns True while the backlog has work. Sets ``self._cycle_failed`` for
        the guard: a cycle fails when rows were tried and none became complete.
        """
        self._cycle_failed = False
        guard = self.guard
        state = self.repo.checkpoint(self.job_name, self.shard_index, self.shard_count)
        allowance = guard.allowance(lambda: self.repo.attempts_today(self.job_name))
        if allowance <= 0:
            _event(logging.INFO, "backfill_daily_limit_reached", daily_limit=guard.daily_limit)
            self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
                                        status="running", last_error=None)
            return True
        rows = self._retry(lambda: self.repo.backlog(
            self.job_name, min(self.batch_size, allowance), self.shard_index, self.shard_count))
        processed, failed = int(state["processed_count"] or 0), int(state["failed_count"] or 0)
        completed = tried = 0
        last_id = state.get("last_processed_news_id")
        for row in rows:
            if STOP.is_set():
                break
            candidate_id = int(row["id"])
            tried += 1
            try:
                enriched, missing, issues = self.pipeline.enrich_best_effort(row)
                self._retry(lambda: self.repo.update_partial(candidate_id, enriched, missing))
                processed += 1
                last_id = candidate_id
                if missing:
                    failed += 1
                    self._record("backfill_retryable", "retryable", news_id=candidate_id,
                                 publisher=row.get("publisher"), details={
                                     "missing_fields": missing, "issue_types": issues})
                    if any(str(i).endswith("DailyBudgetExceeded") for i in issues):
                        _event(logging.WARNING, "backfill_budget_exhausted")
                        break
                else:
                    completed += 1
                    self._record("backfill_enriched", "completed", news_id=candidate_id,
                                 publisher=row.get("publisher"))
            except Exception as exc:  # noqa: BLE001 — counted, row cools down 24h
                failed += 1
                self._record("backfill_failed", "error", news_id=candidate_id,
                             publisher=row.get("publisher"), details={"error_type": type(exc).__name__})
        self._cycle_failed = tried > 0 and completed == 0
        remaining = self.repo.backlog_remaining()
        self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
            last_processed_news_id=last_id, processed_count=processed, failed_count=failed,
            status="running", last_successful_cycle=datetime.now(timezone.utc), last_error=None)
        _event(logging.INFO, "backfill_cycle_completed", tried=tried, enriched=completed,
               remaining=remaining, allowance=allowance)
        self._record("backfill_cycle_completed", "completed", details={
            "tried": tried, "enriched": completed, "remaining": remaining})
        return True

    def _realtime_cycle(self) -> bool:
        state = self.repo.checkpoint(self.job_name, self.shard_index, self.shard_count)
        processed, failed, inserted = int(state["processed_count"] or 0), int(state["failed_count"] or 0), None
        attempted = 0
        completed_this_cycle = partial_this_cycle = 0
        publisher_counts: dict[str, dict[str, int]] = {}
        # Fair share per publisher job inside the batch cap; already-stored links are
        # skipped inside each job's turn (the same publisher+link check CityTicker uses).
        exists_fn = getattr(self.repo, "article_exists", None)
        is_new = (lambda p, l: not exists_fn(p, l)) if exists_fn else None
        for article in self._retry(lambda: self.publishers.collect(
                is_new=is_new, batch_size=self.batch_size)):
            exists = getattr(self.repo, "article_exists", lambda *_: False)
            if exists(str(article.get("publisher") or ""), str(article.get("link") or "")):
                continue
            # Batch size is a hard cost/resource ceiling, not an insert target. It is
            # checked here (not after the try) so failing articles count too — the
            # Sep 2026 insert failure otherwise walked all ~3,400 feed items per cycle.
            if attempted >= self.batch_size:
                break
            attempted += 1
            publisher_job = str(article.get("publisher_job") or article.get("publisher") or "unknown")
            publisher_stats = publisher_counts.setdefault(
                publisher_job, {"attempted": 0, "enriched": 0, "partial": 0, "failed": 0})
            publisher_stats["attempted"] += 1
            try:
                # Match the original Finespresso behavior: save first, then
                # retain every enrichment field that succeeds.
                inserted_now = self._retry(lambda: self.repo.insert_pending(article))
                inserted = inserted_now or inserted
                if inserted_now is None:  # another worker won the idempotency race
                    continue
                processed += 1
                enriched, missing, issues = self.pipeline.enrich_best_effort(article)
                self._retry(lambda: self.repo.update_partial(inserted_now, enriched, missing))
                if not missing:
                    completed_this_cycle += 1
                    publisher_stats["enriched"] += 1
                    _event(logging.INFO, "article_inserted", news_id=inserted_now,
                           publisher=article.get("publisher"),
                           model_event=enriched.get("event_standardized"),
                           predicted_side=enriched.get("predicted_side"),
                           predicted_move=enriched.get("predicted_move"))
                    self._record("article_inserted", "completed", news_id=inserted_now,
                                 publisher=article.get("publisher"), details={
                                     "model_event": enriched.get("event_standardized"),
                                     "predicted_side": enriched.get("predicted_side"),
                                     "predicted_move": enriched.get("predicted_move"),
                                 })
                else:
                    partial_this_cycle += 1
                    failed += 1
                    publisher_stats["partial"] += 1
                    _event(logging.WARNING, "article_saved_partial", news_id=inserted_now,
                           publisher=article.get("publisher"), missing_fields=missing,
                           issue_types=issues)
                    self._record("article_saved_partial", "retryable", news_id=inserted_now,
                                 publisher=article.get("publisher"), details={
                                     "missing_fields": missing, "issue_types": issues})
            except RETRYABLE as exc:
                failed += 1
                publisher_stats["failed"] += 1
                _event(logging.ERROR, "article_retryable", source_link=bool(article.get("link")),
                       error_type=type(exc).__name__)
                self._record("article_retryable", "error", publisher=article.get("publisher"),
                             details={"error_type": type(exc).__name__})
                continue
        self.repo.update_checkpoint(self.job_name, self.shard_index, self.shard_count,
            last_inserted_news_id=inserted, processed_count=processed, failed_count=failed,
            status="running", last_successful_cycle=datetime.now(timezone.utc), last_error=None)
        _event(logging.INFO, "cycle_completed", mode=self.mode, attempted=attempted,
               enriched=completed_this_cycle, partial=partial_this_cycle,
               processed_count=processed, failed_count=failed, last_inserted_news_id=inserted)
        self._record("cycle_completed", "completed", news_id=inserted,
                     details={"attempted": attempted, "enriched": completed_this_cycle,
                              "partial": partial_this_cycle, "processed_count": processed,
                              "failed_count": failed, "publishers": publisher_counts})
        _event(logging.INFO, "publisher_cycle_summary", publishers=publisher_counts)
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
            self._record("worker_started", "running", details={"mode": self.mode,
                         "shard_count": self.shard_count})
            try:
                while not STOP.is_set():
                    if self.guard is not None and self.guard.paused():
                        STOP.wait(min(self.guard.sleep_seconds(), 300))
                        continue
                    try:
                        if self.mode == "realtime":
                            has_more = self._realtime_cycle()
                        elif self.mode == "backfill":
                            has_more = self._backlog_cycle()
                            if self.guard.record(self._cycle_failed):
                                msg = (f"news backfill PAUSED for {self.guard.pause_seconds}s after "
                                       f"{self.guard.max_failures} consecutive failed cycles")
                                _event(logging.ERROR, "backfill_paused", message=msg)
                                self._record("backfill_paused", "error", details={"message": msg})
                        else:
                            has_more = self._backfill_cycle()
                    except Exception as exc:
                        # A failed cycle is observable but never terminates the
                        # continuously scheduled worker.
                        try:
                            self.repo.update_checkpoint(
                                self.job_name, self.shard_index, self.shard_count,
                                status="running", last_error=_safe_error(exc))
                            self._record("cycle_failed", "error", details={
                                "error_type": type(exc).__name__})
                        except Exception:
                            pass
                        _event(logging.ERROR, "cycle_failed", error_type=type(exc).__name__)
                        if self.guard is not None:
                            self.guard.record(True)
                        has_more = True
                    if self.mode != "realtime" and not has_more:
                        break
                    STOP.wait(self.guard.sleep_seconds() if self.guard is not None else self.interval)
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
    parser.add_argument("--mode", choices=("realtime", "backfill", "full-backfill", "company-backfill"),
                        default=os.getenv("NEWS_WORKER_MODE", "realtime"))
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
