-- 17_alpha_research_runs.sql
-- Minimal, user-scoped persistence for local Alpha Growth/Value reports.

CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.alpha_research_runs (
    run_id UUID PRIMARY KEY,
    user_id UUID REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    mode VARCHAR(16) NOT NULL CHECK (mode IN ('growth', 'value')),
    ticker VARCHAR(16) NOT NULL
        CHECK (ticker ~ '^[A-Z0-9][A-Z0-9.-]{0,15}$'),
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    methodology_version VARCHAR(64) NOT NULL,
    model_provider VARCHAR(32),
    model_name VARCHAR(128),
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    report_markdown TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alpha_research_runs_user_created
    ON alpatrade.alpha_research_runs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alpha_research_runs_ticker_created
    ON alpatrade.alpha_research_runs (ticker, created_at DESC);
