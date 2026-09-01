-- Activation funnel events (Start Here plan, phase 3).
-- One row per (user, event); the first occurrence wins — emitters use
-- ON CONFLICT DO NOTHING. Events: registered, keys_connected,
-- first_backtest, first_paper_run. Constrained to the alpatrade schema.

CREATE TABLE IF NOT EXISTS alpatrade.activation_events (
    id        BIGSERIAL PRIMARY KEY,
    user_id   UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    event     VARCHAR(32) NOT NULL,
    first_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meta      JSONB,
    UNIQUE (user_id, event)
);

CREATE INDEX IF NOT EXISTS idx_activation_events_event_time
    ON alpatrade.activation_events(event, first_at);

-- Backfill registrations for users that predate the table, so the funnel
-- denominator reflects every account that exists — not only new signups.
INSERT INTO alpatrade.activation_events (user_id, event, first_at)
SELECT u.user_id, 'registered', u.created_at
FROM alpatrade.users u
ON CONFLICT (user_id, event) DO NOTHING;

-- Align historical activity with the checklist's done-ness, which reads the
-- runs table: anyone with a stored backtest/paper run has, in fact, done it.
INSERT INTO alpatrade.activation_events (user_id, event, first_at)
SELECT r.user_id, e.event, MIN(r.created_at)
FROM alpatrade.runs r
CROSS JOIN (VALUES ('first_backtest'), ('first_paper_run')) AS e(event)
WHERE r.user_id IS NOT NULL
  AND ((e.event = 'first_backtest' AND r.mode = 'backtest')
   OR  (e.event = 'first_paper_run' AND r.mode = 'paper'))
GROUP BY r.user_id, e.event
ON CONFLICT (user_id, event) DO NOTHING;