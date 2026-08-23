-- Durable, user-scoped asynchronous work submitted through the Hermes broker.
CREATE TABLE IF NOT EXISTS alpatrade.hermes_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id VARCHAR(64) NOT NULL UNIQUE,
    kind VARCHAR(24) NOT NULL CHECK (kind IN ('backtest', 'paper')),
    status VARCHAR(24) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL,
    thread_id UUID REFERENCES alpatrade.chat_conversations(thread_id) ON DELETE SET NULL,
    candidate_id UUID REFERENCES alpatrade.strategy_candidates(candidate_id) ON DELETE SET NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    claimed_by VARCHAR(96),
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hermes_jobs_queue
    ON alpatrade.hermes_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_user
    ON alpatrade.hermes_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_thread
    ON alpatrade.hermes_jobs(thread_id, created_at DESC);
