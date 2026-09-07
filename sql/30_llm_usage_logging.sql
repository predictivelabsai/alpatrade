-- Tenant-scoped LLM token/cost accounting. No credential values are stored.
CREATE TABLE IF NOT EXISTS alpatrade.llm_usage_logging (
    usage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES alpatrade.users(user_id) ON DELETE SET NULL,
    thread_id UUID,
    request_id VARCHAR(128),
    job_id VARCHAR(128),
    agent_framework VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    funding_source VARCHAR(16) NOT NULL,
    input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens BIGINT NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    estimated_cost_usd NUMERIC(14,6) NOT NULL DEFAULT 0 CHECK (estimated_cost_usd >= 0),
    usage_quality VARCHAR(16) NOT NULL DEFAULT 'estimated',
    status VARCHAR(24) NOT NULL DEFAULT 'completed',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT llm_usage_funding_check CHECK (funding_source IN ('platform','user_byok')),
    CONSTRAINT llm_usage_quality_check CHECK (usage_quality IN ('measured','estimated','unavailable'))
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_owner_created
    ON alpatrade.llm_usage_logging(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_daily_platform
    ON alpatrade.llm_usage_logging(created_at, funding_source, status);
CREATE INDEX IF NOT EXISTS idx_llm_usage_agent_created
    ON alpatrade.llm_usage_logging(agent_framework, created_at DESC);
