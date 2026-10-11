-- Settings > Integrations "Check" button: last read-only Alpaca check per saved key.
ALTER TABLE alpatrade.user_accounts ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE alpatrade.user_accounts ADD COLUMN IF NOT EXISTS last_check_result TEXT;
ALTER TABLE alpatrade.user_live_broker_accounts ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE alpatrade.user_live_broker_accounts ADD COLUMN IF NOT EXISTS last_check_result TEXT;
