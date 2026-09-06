-- Tenant-scoped saved public-market scanners and in-app daily digest alerts.

CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.saved_market_views (
    view_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    page_key VARCHAR(32) NOT NULL CHECK (page_key IN ('ipo-pipeline', 'spacs', 'filings', 'hedge-funds', 'press')),
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    daily_digest BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_market_views_user_active
    ON alpatrade.saved_market_views (user_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS alpatrade.market_alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    view_id UUID NOT NULL REFERENCES alpatrade.saved_market_views(view_id) ON DELETE CASCADE,
    alert_date DATE NOT NULL,
    title VARCHAR(180) NOT NULL,
    body TEXT NOT NULL,
    target_path TEXT NOT NULL,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (view_id, alert_date)
);

CREATE INDEX IF NOT EXISTS idx_market_alerts_user_unread
    ON alpatrade.market_alerts (user_id, read_at, created_at DESC);
