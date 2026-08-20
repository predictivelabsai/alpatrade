-- 18_deepagent_responses.sql
-- Durable, tenant-scoped API response/idempotency records and sanitized traces.

CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.deepagent_responses (
    response_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES alpatrade.chat_conversations(thread_id) ON DELETE CASCADE,
    request_message_id UUID NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL,
    request_id VARCHAR(128),
    process_instance_id UUID NOT NULL,
    auth_type VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    model_provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    response_payload JSONB,
    error_code VARCHAR(64),
    error_message VARCHAR(512),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, thread_id, request_message_id)
);

-- Converge safely if an interrupted/preview deployment created an earlier
-- version of this new table before the migration was rerun.
ALTER TABLE alpatrade.deepagent_responses
    ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);
UPDATE alpatrade.deepagent_responses
SET request_fingerprint = REPEAT('0', 64)
WHERE request_fingerprint IS NULL;
ALTER TABLE alpatrade.deepagent_responses
    ALTER COLUMN request_fingerprint SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_deepagent_responses_thread_started
    ON alpatrade.deepagent_responses (user_id, thread_id, started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_deepagent_running_thread
    ON alpatrade.deepagent_responses (user_id, thread_id)
    WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_thread_message_id
    ON alpatrade.chat_messages (thread_id, message_id);

CREATE TABLE IF NOT EXISTS alpatrade.deepagent_events (
    event_id BIGSERIAL PRIMARY KEY,
    response_id UUID NOT NULL REFERENCES alpatrade.deepagent_responses(response_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    call_id VARCHAR(128),
    name VARCHAR(128),
    status VARCHAR(32),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (response_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS idx_deepagent_events_response_sequence
    ON alpatrade.deepagent_events (response_id, sequence_no);

CREATE TABLE IF NOT EXISTS alpatrade.deepagent_actions (
    action_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    response_id UUID NOT NULL REFERENCES alpatrade.deepagent_responses(response_id) ON DELETE CASCADE,
    request_message_id UUID NOT NULL,
    tool_call_id VARCHAR(128) NOT NULL,
    tool_name VARCHAR(128) NOT NULL,
    job_id UUID REFERENCES alpatrade.autonomy_runs(run_id) ON DELETE SET NULL,
    order_client_id VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'accepted',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (response_id, request_message_id, tool_call_id, tool_name)
);

ALTER TABLE alpatrade.autonomy_runs
    ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_autonomy_runs_user_dedupe_key
    ON alpatrade.autonomy_runs (user_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
