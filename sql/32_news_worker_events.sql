CREATE TABLE IF NOT EXISTS alpatrade.news_worker_events (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    shard_index INTEGER NOT NULL DEFAULT 0,
    event_name TEXT NOT NULL,
    status TEXT NOT NULL,
    news_id BIGINT,
    publisher TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_worker_events_created
    ON alpatrade.news_worker_events (created_at DESC);

REVOKE ALL ON alpatrade.news_worker_events FROM PUBLIC;
