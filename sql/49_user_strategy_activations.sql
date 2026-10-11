-- Per-user strategy activations from chat ("Activate Paper" / "Activate Live" after a clone or
-- backtest; engine/leaderboard/activate.py). Additive and idempotent.
--   mode paper : a deepagent_paper job on the user's own Alpaca PAPER account (job_id).
--   mode live  : an explicitly confirmed, cash-only request for the user's own linked LIVE
--                account, with its sleeve allocation and client_order_id prefix
--                (utils/strategy_allocation.py). status 'pending_runner' = recorded and
--                validated; the shared live runner does NOT trade it until an operator enables
--                per-user live sleeves (it never reads this table today).
CREATE TABLE IF NOT EXISTS alpatrade.user_strategy_activations (
    id                SERIAL PRIMARY KEY,
    user_id           UUID NOT NULL,
    user_strategy_id  INTEGER NOT NULL REFERENCES alpatrade.user_strategies(id) ON DELETE CASCADE,
    mode              VARCHAR(8) NOT NULL CHECK (mode IN ('paper', 'live')),
    account_ref       VARCHAR(64) NOT NULL,
    cid_prefix        VARCHAR(12),
    allocation_usd    NUMERIC(14,2) CHECK (allocation_usd IS NULL OR allocation_usd > 0),
    cash_only         BOOLEAN NOT NULL DEFAULT TRUE CHECK (cash_only),
    status            VARCHAR(24) NOT NULL,
    job_id            VARCHAR(64),
    confirmed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, user_strategy_id, mode)
);
CREATE UNIQUE INDEX IF NOT EXISTS user_strategy_activations_prefix
    ON alpatrade.user_strategy_activations (account_ref, cid_prefix) WHERE cid_prefix IS NOT NULL;
