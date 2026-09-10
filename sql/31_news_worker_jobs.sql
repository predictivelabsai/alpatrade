CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.news_worker_jobs (
    job_name TEXT NOT NULL,
    shard_index INTEGER NOT NULL DEFAULT 0 CHECK (shard_index >= 0),
    shard_count INTEGER NOT NULL DEFAULT 1 CHECK (shard_count > 0 AND shard_index < shard_count),
    last_processed_news_id BIGINT NOT NULL DEFAULT 0,
    last_inserted_news_id BIGINT,
    processed_count BIGINT NOT NULL DEFAULT 0,
    failed_count BIGINT NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'stopped' CHECK (status IN ('running','stopped','error')),
    last_successful_cycle TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_name, shard_index, shard_count)
);

CREATE INDEX IF NOT EXISTS idx_news_worker_jobs_updated
    ON alpatrade.news_worker_jobs(updated_at DESC);

REVOKE ALL ON alpatrade.news_worker_jobs FROM PUBLIC;
