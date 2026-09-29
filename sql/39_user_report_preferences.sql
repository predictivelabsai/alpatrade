-- 39_user_report_preferences.sql
-- Per-user opt-in/opt-out for the daily email reports, edited on /settings and read
-- by both senders in engine/autonomy/schedule.py:
--   report_live_daily  -> scripts/daily_live_report.py  (default ON)
--   report_paper_daily -> scripts/daily_pnl_report.py   (default OFF)
-- A user with no row gets the column defaults (engine/reporting/preferences.py).
-- Kept out of alpatrade.user_settings because those columns are provider-name
-- strings merged into engine.config.get_settings().
-- Idempotent and additive; safe to re-run on prod:
--   python run_migration.py sql/39_user_report_preferences.sql

CREATE TABLE IF NOT EXISTS alpatrade.user_report_preferences (
    user_id UUID PRIMARY KEY REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    report_live_daily  BOOLEAN NOT NULL DEFAULT TRUE,
    report_paper_daily BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Preserve the paper report for users who were actually receiving it when this
-- preference was introduced (a successful daily_paper delivery in the last 14 days);
-- everyone else falls back to the OFF default. ON CONFLICT DO NOTHING means a re-run
-- never overrides a choice the user has since saved on /settings.
INSERT INTO alpatrade.user_report_preferences (user_id, report_live_daily, report_paper_daily)
SELECT DISTINCT d.user_id, TRUE, TRUE
FROM alpatrade.report_deliveries d
WHERE d.report_kind = 'daily_paper'
  AND d.status = 'sent'
  AND d.report_date >= CURRENT_DATE - 14
ON CONFLICT (user_id) DO NOTHING;
