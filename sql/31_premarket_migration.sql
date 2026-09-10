-- Source company/calendar/snapshot/analysis history stays in premarket_screener.
-- Market observations and narratives are public research; user_id/account_id
-- attribute requests only and must never introduce portfolio data into them.
CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.premarket_observations (
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id INTEGER NOT NULL,
    trading_date DATE NOT NULL,
    user_id UUID,
    account_id UUID,
    prev_close DOUBLE PRECISION,
    premarket_close DOUBLE PRECISION,
    accumulated_volume DOUBLE PRECISION,
    as_of TIMESTAMPTZ,
    quote_timestamp TIMESTAMPTZ,
    data_source TEXT NOT NULL DEFAULT 'massive',
    finalized BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, trading_date)
);
CREATE INDEX IF NOT EXISTS idx_premarket_observations_date
    ON alpatrade.premarket_observations(trading_date DESC) WHERE finalized;

CREATE TABLE IF NOT EXISTS alpatrade.premarket_analyses (
    analysis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id INTEGER NOT NULL,
    trading_date DATE NOT NULL,
    provider TEXT NOT NULL DEFAULT 'grok' CHECK(provider='grok'),
    model_name TEXT NOT NULL,
    user_id UUID,
    account_id UUID,
    narrative TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    observation_identity TEXT NOT NULL,
    retrospective BOOLEAN NOT NULL DEFAULT FALSE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, trading_date, provider)
);
CREATE INDEX IF NOT EXISTS idx_premarket_analyses_date
    ON alpatrade.premarket_analyses(trading_date DESC);

CREATE TABLE IF NOT EXISTS alpatrade.premarket_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL CHECK(kind IN ('previous_closes','finalize','analysis')),
    dedupe_key TEXT NOT NULL UNIQUE,
    trading_date DATE NOT NULL,
    company_id INTEGER,
    user_id UUID,
    account_id UUID,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    heartbeat_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    funding_source TEXT CHECK(funding_source IN ('platform','byok')),
    platform_slot BOOLEAN NOT NULL DEFAULT FALSE,
    refunded BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_premarket_jobs_claim
    ON alpatrade.premarket_jobs(available_at,created_at) WHERE status='queued';
CREATE INDEX IF NOT EXISTS idx_premarket_jobs_heartbeat
    ON alpatrade.premarket_jobs(heartbeat_at) WHERE status='running';

-- Optional indexes: an empty development DB need not contain the shared schema.
DO $$ BEGIN
    IF to_regclass('premarket_screener.snapshots') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_premarket_snapshot_date_company
            ON premarket_screener.snapshots(date,company_id,snapshot_id DESC);
    END IF;
    IF to_regclass('premarket_screener.previous_closes') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_premarket_previous_close_date_company
            ON premarket_screener.previous_closes(date,company_id);
    END IF;
    IF to_regclass('premarket_screener.llm_analysis') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_premarket_legacy_analysis_date_company
            ON premarket_screener.llm_analysis(date,company_id,model_provider,analysis_id DESC);
    END IF;
END $$;
