CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.premarket_scan_runs (
    run_id UUID PRIMARY KEY,
    user_id UUID NULL,
    account_id UUID NULL,
    scan_timestamp TIMESTAMPTZ NOT NULL,
    scan_type TEXT NOT NULL DEFAULT 'single',
    status TEXT NOT NULL DEFAULT 'complete',
    total_sectors INTEGER NOT NULL DEFAULT 0,
    total_stocks_attempted INTEGER NOT NULL DEFAULT 0,
    total_stocks_failed INTEGER NOT NULL DEFAULT 0,
    total_stocks_scanned INTEGER NOT NULL DEFAULT 0,
    total_up_movements INTEGER NOT NULL DEFAULT 0,
    total_down_movements INTEGER NOT NULL DEFAULT 0,
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_premarket_scan_runs_timestamp
    ON alpatrade.premarket_scan_runs (scan_timestamp DESC);
