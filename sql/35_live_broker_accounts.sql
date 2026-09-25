-- 35_live_broker_accounts.sql
-- Read-only links from an AlpaTrade user to a LIVE Alpaca account, shown on the
-- GET-only /live/account page. Deliberately NOT alpatrade.user_accounts: every
-- paper/trading code path reads user_accounts, so live keys stored here can never
-- be picked up by chat trading tools, paper jobs, reconcile or cleanup.
-- Keys are Fernet-encrypted by the application (engine.auth.encrypt_key).
-- Apply with: python run_migration.py sql/35_live_broker_accounts.sql

CREATE TABLE IF NOT EXISTS alpatrade.user_live_broker_accounts (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_number VARCHAR(32) NOT NULL,
    label VARCHAR(255) NOT NULL DEFAULT 'Alpaca live',
    api_key_enc BYTEA NOT NULL,
    secret_key_enc BYTEA NOT NULL,
    api_key_hint VARCHAR(32) NOT NULL DEFAULT '',
    read_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (read_only),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, account_number)
);

CREATE INDEX IF NOT EXISTS idx_user_live_broker_accounts_user
    ON alpatrade.user_live_broker_accounts(user_id);
