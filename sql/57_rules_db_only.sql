-- 57_rules_db_only.sql (v0.55.0): every BTD trading rule/parameter lives in the DB only.
-- Julian 2026-10-21. Before this, missing keys were filled from code constants
-- (utils/live_btd_config.DEFAULT_PARAMS / DEFAULT_EXECUTION, utils/user_live_runner.NEUTRAL) and
-- stop exemptions came from the BTD_STOP_EXEMPT env var. This migration writes the values those
-- fallbacks produced INTO the rows, unchanged, so behaviour is identical; the code then refuses
-- to run a rule set with a missing key (fails safe: no entries, resting stops stay).
--
-- New keys (all seeded so nothing changes until Julian edits them after seeing the backtest):
--   params.session_mode   'regular' | 'stops_24_5' | 'full_24_5'   seed: 'regular' (today's behaviour)
--   params.stop_exempt    {"SYM": "YYYY-MM-DD"}                     seed: {} (BTD_STOP_EXEMPT was unset on the HP)
--   execution.extended_hours_exit.max_spread_bps                    seed: 50 (quote sanity guard; only read when
--                                                                    session_mode != 'regular')
-- Existing values always win (jsonb: seed || existing). Idempotent; safe to re-run:
--   python run_migration.py sql/57_rules_db_only.sql

-- operator sleeves (Mag-7 #1, Semi-7 #3, any other row)
UPDATE alpatrade.strategy_configs SET
  params = '{"dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3, "pos_frac": 0.10,
             "max_exposure": 0.0, "ref": "high20", "feed": "iex", "entry_window": "15-5", "close_window": "15-2",
             "regime_filter": "", "stop_mode": "pct", "stop_k": 2.0, "tp_mult": 0.0, "stop_timing": "always",
             "vol_filter": "off", "vol_max": 4.0, "regime_mode": "low5", "regime_sma": 200, "max_exposure_pct": 0.0,
             "session_mode": "regular", "stop_exempt": {}}'::jsonb || params,
  execution = jsonb_build_object(
     'regular_hours_exit', '{"order_type": "market", "time_in_force": "day"}'::jsonb || COALESCE(execution->'regular_hours_exit', '{}'::jsonb),
     'extended_hours_exit', '{"enabled": false, "order_type": "limit", "limit_ref": "bid", "discount_bps": 15,
                              "reprice_after_min": 5, "max_reprices": 2, "fallback": "market_day_at_regular_open",
                              "max_spread_bps": 50}'::jsonb || COALESCE(execution->'extended_hours_exit', '{}'::jsonb)),
  updated_by = 'migration 57 (rules db-only, values unchanged)'
WHERE NOT (params ? 'session_mode' AND params ? 'stop_exempt' AND params ? 'stop_mode'
           AND execution->'extended_hours_exit' ? 'max_spread_bps');

-- per-user configs and param versions: the old NEUTRAL fill-ins become stored values
-- (guarded: those tables arrive with sql/47 and sql/56)
DO $m57$
BEGIN
IF to_regclass('alpatrade.user_strategy_configs') IS NOT NULL THEN
UPDATE alpatrade.user_strategy_configs SET
  params = '{"min_hold": 0, "max_exposure": 0.0, "ref": "high20", "feed": "iex", "entry_window": "15-5",
             "close_window": "15-2", "regime_filter": "", "stop_mode": "pct", "stop_k": 2.0, "tp_mult": 0.0,
             "stop_timing": "always", "vol_filter": "off", "vol_max": 4.0, "regime_mode": "low5",
             "regime_sma": 200, "max_exposure_pct": 0.0, "session_mode": "regular", "stop_exempt": {}}'::jsonb
           || COALESCE(params, '{}'::jsonb),
  -- user_live_runner forced extended_hours_exit.enabled=false; store exactly that (override code removed)
  execution = jsonb_build_object(
     'regular_hours_exit', '{"order_type": "market", "time_in_force": "day"}'::jsonb || COALESCE(execution->'regular_hours_exit', '{}'::jsonb),
     'extended_hours_exit', COALESCE(execution->'extended_hours_exit', '{}'::jsonb)
        || '{"enabled": false}'::jsonb
        || '{"order_type": "limit", "limit_ref": "bid", "discount_bps": 15, "reprice_after_min": 5, "max_reprices": 2,
             "fallback": "market_day_at_regular_open", "max_spread_bps": 50}'::jsonb
           - ARRAY(SELECT jsonb_object_keys(COALESCE(execution->'extended_hours_exit', '{}'::jsonb)))
  )
WHERE NOT (COALESCE(params, '{}'::jsonb) ? 'session_mode' AND COALESCE(execution, '{}'::jsonb)->'extended_hours_exit' ? 'max_spread_bps');
END IF;
IF to_regclass('alpatrade.strategy_param_versions') IS NOT NULL THEN
UPDATE alpatrade.strategy_param_versions SET
  params = '{"min_hold": 0, "max_exposure": 0.0, "ref": "high20", "feed": "iex", "entry_window": "15-5",
             "close_window": "15-2", "regime_filter": "", "stop_mode": "pct", "stop_k": 2.0, "tp_mult": 0.0,
             "stop_timing": "always", "vol_filter": "off", "vol_max": 4.0, "regime_mode": "low5",
             "regime_sma": 200, "max_exposure_pct": 0.0, "session_mode": "regular", "stop_exempt": {}}'::jsonb || params
WHERE NOT params ? 'session_mode';
END IF;
END
$m57$;
