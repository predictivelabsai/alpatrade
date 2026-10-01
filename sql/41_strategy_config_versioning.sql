-- 41_strategy_config_versioning.sql
-- Every edit of alpatrade.strategy_configs bumps `version` (unless the UPDATE already did),
-- stamps updated_at, and fires NOTIFY strategy_config_changed '<name>:<version>'.
-- The live BTD schedulers cache the row in memory and compare only `version` (every 15 min
-- and at the open / first entry / close events), so any edit reaches all three machines
-- without a restart. Force a reload without changing params:
--   python scripts/live_btd_config.py bump      (or: kill -HUP <scheduler pid> on one machine)
-- Idempotent; safe to re-run:  python run_migration.py sql/41_strategy_config_versioning.sql

CREATE OR REPLACE FUNCTION alpatrade.strategy_configs_touch() RETURNS trigger AS $$
BEGIN
    IF (NEW.params IS DISTINCT FROM OLD.params OR NEW.execution IS DISTINCT FROM OLD.execution
        OR NEW.is_active IS DISTINCT FROM OLD.is_active) AND NEW.version = OLD.version THEN
        NEW.version := OLD.version + 1;
    END IF;
    NEW.updated_at := NOW();
    IF NEW.version IS DISTINCT FROM OLD.version THEN
        PERFORM pg_notify('strategy_config_changed', NEW.name || ':' || NEW.version);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_strategy_configs_touch ON alpatrade.strategy_configs;
CREATE TRIGGER trg_strategy_configs_touch
    BEFORE UPDATE ON alpatrade.strategy_configs
    FOR EACH ROW EXECUTE FUNCTION alpatrade.strategy_configs_touch();
