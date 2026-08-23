-- Phase 2: agent attribution and per-user saved strategy candidates.
-- Every object is explicitly schema-qualified. Hermes itself has no DB role.

ALTER TABLE alpatrade.runs
    ADD COLUMN IF NOT EXISTS agent_name VARCHAR(64),
    ADD COLUMN IF NOT EXISTS agent_framework VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_run_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_runs_user_agent
    ON alpatrade.runs(user_id, agent_framework, created_at DESC);

CREATE TABLE IF NOT EXISTS alpatrade.strategy_candidates (
    candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL,
    source_run_id VARCHAR(64) REFERENCES alpatrade.runs(run_id) ON DELETE SET NULL,
    agent_name VARCHAR(64) NOT NULL,
    agent_framework VARCHAR(64) NOT NULL,
    strategy VARCHAR(64) NOT NULL,
    symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    objective JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'paper', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_user
    ON alpatrade.strategy_candidates(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_candidates_source
    ON alpatrade.strategy_candidates(source_run_id);
