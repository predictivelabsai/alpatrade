-- 24_runs_heartbeat.sql
-- Heartbeat + terminal-state hygiene for alpatrade.runs.
--
-- Paper runs are inserted as 'running' and only moved to a terminal status when
-- the orchestrator process finishes the session cleanly. On redeploy/restart/
-- SIGTERM/SIGKILL the process dies first, so the row stays 'running' forever and
-- the daily report shows "+N older runs ... still marked running" ("zombies").
-- A live paper session now stamps heartbeat_at each cycle; the autonomy worker
-- sweeps paper runs whose heartbeat has gone stale to 'stale' (the same terminal
-- status the report's reconcile uses; distinct from a deliberate 'stopped').

ALTER TABLE alpatrade.runs
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

-- Partial index keeps the sweep and the report's "running" lookups cheap.
CREATE INDEX IF NOT EXISTS idx_runs_paper_running
    ON alpatrade.runs (mode, status)
    WHERE status = 'running';

-- One-time cleanup: finalize already-orphaned paper runs. Pre-migration rows have
-- no heartbeat, so fall back to started_at/created_at to judge staleness.
UPDATE alpatrade.runs
SET status = 'stale',
    completed_at = COALESCE(completed_at, NOW())
WHERE mode = 'paper'
  AND status = 'running'
  AND COALESCE(heartbeat_at, started_at, created_at) < NOW() - INTERVAL '30 minutes';
