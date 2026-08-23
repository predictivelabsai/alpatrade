-- User-scoped Hermes portfolio construction and entry/exit advice.
CREATE TABLE IF NOT EXISTS alpatrade.hermes_advice (
    advice_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL,
    job_id UUID REFERENCES alpatrade.hermes_jobs(job_id) ON DELETE CASCADE,
    candidate_id UUID REFERENCES alpatrade.strategy_candidates(candidate_id) ON DELETE SET NULL,
    thread_id UUID REFERENCES alpatrade.chat_conversations(thread_id) ON DELETE SET NULL,
    advice_type VARCHAR(24) NOT NULL
        CHECK (advice_type IN ('portfolio', 'entry', 'exit', 'hold', 'risk')),
    symbol VARCHAR(16),
    action VARCHAR(24) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'info'
        CHECK (severity IN ('info', 'watch', 'action')),
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    delivered_in_app BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_email BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hermes_advice_user
    ON alpatrade.hermes_advice(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_advice_job
    ON alpatrade.hermes_advice(job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_advice_dedupe
    ON alpatrade.hermes_advice(job_id, symbol, action, created_at DESC);
