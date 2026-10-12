-- Dashboard speed (v0.42.0): the since-start lookup orders a user's runs of one mode by
-- started_at; without this index Postgres sorts every run row (runs is ~1 GB of JSONB).
CREATE INDEX IF NOT EXISTS idx_runs_user_mode_started
    ON alpatrade.runs (user_id, mode, started_at DESC);
