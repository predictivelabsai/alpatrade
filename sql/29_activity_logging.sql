-- Unified, tenant-safe user and agent activity history.
-- Idempotent and restricted to the alpatrade schema.

CREATE TABLE IF NOT EXISTS alpatrade.user_logging (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    thread_id UUID,
    request_text TEXT NOT NULL DEFAULT '',
    response_text TEXT,
    agent_framework VARCHAR(64),
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT user_logging_status_check
        CHECK (status IN ('pending', 'completed', 'failed', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_user_logging_owner_created
    ON alpatrade.user_logging(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_logging_thread_pending
    ON alpatrade.user_logging(user_id, thread_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS alpatrade.agent_logging (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID,
    agent_framework VARCHAR(64) NOT NULL DEFAULT 'legacy',
    operation_type VARCHAR(32) NOT NULL,
    job_id VARCHAR(64),
    run_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    source_table VARCHAR(32) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_logging_source UNIQUE (source_table, source_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_logging_owner_created
    ON alpatrade.agent_logging(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_logging_status
    ON alpatrade.agent_logging(status, updated_at DESC);

CREATE OR REPLACE FUNCTION alpatrade.sync_hermes_agent_logging()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO alpatrade.agent_logging
        (user_id, account_id, agent_framework, operation_type, job_id, run_id,
         status, details, error, source_table, source_id, started_at,
         completed_at, created_at, updated_at)
    VALUES
        (NEW.user_id, NEW.account_id, 'hermes', NEW.kind, NEW.job_id::text,
         NEW.run_id, NEW.status,
         jsonb_strip_nulls(jsonb_build_object(
             'strategy', NEW.config->'strategy', 'symbols', NEW.config->'symbols',
             'lookback', NEW.config->'lookback',
             'progress', NEW.progress->'message')),
         NEW.error, 'hermes_jobs', NEW.job_id::text, NEW.started_at,
         NEW.completed_at, NEW.created_at, NEW.updated_at)
    ON CONFLICT (source_table, source_id) DO UPDATE SET
        status = EXCLUDED.status, details = EXCLUDED.details,
        error = EXCLUDED.error, started_at = EXCLUDED.started_at,
        completed_at = EXCLUDED.completed_at, updated_at = EXCLUDED.updated_at;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    -- Observability must never block the underlying trading job transition.
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_hermes_agent_logging ON alpatrade.hermes_jobs;
CREATE TRIGGER trg_hermes_agent_logging
AFTER INSERT OR UPDATE ON alpatrade.hermes_jobs
FOR EACH ROW EXECUTE FUNCTION alpatrade.sync_hermes_agent_logging();

CREATE OR REPLACE FUNCTION alpatrade.sync_run_agent_logging()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO alpatrade.agent_logging
        (user_id, account_id, agent_framework, operation_type, job_id, run_id,
         status, details, source_table, source_id, started_at, completed_at,
         created_at, updated_at)
    VALUES
        (NEW.user_id, NEW.account_id, COALESCE(NEW.agent_framework, 'legacy'),
         NEW.mode, NEW.run_id, NEW.run_id, NEW.status,
         jsonb_strip_nulls(jsonb_build_object('strategy', NEW.strategy)),
         'runs', NEW.run_id, NEW.started_at, NEW.completed_at, NEW.created_at, NOW())
    ON CONFLICT (source_table, source_id) DO UPDATE SET
        user_id = EXCLUDED.user_id, account_id = EXCLUDED.account_id,
        agent_framework = EXCLUDED.agent_framework,
        operation_type = EXCLUDED.operation_type, status = EXCLUDED.status,
        details = EXCLUDED.details, started_at = EXCLUDED.started_at,
        completed_at = EXCLUDED.completed_at, updated_at = NOW();
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_run_agent_logging ON alpatrade.runs;
CREATE TRIGGER trg_run_agent_logging
AFTER INSERT OR UPDATE ON alpatrade.runs
FOR EACH ROW EXECUTE FUNCTION alpatrade.sync_run_agent_logging();

CREATE OR REPLACE FUNCTION alpatrade.sync_autonomy_agent_logging()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO alpatrade.agent_logging
        (user_id, account_id, agent_framework, operation_type, job_id, run_id,
         status, details, error, source_table, source_id, started_at, created_at,
         updated_at)
    VALUES
        (NEW.user_id, NEW.account_id, 'autonomy', NEW.kind, NEW.run_id::text,
         NEW.run_id::text, NEW.status,
         jsonb_build_object('attempt', NEW.attempt), NEW.error,
         'autonomy_runs', NEW.run_id::text, NEW.created_at, NEW.created_at,
         NEW.updated_at)
    ON CONFLICT (source_table, source_id) DO UPDATE SET
        status = EXCLUDED.status, details = EXCLUDED.details,
        error = EXCLUDED.error, updated_at = EXCLUDED.updated_at;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_autonomy_agent_logging ON alpatrade.autonomy_runs;
CREATE TRIGGER trg_autonomy_agent_logging
AFTER INSERT OR UPDATE ON alpatrade.autonomy_runs
FOR EACH ROW EXECUTE FUNCTION alpatrade.sync_autonomy_agent_logging();

-- Make existing history visible immediately after deployment.
INSERT INTO alpatrade.agent_logging
    (user_id, account_id, agent_framework, operation_type, job_id, run_id,
     status, details, error, source_table, source_id, started_at, completed_at,
     created_at, updated_at)
SELECT user_id, account_id, 'hermes', kind, job_id::text, run_id, status,
       jsonb_strip_nulls(jsonb_build_object(
           'strategy', config->'strategy', 'symbols', config->'symbols',
           'lookback', config->'lookback', 'progress', progress->'message')),
       error, 'hermes_jobs', job_id::text, started_at, completed_at, created_at, updated_at
FROM alpatrade.hermes_jobs
ON CONFLICT (source_table, source_id) DO NOTHING;

INSERT INTO alpatrade.agent_logging
    (user_id, account_id, agent_framework, operation_type, job_id, run_id,
     status, details, source_table, source_id, started_at, completed_at,
     created_at, updated_at)
SELECT user_id, account_id, COALESCE(agent_framework, 'legacy'), mode, run_id,
       run_id, status, jsonb_strip_nulls(jsonb_build_object('strategy', strategy)),
       'runs', run_id, started_at, completed_at, created_at, NOW()
FROM alpatrade.runs
ON CONFLICT (source_table, source_id) DO NOTHING;

INSERT INTO alpatrade.agent_logging
    (user_id, account_id, agent_framework, operation_type, job_id, run_id,
     status, details, error, source_table, source_id, started_at, created_at,
     updated_at)
SELECT user_id, account_id, 'autonomy', kind, run_id::text, run_id::text,
       status, jsonb_build_object('attempt', attempt), error, 'autonomy_runs',
       run_id::text, created_at, created_at, updated_at
FROM alpatrade.autonomy_runs
ON CONFLICT (source_table, source_id) DO NOTHING;
