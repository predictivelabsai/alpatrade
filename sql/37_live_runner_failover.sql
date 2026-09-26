-- 37_live_runner_failover.sql
-- Authoritative state + leader lease for the live BTD runner (scripts/live_btd_minhold.py),
-- so two instances (HP primary, Mac backup) never both trade and neither loses track of
-- positions. See utils/live_btd_state.py for the protocol. The runner also creates these
-- tables lazily (CREATE TABLE IF NOT EXISTS) on first use.
-- Apply with: python run_migration.py sql/37_live_runner_failover.sql
-- Seed once:  python scripts/live_btd_minhold.py --seed-state --seed-run-id <run uuid>

CREATE TABLE IF NOT EXISTS alpatrade.live_runner_state (
    runner_key        VARCHAR(96) PRIMARY KEY,     -- '<strategy_slug>:<alpaca account number>'
    run_id            VARCHAR(64),                 -- alpatrade.runs row the runner records into
    state             JSONB NOT NULL DEFAULT '{}'::jsonb,  -- positions, last_entry, rec{run_id, pending, ...}
    version           BIGINT NOT NULL DEFAULT 0,
    lease_holder      VARCHAR(128),                -- instance name (BTD_INSTANCE)
    lease_host        VARCHAR(255),
    lease_role        VARCHAR(16),                 -- primary | backup
    lease_acquired_at TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by        VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS alpatrade.live_runner_heartbeats (
    runner_key     VARCHAR(96) NOT NULL,
    instance       VARCHAR(128) NOT NULL,
    host           VARCHAR(255),
    role           VARCHAR(16),
    mode           VARCHAR(16),
    last_pass_at   TIMESTAMPTZ,                    -- every --live pass (acting or standby)
    last_acted_at  TIMESTAMPTZ,                    -- last pass that held the lease
    last_decision  VARCHAR(32),                    -- act | renew | takeover | standby | handback | holdoff | missing
    last_detail    TEXT,
    code_version   VARCHAR(64),
    PRIMARY KEY (runner_key, instance)
);
