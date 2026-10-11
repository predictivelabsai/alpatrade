-- 2026-10-11: the publisher+link dedupe check used by both news writers
-- (AlpaTrade news_scheduler and CityTicker news_worker) was a ~1.2 s sequential
-- scan of public.news per article. A hash index on link serves
-- `WHERE publisher=:p AND link=:l` with no key-length limit.
-- CONCURRENTLY: run outside a transaction (psql -f, or autocommit), not run_migration.py.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_link_hash ON public.news USING hash (link);
-- Guarded backlog: per-row 24 h cooldown lookup.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_worker_events_job_news
    ON alpatrade.news_worker_events (job_name, news_id, created_at DESC);
-- Partial index for the pending/retryable backlog scan (newest first).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_backlog_status_id
    ON public.news (id DESC) WHERE status IN ('pending_enrichment', 'retryable');
