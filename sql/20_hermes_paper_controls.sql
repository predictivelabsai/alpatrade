-- Durable, account-scoped controls for Hermes paper sessions.
ALTER TABLE alpatrade.hermes_jobs
    ADD COLUMN IF NOT EXISTS control_requested VARCHAR(16) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ;

ALTER TABLE alpatrade.hermes_jobs
    DROP CONSTRAINT IF EXISTS hermes_jobs_status_check;
ALTER TABLE alpatrade.hermes_jobs
    ADD CONSTRAINT hermes_jobs_status_check
    CHECK (status IN ('queued', 'running', 'paused', 'completed', 'failed', 'cancelled', 'stopped'));

ALTER TABLE alpatrade.hermes_jobs
    DROP CONSTRAINT IF EXISTS hermes_jobs_control_requested_check;
ALTER TABLE alpatrade.hermes_jobs
    ADD CONSTRAINT hermes_jobs_control_requested_check
    CHECK (control_requested IN ('none', 'pause', 'stop'));

CREATE INDEX IF NOT EXISTS idx_hermes_jobs_control
    ON alpatrade.hermes_jobs(user_id, status, updated_at DESC);
