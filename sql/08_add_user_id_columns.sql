-- Add user_id to existing tables for multi-user support.
-- Nullable so existing CLI data (user_id=NULL) still works.

ALTER TABLE alpatrade.runs
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES alpatrade.users(user_id);

ALTER TABLE alpatrade.trades
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES alpatrade.users(user_id);

ALTER TABLE alpatrade.backtest_summaries
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES alpatrade.users(user_id);

ALTER TABLE alpatrade.validations
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES alpatrade.users(user_id);

-- Indexes for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_runs_user_id ON alpatrade.runs(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_user_id ON alpatrade.trades(user_id);
CREATE INDEX IF NOT EXISTS idx_backtest_summaries_user_id ON alpatrade.backtest_summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_validations_user_id ON alpatrade.validations(user_id);
