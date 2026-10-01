-- 40_strategy_configs.sql
-- Shared, DB-backed parameters for live strategy runners, so every instance (HP primary,
-- Mac backup, box tertiary) reads the SAME params instead of argparse defaults plus
-- per-machine scheduler flags. Read by scripts/live_btd_minhold.py via
-- utils/live_btd_config.py (--strategy / $BTD_STRATEGY, default = the row below).
--
-- Why a new table: prod has no alpatrade strategy-config table. sql/03 (public.strategies)
-- was never applied to prod and is a generic, un-schema'd catalogue; alpatrade.runs.config
-- is a per-run snapshot (written by the runner, not read); alpatrade.strategy_candidates
-- holds Hermes research candidates; public.strategy_config belongs to another app.
--
--   params     strategy parameters (symbols, dip/tp/sl, holds, sizing, windows, feed)
--   execution  reusable order-execution settings (regular-hours and extended-hours exits)
--   version    bump on every edit (UPDATE ... SET version = version + 1); logged per pass
--
-- Idempotent and additive; safe to re-run on prod:
--   python run_migration.py sql/40_strategy_configs.sql
-- The seed uses ON CONFLICT DO NOTHING, so a re-run never overwrites edited params.

CREATE TABLE IF NOT EXISTS alpatrade.strategy_configs (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(96) NOT NULL UNIQUE,      -- lookup key (--strategy / BTD_STRATEGY)
    display_name  VARCHAR(255),
    description   TEXT,
    params        JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution     JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    VARCHAR(128)
);

-- Live Mag-7 BTD: exactly the params in effect on the HP primary on 2026-10-01
-- (systemd ExecStart `--live --pos-frac 0.142857` + script defaults).
-- extended_hours_exit.enabled = false keeps today's behaviour (the runner only exits in
-- the regular session) until it is deliberately switched on in this row.
INSERT INTO alpatrade.strategy_configs (name, display_name, description, params, execution, updated_by)
VALUES (
    'buy_the_dip_mag7_minhold_live',
    'Mag-7 BTD min-hold 3d',
    'Live Mag-7 buy-the-dip, true calendar min-hold (scripts/live_btd_minhold.py)',
    '{"symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
      "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
      "pos_frac": 0.142857, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
      "entry_window": "15-5", "close_window": "15-2"}'::jsonb,
    '{"regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
      "extended_hours_exit": {"enabled": false, "order_type": "limit", "limit_ref": "bid",
                              "discount_bps": 15, "reprice_after_min": 5, "max_reprices": 2,
                              "fallback": "market_day_at_regular_open"}}'::jsonb,
    'sql/40_strategy_configs.sql'
)
ON CONFLICT (name) DO NOTHING;
