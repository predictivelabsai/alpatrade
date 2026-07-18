-- 15_autonomy.sql
-- Durable state for the autonomous agent team (Phase B). Postgres-only: run state +
-- checkpoints live here; the DB-backed queue (claimed via FOR UPDATE SKIP LOCKED) means
-- a crashed worker never loses a run (requeue_unfinished rebuilds the runnable set).
-- Paper-only: nothing here can place a live order — promotions are recommendations only.

CREATE TABLE IF NOT EXISTS alpatrade.autonomy_runs (
    run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind         VARCHAR(32)  NOT NULL DEFAULT 'full',      -- full | backtest | paper | ...
    status       VARCHAR(24)  NOT NULL DEFAULT 'queued',    -- queued|running|done|failed|cancelled
    config       JSONB,
    user_id      UUID REFERENCES alpatrade.users(user_id) ON DELETE SET NULL,
    account_id   UUID,
    attempt      INT          NOT NULL DEFAULT 0,
    claimed_by   VARCHAR(64),
    heartbeat_at TIMESTAMPTZ,
    error        TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_autonomy_runs_status ON alpatrade.autonomy_runs(status, created_at);

-- One row per pipeline node = the resumable checkpoint (UNIQUE lets a resumed run skip
-- nodes already completed).
CREATE TABLE IF NOT EXISTS alpatrade.autonomy_run_steps (
    id         SERIAL PRIMARY KEY,
    run_id     UUID NOT NULL REFERENCES alpatrade.autonomy_runs(run_id) ON DELETE CASCADE,
    node       VARCHAR(48) NOT NULL,
    status     VARCHAR(24) NOT NULL DEFAULT 'done',         -- done | failed
    input      JSONB,
    output     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, node)
);

CREATE TABLE IF NOT EXISTS alpatrade.autonomy_events (
    id         SERIAL PRIMARY KEY,
    run_id     UUID REFERENCES alpatrade.autonomy_runs(run_id) ON DELETE CASCADE,
    level      VARCHAR(16) NOT NULL DEFAULT 'info',
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_autonomy_events_run ON alpatrade.autonomy_events(run_id, created_at);

-- paper→live promotion CANDIDATES (recommendations for a human; the system never trades live).
CREATE TABLE IF NOT EXISTS alpatrade.autonomy_promotions (
    id            SERIAL PRIMARY KEY,
    run_id        UUID REFERENCES alpatrade.autonomy_runs(run_id) ON DELETE SET NULL,
    strategy_slug VARCHAR(128),
    symbol        VARCHAR(16),
    evidence      JSONB,                                    -- sharpe/return/drawdown/equity refs
    status        VARCHAR(24) NOT NULL DEFAULT 'candidate', -- candidate|reviewed|dismissed
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
