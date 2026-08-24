-- Tenant-safe daily reporting and paper-run liveness.
-- All objects are confined to the alpatrade schema.

ALTER TABLE alpatrade.runs
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_runs_tenant_paper_liveness
    ON alpatrade.runs(user_id, account_id, agent_framework, status, heartbeat_at DESC)
    WHERE mode IN ('paper', 'full');

CREATE TABLE IF NOT EXISTS alpatrade.account_equity_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES alpatrade.user_accounts(account_id) ON DELETE CASCADE,
    trading_date DATE NOT NULL,
    equity NUMERIC(18,4) NOT NULL,
    cash NUMERIC(18,4),
    buying_power NUMERIC(18,4),
    unrealized_pnl NUMERIC(18,4),
    net_cash_flow NUMERIC(18,4) NOT NULL DEFAULT 0,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, account_id, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_equity_snapshots_tenant_date
    ON alpatrade.account_equity_snapshots(user_id, account_id, trading_date DESC);

CREATE TABLE IF NOT EXISTS alpatrade.report_deliveries (
    delivery_id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES alpatrade.user_accounts(account_id) ON DELETE CASCADE,
    report_date DATE NOT NULL,
    report_kind VARCHAR(32) NOT NULL DEFAULT 'daily_paper',
    status VARCHAR(16) NOT NULL DEFAULT 'sending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    UNIQUE (user_id, account_id, report_date, report_kind)
);
