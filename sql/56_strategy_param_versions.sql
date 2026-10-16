-- 56_strategy_param_versions.sql (v0.51.0): versioned, user-editable strategy parameters.
-- Every edit (Parameters form, chat confirmation, API) inserts a new DRAFT version; nothing here
-- changes a running activation. A version reaches an activation only through apply
-- (engine/leaderboard/params.py): paper at once; live after a completed walk-forward run and a
-- typed LIVE confirmation. Applies/edits are also logged to alpatrade.activation_events.
CREATE TABLE IF NOT EXISTS alpatrade.strategy_param_versions (
    id                SERIAL PRIMARY KEY,
    user_id           UUID NOT NULL,
    user_strategy_id  INTEGER NOT NULL REFERENCES alpatrade.user_strategies(id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    params            JSONB NOT NULL,
    status            VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'baseline')),
    parent_id         INTEGER,
    source            VARCHAR(16) NOT NULL DEFAULT 'ui',     -- baseline | ui | chat | api
    note              VARCHAR(300),
    diff              JSONB,
    created_by        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_strategy_id, version)
);
CREATE INDEX IF NOT EXISTS idx_spv_user ON alpatrade.strategy_param_versions (user_id, user_strategy_id);

CREATE TABLE IF NOT EXISTS alpatrade.strategy_wf_runs (
    id                SERIAL PRIMARY KEY,
    user_id           UUID NOT NULL,
    user_strategy_id  INTEGER NOT NULL REFERENCES alpatrade.user_strategies(id) ON DELETE CASCADE,
    version_id        INTEGER NOT NULL REFERENCES alpatrade.strategy_param_versions(id) ON DELETE CASCADE,
    cache_key         VARCHAR(64) NOT NULL,
    status            VARCHAR(16) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'error')),
    progress          VARCHAR(300),
    result            JSONB,
    error             VARCHAR(500),
    cached            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_wf_runs_version ON alpatrade.strategy_wf_runs (version_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_runs_cache ON alpatrade.strategy_wf_runs (cache_key) WHERE status = 'done';

-- Which version an activation runs (NULL = the strategy's user_strategy_configs.params, as before).
ALTER TABLE alpatrade.user_strategy_activations ADD COLUMN IF NOT EXISTS params_version_id INTEGER;
ALTER TABLE alpatrade.user_strategy_activations ADD COLUMN IF NOT EXISTS params_applied_at TIMESTAMPTZ;
