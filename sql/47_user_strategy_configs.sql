-- Per-user PAPER strategy configs created by "Clone strategy" (engine/leaderboard/clone_bt.py).
-- Deliberately separate from alpatrade.strategy_configs (read by the live runner by name):
-- nothing here is ever read by a live scheduler, and is_live is pinned to FALSE.
CREATE TABLE IF NOT EXISTS alpatrade.user_strategy_configs (
    id                SERIAL PRIMARY KEY,
    user_id           UUID NOT NULL,
    user_strategy_id  INTEGER NOT NULL UNIQUE REFERENCES alpatrade.user_strategies(id) ON DELETE CASCADE,
    template          VARCHAR(32) NOT NULL,
    params            JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution         JSONB NOT NULL DEFAULT '{}'::jsonb,
    mode              VARCHAR(16) NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'simulated')),
    is_live           BOOLEAN NOT NULL DEFAULT FALSE CHECK (is_live = FALSE),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_strategy_configs_user ON alpatrade.user_strategy_configs (user_id);
