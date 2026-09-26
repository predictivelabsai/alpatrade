-- 36_live_report_deliveries.sql
-- One row per daily LIVE report delivery (scripts/daily_live_report.py), keyed by
-- the live account number rather than alpatrade.user_accounts (paper) — so the
-- paper report_deliveries table and its FK stay untouched. The report also creates
-- this table lazily (CREATE TABLE IF NOT EXISTS) on first use.
-- Apply with: python run_migration.py sql/36_live_report_deliveries.sql

CREATE TABLE IF NOT EXISTS alpatrade.live_report_deliveries (
    delivery_id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_number VARCHAR(32) NOT NULL,
    report_date DATE NOT NULL,
    report_kind VARCHAR(32) NOT NULL DEFAULT 'daily_live',
    status VARCHAR(16) NOT NULL DEFAULT 'sending',
    message_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    UNIQUE (user_id, account_number, report_date, report_kind)
);
