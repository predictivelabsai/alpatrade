-- 42_user_strategies.sql
-- User-owned, shareable trading strategies behind the public /leaderboard.
--
-- A strategy is a single-markdown "skill" (rules prompt + a machine-readable Parameters
-- JSON block) owned by one user. Users can own several; each is private (default) or
-- public, and only public strategies are listed on /leaderboard. "Clone into AlpaTrade"
-- copies a strategy into the cloner's own list as a private row (cloned_from_id set,
-- no live link).
--
--   live_strategy_slug  optional link to the OWNER's live runner run
--                       (alpatrade.runs.mode='live' AND strategy_slug = this AND
--                       user_id = this row's user_id). Leaderboard figures are computed
--                       from that run's daily session-close snapshots at request time;
--                       NULL (e.g. clones) -> figures render as "—".
--   seed_key            idempotent seeds (engine/leaderboard/seed.py); NULL for user rows.
--
-- Idempotent and additive; touches no existing table. Safe to re-run on prod:
--   python run_migration.py sql/42_user_strategies.sql

CREATE TABLE IF NOT EXISTS alpatrade.user_strategies (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID NOT NULL,
    name                VARCHAR(160) NOT NULL,
    author_name         VARCHAR(120),
    description         TEXT NOT NULL DEFAULT '',
    skill_md            TEXT NOT NULL DEFAULT '',
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,
    live_strategy_slug  VARCHAR(96),
    seed_key            VARCHAR(96) UNIQUE,
    cloned_from_id      INTEGER REFERENCES alpatrade.user_strategies(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_strategies_user ON alpatrade.user_strategies (user_id);
CREATE INDEX IF NOT EXISTS idx_user_strategies_public ON alpatrade.user_strategies (is_public)
    WHERE is_public;
