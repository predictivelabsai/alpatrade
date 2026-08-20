-- 19_daily_advisor.sql
-- Tenant-scoped, paper-only daily advisor reports and consolidated delivery state.

CREATE SCHEMA IF NOT EXISTS alpatrade;

-- Strategy slugs are the join key between the paper configuration and its
-- comparable backtest. Existing deployments already carry these columns, but
-- older/fresh numbered-migration installs did not declare them explicitly.
ALTER TABLE alpatrade.runs
    ADD COLUMN IF NOT EXISTS strategy_slug VARCHAR(128);
ALTER TABLE alpatrade.backtest_summaries
    ADD COLUMN IF NOT EXISTS strategy_slug VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_runs_strategy_slug
    ON alpatrade.runs (strategy_slug);
CREATE INDEX IF NOT EXISTS idx_backtest_summaries_strategy_slug
    ON alpatrade.backtest_summaries (strategy_slug);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_accounts_user_account_id
    ON alpatrade.user_accounts (user_id, account_id);

CREATE TABLE IF NOT EXISTS alpatrade.advisor_reports (
    report_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    account_id      UUID NOT NULL,
    session_date    DATE NOT NULL,
    status          VARCHAR(24) NOT NULL DEFAULT 'generating'
        CHECK (status IN ('generating', 'completed', 'partial', 'failed')),
    severity        VARCHAR(24) NOT NULL DEFAULT 'insufficient_data'
        CHECK (severity IN ('insufficient_data', 'monitor', 'review', 'urgent')),
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    advisory        JSONB,
    narrative       TEXT,
    model_provider  VARCHAR(64),
    model_name      VARCHAR(128),
    error_code      VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT fk_advisor_report_owned_account
        FOREIGN KEY (user_id, account_id)
        REFERENCES alpatrade.user_accounts(user_id, account_id)
        ON DELETE CASCADE
);

ALTER TABLE alpatrade.advisor_reports
    ADD COLUMN IF NOT EXISTS narrative TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_advisor_report_owned_account'
          AND conrelid = 'alpatrade.advisor_reports'::regclass
    ) THEN
        ALTER TABLE alpatrade.advisor_reports
            ADD CONSTRAINT fk_advisor_report_owned_account
            FOREIGN KEY (user_id, account_id)
            REFERENCES alpatrade.user_accounts(user_id, account_id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_advisor_reports_user_date
    ON alpatrade.advisor_reports (user_id, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_advisor_reports_account_date
    ON alpatrade.advisor_reports (account_id, session_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_advisor_reports_user_account_session
    ON alpatrade.advisor_reports (user_id, account_id, session_date);

CREATE TABLE IF NOT EXISTS alpatrade.advisor_deliveries (
    delivery_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    session_date    DATE NOT NULL,
    channel         VARCHAR(24) NOT NULL DEFAULT 'email'
        CHECK (channel IN ('email')),
    recipient       VARCHAR(255) NOT NULL,
    report_ids      JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(24) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'unknown', 'disabled')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    error_code      VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_advisor_deliveries_status
    ON alpatrade.advisor_deliveries (status, session_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_advisor_deliveries_user_session_channel_recipient
    ON alpatrade.advisor_deliveries (user_id, session_date, channel, recipient);
